"""IBKR connection manager: connect/reconnect with backoff, clientId allocation,
and a hard live/paper safety check.

Every process (engine, monitor, backfill, healthcheck) takes a different clientId
from settings.yaml to avoid TWS conflicts. The trading_skills MCP and the
dashboard use their own ids (20, 21) configured separately.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from collections.abc import Awaitable, Callable

from ib_async import IB

from src.common.config import get_config
from src.common.logging import get_logger

log = get_logger(__name__)


class ConnectionError_(RuntimeError):
    """Raised when we cannot establish or maintain a TWS/Gateway connection."""


class IBKRConnection:
    """Thin lifecycle wrapper around ib_async.IB with reconnect + safety banner.

    Use as a context manager:
        with IBKRConnection("engine") as ib:
            ib.positions()
    """

    def __init__(self, role: str) -> None:
        self.cfg = get_config()
        self.role = role
        self.ib = IB()
        self._client_id = self._resolve_client_id(role)

    def _resolve_client_id(self, role: str) -> int:
        ids = self.cfg.ibkr.client_ids
        if role not in ids:
            raise KeyError(
                f"No clientId configured for role '{role}'. "
                f"Add it under ibkr.client_ids in settings.yaml. Known: {list(ids)}"
            )
        return ids[role]

    def _safety_banner(self) -> None:
        port = self.cfg.ibkr_port
        mode = "LIVE" if self.cfg.is_live else "PAPER"
        # Loud, unmissable: which account are we actually about to touch?
        log.warning(
            "=" * 60
            + f"\n  IBKR MODE: {mode}  |  port={port}  |  clientId={self._client_id}"
            + f"\n  role={self.role}"
            + "\n"
            + "=" * 60
        )
        if self.cfg.is_live:
            # Guard against the classic "live port but LIVE_TRADING not intended".
            log.warning("LIVE_TRADING=true — orders will hit a REAL account.")

    async def connect_async(self) -> IB:
        """Async connect with backoff — for use inside an already-running event loop
        (orchestrators run under asyncio.run, where the sync `connect()` would raise
        'event loop already running')."""
        self._safety_banner()
        host = self.cfg.ibkr.host
        port = self.cfg.ibkr_port
        retries = self.cfg.ibkr.reconnect.max_retries
        base = self.cfg.ibkr.reconnect.backoff_base_seconds

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                await self.ib.connectAsync(
                    host,
                    port,
                    clientId=self._client_id,
                    timeout=self.cfg.ibkr.connect_timeout_seconds,
                )
                self.ib.reqMarketDataType(self.cfg.ibkr.market_data_type)
                log.info(
                    "Connected to IBKR %s:%s (clientId=%s, mktDataType=%s)",
                    host,
                    port,
                    self._client_id,
                    self.cfg.ibkr.market_data_type,
                )
                return self.ib
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                wait = base * (2 ** (attempt - 1))
                log.warning(
                    "Connect attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt,
                    retries,
                    exc,
                    wait,
                )
                if attempt < retries:
                    await asyncio.sleep(wait)

        raise ConnectionError_(
            f"Could not connect to IBKR at {host}:{port} after {retries} attempts. "
            f"Last error: {last_err}"
        )

    async def __aenter__(self) -> IB:
        return await self.connect_async()

    async def __aexit__(self, *_exc: object) -> None:
        self.disconnect()

    def connect(self) -> IB:
        # ProactorEventLoop (Windows default) fails in Python 3.14 due to a
        # broken socket.socketpair() fallback. SelectorEventLoop avoids it.
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        self._safety_banner()
        host = self.cfg.ibkr.host
        port = self.cfg.ibkr_port
        retries = self.cfg.ibkr.reconnect.max_retries
        base = self.cfg.ibkr.reconnect.backoff_base_seconds

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self.ib.connect(
                    host,
                    port,
                    clientId=self._client_id,
                    timeout=self.cfg.ibkr.connect_timeout_seconds,
                )
                self.ib.reqMarketDataType(self.cfg.ibkr.market_data_type)
                log.info(
                    "Connected to IBKR %s:%s (clientId=%s, mktDataType=%s)",
                    host,
                    port,
                    self._client_id,
                    self.cfg.ibkr.market_data_type,
                )
                return self.ib
            except Exception as exc:  # noqa: BLE001 — surface any connect failure
                last_err = exc
                wait = base * (2 ** (attempt - 1))
                log.warning(
                    "Connect attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt,
                    retries,
                    exc,
                    wait,
                )
                if attempt < retries:
                    time.sleep(wait)

        raise ConnectionError_(
            f"Could not connect to IBKR at {host}:{port} after {retries} attempts. "
            f"Is TWS/Gateway running with the API enabled on this port? "
            f"Last error: {last_err}"
        )

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()
            log.info("Disconnected from IBKR (role=%s)", self.role)

    def resolve_account(self) -> str:
        """Return the configured account, or the first managed account if blank."""
        configured = self.cfg.secrets.ibkr_account
        managed = self.ib.managedAccounts()
        if configured:
            if managed and configured not in managed:
                log.warning(
                    "Configured IBKR_ACCOUNT=%s not in managed accounts %s",
                    configured,
                    managed,
                )
            return configured
        if not managed:
            raise ConnectionError_("No managed accounts returned by TWS.")
        return managed[0]

    def __enter__(self) -> IB:
        return self.connect()

    def __exit__(self, *_exc: object) -> None:
        self.disconnect()


class AutoReconnect:
    """Keeps a long-running IB connection alive across TWS/Gateway drops.

    The long-lived daemons (approval_service, intraday monitor) run for hours; ib_async
    does NOT auto-reconnect on its own. Without this, a single socket drop silently blinds
    the monitor and stops order execution. Attach one of these after connecting; it listens
    on `disconnectedEvent` and reconnects with capped exponential backoff. Call `stop()`
    before an intentional `ib.disconnect()` so shutdown doesn't trigger a reconnect storm.
    """

    def __init__(
        self,
        ib: IB,
        host: str,
        port: int,
        client_id: int,
        *,
        market_data_type: int = 1,
        backoff_base: float = 2.0,
        max_backoff: float = 60.0,
        max_reconnect_attempts: int = 20,
        on_reconnect: Callable[[], Awaitable[None]] | None = None,
        label: str = "ibkr",
    ) -> None:
        self._ib = ib
        self._host = host
        self._port = port
        self._client_id = client_id
        self._market_data_type = market_data_type
        self._backoff_base = backoff_base
        self._max_backoff = max_backoff
        self._max_reconnect_attempts = max_reconnect_attempts
        self._on_reconnect = on_reconnect
        self._label = label
        self._stopped = False
        self._reconnecting = False
        ib.disconnectedEvent += self._on_disconnect

    def _on_disconnect(self) -> None:
        if self._stopped or self._reconnecting:
            return
        # Set the flag synchronously before create_task so that a second
        # disconnectedEvent fired before the coroutine starts cannot spawn
        # a second concurrent reconnect loop.
        self._reconnecting = True
        try:
            asyncio.get_running_loop().create_task(self._reconnect_loop())
        except RuntimeError:
            # Fired outside of an event loop (e.g. during teardown). Reset flag
            # and log — suppressing silently would leave _reconnecting=True and
            # block all future reconnect attempts.
            self._reconnecting = False
            log.warning(
                "[%s] disconnectedEvent fired outside event loop — reconnect not scheduled",
                self._label,
            )

    async def _reconnect_loop(self) -> None:
        attempt = 0
        try:
            while not self._stopped and not self._ib.isConnected():
                attempt += 1
                if attempt > self._max_reconnect_attempts:
                    log.critical(
                        "[%s] IBKR reconnect failed after %d attempts — giving up. "
                        "Restart the process to re-enable reconnection.",
                        self._label,
                        self._max_reconnect_attempts,
                    )
                    return
                wait = min(self._backoff_base * (2 ** (attempt - 1)), self._max_backoff)
                log.warning(
                    "[%s] IBKR disconnected — reconnect attempt %d/%d in %.1fs",
                    self._label,
                    attempt,
                    self._max_reconnect_attempts,
                    wait,
                )
                await asyncio.sleep(wait)
                if self._stopped:
                    break
                try:
                    await self._ib.connectAsync(
                        self._host, self._port, clientId=self._client_id, timeout=15.0
                    )
                    self._ib.reqMarketDataType(self._market_data_type)
                    log.warning("[%s] IBKR reconnected (clientId=%s)", self._label, self._client_id)
                    if self._on_reconnect is not None:
                        try:
                            await self._on_reconnect()
                        except Exception:
                            log.exception("[%s] on_reconnect callback failed", self._label)
                    return
                except Exception as exc:  # noqa: BLE001
                    log.warning("[%s] reconnect attempt %d failed: %s", self._label, attempt, exc)
        finally:
            self._reconnecting = False

    def stop(self) -> None:
        """Disable reconnection (call before an intentional disconnect)."""
        self._stopped = True
        with contextlib.suppress(Exception):
            self._ib.disconnectedEvent -= self._on_disconnect


# ---------------------------------------------------------------------------
# Account-summary subscription helpers
# ---------------------------------------------------------------------------


def suppress_account_summary_on_reconnect(ib: IB) -> None:
    """Remove ib_async's automatic reqAccountSummary on Error 1102 for this IB object.

    ib_async fires reqAccountSummaryAsync() on every connected IB object that
    receives Error 1102 (connectivity restored). When two concurrent objects —
    exec (clientId 14) and scan (clientId 15) — both react to 1102, IBKR
    rejects the second with Error 322 ("maximum account summary requests
    exceeded") because only one reqAccountSummary per account is allowed at
    a time. The exec connection never calls accountSummaryAsync() directly, so
    suppressing its auto-subscribe ensures only ib_scan holds the subscription.
    """
    ib.errorEvent -= ib._onError
    _orig = ib._onError

    def _patched(reqId: int, errorCode: int, errorString: str, contract: object) -> None:
        if errorCode != 1102:
            _orig(reqId, errorCode, errorString, contract)

    ib.errorEvent += _patched


def debounce_account_summary_on_reconnect(ib: IB, *, _reconnect_delay: float = 0.5) -> None:
    """Guard the scan IB object against concurrent reqAccountSummary on rapid reconnects.

    During a connection storm (1100 → 1102 → 1100 → 1102 in quick succession),
    ib_async's default _onError fires a new reqAccountSummaryAsync() on each 1102
    before the previous request resolves. IBKR rejects the second with Error 322.
    This replaces the default handler with one that skips resubscription when one
    is already in-flight, then retries naturally on the next scan cycle.

    _reconnect_delay: seconds to wait after 1102 before resubscribing, giving
    IBKR time to clear the previous subscription. Exposed for testing (pass 0).
    """
    _in_flight: list[bool] = [False]

    async def _resubscribe() -> None:
        try:
            await asyncio.sleep(_reconnect_delay)
            await ib.reqAccountSummaryAsync()
        except Exception:
            log.warning("account summary resubscription after 1102 failed", exc_info=True)
        finally:
            _in_flight[0] = False

    ib.errorEvent -= ib._onError
    _orig = ib._onError

    def _patched(reqId: int, errorCode: int, errorString: str, contract: object) -> None:
        if errorCode == 1102:
            if not _in_flight[0]:
                _in_flight[0] = True
                asyncio.ensure_future(_resubscribe())
            return
        _orig(reqId, errorCode, errorString, contract)

    ib.errorEvent += _patched
