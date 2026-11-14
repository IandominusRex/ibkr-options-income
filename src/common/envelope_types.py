"""Plain types for the risk envelope (risk-envelope plan, Tasks 11 and 13; spec §3.4).

Standard-library frozen dataclasses only, no I/O and no imports from the rest of ``src``: the
pure shock engine (``src/analytics/shock.py``), the envelope (``src/engine/envelope.py``), the
value book (Task 20, through the value fence's allowance, code fact C8), the formatters and the
API all exchange these.

Units: every scenario figure is a **percent of net liquidation** (22.3 means 22.3%), a loss
counted positive; ``uew`` is a ratio (1.36 means 136% of NLV); IV is a decimal (0.30 = 30%).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LineKind = Literal["stock", "short_put", "short_call", "long_put", "long_call"]
Scenario = Literal["S10", "S20", "G10", "P20", "T20", "S_SMH"]


@dataclass(frozen=True, slots=True)
class BookLine:
    """One position line as the shock engine sees it.

    ``qty`` is in shares for stock (signed as the broker reports it, negative = short) and in
    contracts for options; for an option the ``kind`` decides the sign and ``|qty|`` counts.
    ``spot`` is the underlying's price (for stock, the share price). ``book`` names where the
    line came from (``wheel``, ``value``, ``hedge``, ``manual`` ...); every book is counted.
    """

    symbol: str
    kind: LineKind
    qty: float
    spot: float
    strike: float | None = None
    dte: int | None = None
    iv: float | None = None
    book: str = "wheel"
    con_id: int | None = None


@dataclass(frozen=True, slots=True)
class ShockInputs:
    """Everything the scenarios read. ``leverage`` maps a leveraged ETF to its daily leverage,
    ``governing`` maps it to the unleveraged index whose beta it moves by; ``betas`` are Blume
    betas to SPY and ``betas_smh`` to SMH (ruling P5)."""

    lines: tuple[BookLine, ...]
    betas: dict[str, float]
    betas_smh: dict[str, float]
    leverage: dict[str, int]
    governing: dict[str, str]
    tech_linked: frozenset[str]
    semis: frozenset[str]
    nlv: float


@dataclass(frozen=True, slots=True)
class ShockResult:
    """The scenario losses, gross (no long option, from any source: H1) and net (long options
    counted), as percent of NLV, plus U_ew. ``unmeasured`` names every symbol whose line the
    *gross* measures could not value (a missing IV, spot or beta, or ``NLV``): gates read it and
    fail closed. ``unmeasured_net`` adds the long options the net measures could not value."""

    s10: float
    s20: float
    g10: float
    p20: float
    t20: float
    s_smh: float
    s10_vol10: float
    s10_net: float
    s20_net: float
    g10_net: float
    p20_net: float
    t20_net: float
    s_smh_net: float
    s10_vol10_net: float
    uew: float
    unmeasured: tuple[str, ...] = ()
    unmeasured_net: tuple[str, ...] = ()

    @property
    def measured(self) -> bool:
        return not self.unmeasured


@dataclass(frozen=True, slots=True)
class EnvelopeRoom:
    """The book against its limits on one day (Task 13). ``enforce`` is the
    ``envelope_enforce`` switch (``off``, ``record`` or ``on``); in ``record`` the limits are
    the would-be start-of-glide values for today. ``measured`` False means a gate must refuse
    with ``envelope_unmeasured``; ``reasons_if_unmeasured`` says why."""

    s10_gross: float
    s10_limit: float
    uew: float
    uew_limit: float
    t20_gross: float
    t20_limit: float | None
    enforce: str
    measured: bool
    reasons_if_unmeasured: tuple[str, ...] = ()
