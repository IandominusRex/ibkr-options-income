"""The one definition of assignment risk — a short option deep enough in the money, close
enough to expiry that it may be assigned.

Task 0.3 (M0 baseline fixes): this was defined twice, with two different DTE thresholds.
``src/monitor/triggers.py::check_assignment_risk`` read the real config (0.70 delta, 21 DTE)
and fired the Telegram alerts the operator actually acts on. ``src/api/routers/options.py``
hardcoded ``abs(delta) >= 0.70 and dte <= 7`` under a comment that incorrectly claimed 7 was
"the monitor's default" — it was a copy of a copy that drifted from
``config/settings.yaml``'s ``monitor.assignment_alert_dte: 21``. The two surfaces disagreed by
14 days: a position between 8 and 21 DTE was actively alerted on by the monitor while
``/options/shorts`` reported ``assignment_risk: false``.

This module lives in ``src/common/`` deliberately — the only package both the monitor (a
trading process) and the API (a web-layer process, which may never import the trading
process) can reach. It takes plain values (``float``/``int``/``None``), not a
``PositionSnapshot`` and not an ``OptionQuote``, so neither caller has to construct the
other's domain type just to call it.

``check_assignment_risk`` keeps its own signature and keeps building the ``RollAlert`` it
returns — this module only owns the yes/no decision, never alert construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.common.config import Config


def is_assignment_risk(
    *,
    position: float,
    delta: float | None,
    dte: int | None,
    delta_threshold: float,
    dte_threshold: int,
) -> bool:
    """True when a SHORT option is deep enough in the money, close enough to expiry.

    The single definition. src/monitor/triggers.py fires alerts on it and the API reports
    it; before this function they disagreed by 14 days of DTE.

    Missing delta or missing dte is data-unavailable and returns False — never True, and
    never a fabricated signal from an absent field.
    A non-negative `position` is not a short and returns False.
    """
    if position >= 0:
        return False
    if delta is None or dte is None:
        return False
    return abs(delta) >= delta_threshold and dte <= dte_threshold


def assignment_risk_thresholds(cfg: Config) -> tuple[float, int]:
    """(delta_threshold, dte_threshold) from config, so no caller hardcodes either."""
    return cfg.monitor.assignment_alert_delta, cfg.monitor.assignment_alert_dte
