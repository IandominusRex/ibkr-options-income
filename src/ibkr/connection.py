"""IBKR connection manager: connect/reconnect with backoff, clientId allocation,
and a hard live/paper safety check.

Every process (engine, monitor, backfill, healthcheck) takes a different clientId
from settings.yaml to avoid TWS conflicts. The trading_skills MCP and the
dashboard use their own ids (20, 21) configured separately.
"""

from __future__ import annotations

import time

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

    def connect(self) -> IB:
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
