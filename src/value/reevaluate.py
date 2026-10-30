"""Re-evaluation (spec §7.1): which triggers fire on a session, how severe the re-evaluation is,
whether it joins the open one, and what it does to the plan. Pure: no I/O. Python decides all of
it; Claude decides none (Part 4's review only ever reads the record).

Triggers 1-5, 7 and 8 are here. Trigger 6 (a Claude kill-trigger within 10% of firing) needs
Claude's kill-triggers and arrives with Part 4. Trigger 5 (news volume) and the earnings dates
arrive as plain data; on their own they only open a re-evaluation: no stop and no exit reads them.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from src.common.config import ValueReevaluationCfg
from src.common.value_types import DayBar, FilingEvent, NewsVolume
from src.value.exits import Reeval
from src.value.residuals import Move

Severity = Literal["minor", "major"]
TriggerKind = Literal["move", "drift", "earnings", "filing", "news", "regime", "quiet"]
PERIODIC = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
EIGHT_K = ("8-K", "8-K/A")
_RANK: dict[str, int] = {"minor": 1, "major": 2}


class Trigger(BaseModel):
    kind: TriggerKind
    severity: Severity
    direction: Literal["up", "down"] | None = None
    item: str | None = None  # the 8-K item a filing trigger fired on
    detail: str = ""


def session_triggers(
    *,
    day: date,
    after: date,
    move: Move | None,
    filings: list[FilingEvent],
    earnings: list[date],
    news: NewsVolume | None,
    regime_stepped: bool,
    last_reevaluation: date,
    cfg: ValueReevaluationCfg,
) -> list[Trigger]:
    """Every trigger that fires on *day* for one position. *after* is the last session already
    checked (a filing or report dated after it and on or before *day* is new);
    *last_reevaluation* is the last re-evaluation's session, or the entry date."""
    out: list[Trigger] = []
    major_move = False
    if move is not None and move.z is not None:
        if abs(move.z) >= cfg.abnormal_z:
            major_move = True
            out.append(
                Trigger(
                    kind="move",
                    severity="major",
                    direction="up" if move.z > 0 else "down",
                    detail=f"residual z {move.z:+.2f} vs the sector ETF (beta {move.beta:.2f})",
                )
            )
    elif move is not None and move.ret is not None and abs(move.ret) * 100 >= cfg.raw_move_pct:
        major_move = True  # the backstop: the history is too short for a residual
        out.append(
            Trigger(
                kind="move",
                severity="major",
                direction="up" if move.ret > 0 else "down",
                detail=f"raw move {move.ret:+.1%} (history too short for a residual)",
            )
        )
    if move is not None and move.drift_z is not None and abs(move.drift_z) >= cfg.drift_z:
        out.append(
            Trigger(
                kind="drift",
                severity="minor",
                direction="up" if move.drift_z > 0 else "down",
                detail=f"{cfg.drift_sessions}-session residual z {move.drift_z:+.2f}",
            )
        )
    for report in earnings:
        if after < report <= day:
            out.append(
                Trigger(
                    kind="earnings",
                    severity="major" if major_move else "minor",
                    detail=f"earnings reported {report}",
                )
            )
            break
    for f in filings:
        if not after < f.filed <= day:
            continue
        if f.form in PERIODIC:
            out.append(Trigger(kind="filing", severity="minor", detail=f"{f.form} {f.accn}"))
        elif f.form in EIGHT_K:
            major = [i for i in f.items if i in cfg.major_8k_items]
            minor = [i for i in f.items if i in cfg.minor_8k_items]
            if major:
                out.append(
                    Trigger(
                        kind="filing",
                        severity="major",
                        item=major[0],
                        detail=f"8-K item {major[0]} ({f.accn})",
                    )
                )
            elif minor:
                out.append(
                    Trigger(
                        kind="filing",
                        severity="minor",
                        item=minor[0],
                        detail=f"8-K item {minor[0]} ({f.accn})",
                    )
                )
    if (
        news is not None
        and news.last_24h >= cfg.news_min_items
        and news.last_24h >= cfg.news_multiple * news.daily_median_30d
    ):
        out.append(
            Trigger(
                kind="news",
                severity="minor",
                detail=f"{news.last_24h} items in 24h vs a daily median of {news.daily_median_30d:g}",
            )
        )
    if regime_stepped:
        out.append(Trigger(kind="regime", severity="minor", detail="the market regime stepped"))
    if (day - last_reevaluation).days >= cfg.quiet_days:
        out.append(
            Trigger(
                kind="quiet",
                severity="minor",
                detail=f"no re-evaluation since {last_reevaluation}",
            )
        )
    return out


_REGIME_ORDER = ("normal", "cautious", "stressed", "crisis")


def regime_stepped(previous: str | None, now: str, cfg: ValueReevaluationCfg) -> bool:
    """Trigger 7: the market regime stepped *into* one of ``regime_states`` (stressed to crisis
    included) since the previous night. An unknown previous regime is never a step."""
    states = {str(r) for r in cfg.regime_states}
    if previous is None or now not in states or previous not in _REGIME_ORDER:
        return False
    return _REGIME_ORDER.index(now) > _REGIME_ORDER.index(previous)


def severity(triggers: list[Trigger]) -> Severity | None:
    """The re-evaluation's severity: its most severe trigger's; None when nothing fired."""
    if not triggers:
        return None
    return "major" if any(t.severity == "major" for t in triggers) else "minor"


def joins(
    open_severity: Severity | None,
    sessions_since_open: int | None,
    new: Severity,
    cfg: ValueReevaluationCfg,
) -> bool:
    """One re-evaluation is open per position at a time: a trigger within ``debounce_sessions``
    of the open one joins it, unless its severity is higher (spec §7.1)."""
    if open_severity is None or sessions_since_open is None:
        return False
    return sessions_since_open <= cfg.debounce_sessions and _RANK[new] <= _RANK[open_severity]


def plan_actions(
    triggers: list[Trigger],
    bar: DayBar,
    before: DayBar | None,
    cfg: ValueReevaluationCfg,
) -> Reeval | None:
    """What the session's triggers do to the plan at its close (spec §7.1, "What a
    re-evaluation does"). A Major move is a shock: down, the stop rises to at least the shock
    session's low - ``down_shock_atr`` x ATR(14) measured before the shock (no ATR, no shock
    stop: unknown is never zero); up, the trail arms from the shock low. A Major 8-K item is a
    thesis exit. Every other trigger changes nothing but the record. None when nothing changes."""
    shock = next((t for t in triggers if t.kind == "move" and t.severity == "major"), None)
    thesis = next(
        (t for t in triggers if t.kind == "filing" and t.severity == "major" and t.item), None
    )
    low = bar.low if bar.low is not None else bar.close
    atr = before.atr14 if before is not None else None
    stop = None
    arm = None
    if shock is not None and shock.direction == "down" and atr is not None:
        stop = low - cfg.down_shock_atr * atr
    if shock is not None and shock.direction == "up":
        arm = low
    if stop is None and arm is None and thesis is None:
        return None
    return Reeval(
        stop_at_least=stop,
        arm_from=arm,
        thesis=None if thesis is None else f"8-K item {thesis.item}",
    )
