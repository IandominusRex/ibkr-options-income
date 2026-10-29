"""The calibration dry run's pass funnel (spec §17). Pure: no I/O.

How many names fall at each step: data quality, not applicable, each health gate, each list's
entry rule, fair value, margin of safety and timing, and the verdicts that come out.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from src.value.schemas import LISTS, Check, ValueScorecard


class GateTally(BaseModel):
    passed: int = 0
    failed: int = 0
    unknown: int = 0
    not_applicable: int = 0

    def add(self, check: Check) -> None:
        if check.state == "pass":
            self.passed += 1
        elif check.state == "fail":
            self.failed += 1
        elif check.state == "unknown":
            self.unknown += 1
        else:
            self.not_applicable += 1


class ListFunnel(BaseModel):
    scored: int = 0  # healthy names evaluated on the list
    entry: dict[str, GateTally] = Field(default_factory=dict)
    entry_pass: int = 0
    fair_value: int = 0
    mos_pass: int = 0
    timing: dict[str, GateTally] = Field(default_factory=dict)
    timing_pass: int = 0
    verdicts: Counter[str] = Field(default_factory=Counter)


class Funnel(BaseModel):
    names: int = 0
    classes: Counter[str] = Field(default_factory=Counter)
    etf: int = 0
    data_quality_pass: int = 0
    data_quality: dict[str, GateTally] = Field(default_factory=dict)
    not_applicable: Counter[str] = Field(default_factory=Counter)
    health: dict[str, dict[str, GateTally]] = Field(default_factory=dict)  # class -> gate -> tally
    health_states: Counter[str] = Field(default_factory=Counter)
    lists: dict[str, ListFunnel] = Field(default_factory=dict)


def build_funnel(cards: list[ValueScorecard]) -> Funnel:
    f = Funnel(names=len(cards), lists={name: ListFunnel() for name in LISTS})
    for card in cards:
        f.classes[card.company_class] += 1
        if card.company_class == "etf":
            f.etf += 1
            continue
        for c in card.data_quality_checks:
            f.data_quality.setdefault(c.id, GateTally()).add(c)
        if card.data_quality != "pass":
            continue
        f.data_quality_pass += 1
        if card.not_applicable_reason is not None:
            f.not_applicable[card.not_applicable_reason] += 1
            continue
        group = "bank/insurer" if card.company_class in ("bank", "insurer") else card.company_class
        gates = f.health.setdefault(group, {})
        for c in card.health_checks:
            gates.setdefault(c.id, GateTally()).add(c)
        f.health_states[card.health] += 1
        for name, ev in card.lists.items():
            lf = f.lists[name]
            lf.verdicts[ev.verdict] += 1
            if card.health != "pass":
                continue
            lf.scored += 1
            for c in ev.entry_checks:
                lf.entry.setdefault(c.id, GateTally()).add(c)
            if ev.entry != "pass":
                continue
            lf.entry_pass += 1
            if ev.fair_value is None:
                continue
            lf.fair_value += 1
            if ev.verdict == "WAIT":
                continue
            lf.mos_pass += 1
            for c in ev.timing_checks:
                lf.timing.setdefault(c.id, GateTally()).add(c)
            if ev.timing == "pass":
                lf.timing_pass += 1
    return f


def _tally(t: GateTally) -> str:
    return f"pass {t.passed:>4}  fail {t.failed:>4}  unknown {t.unknown:>4}"


def render_funnel(f: Funnel, title: str) -> str:
    lines = [f"== {title}: {f.names} names ==", f"classes: {dict(f.classes)}"]
    lines.append(f"ETFs (not applicable): {f.etf}")
    lines.append(f"data quality pass: {f.data_quality_pass}")
    for gate, t in sorted(f.data_quality.items()):
        lines.append(f"  {gate:<28} {_tally(t)}")
    lines.append(f"not applicable: {dict(f.not_applicable)}")
    lines.append(f"health: {dict(f.health_states)}")
    for group, gates in sorted(f.health.items()):
        lines.append(f"  [{group}]")
        for gate, t in sorted(gates.items()):
            lines.append(f"    {gate:<28} {_tally(t)}")
    for name, lf in f.lists.items():
        lines.append(f"-- {name} --")
        lines.append(f"  healthy and scored: {lf.scored}")
        for gate, t in sorted(lf.entry.items()):
            lines.append(f"    entry {gate:<22} {_tally(t)}")
        lines.append(f"  entry rule pass: {lf.entry_pass}")
        lines.append(f"  fair value present: {lf.fair_value}")
        lines.append(f"  margin of safety met: {lf.mos_pass}")
        for gate, t in sorted(lf.timing.items()):
            lines.append(f"    {gate:<28} {_tally(t)}")
        lines.append(f"  timing pass (READY): {lf.timing_pass}")
        lines.append(f"  verdicts: {dict(lf.verdicts)}")
    return "\n".join(lines)


def _num(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else f"{v:,.2f}"


def render_name(card: ValueScorecard) -> str:
    """Every number for one name (spec §17: GOOGL, META, BAC and MU by name)."""
    lines = [
        f"## {card.symbol}  class={card.company_class}  price={_num(card.price)}  "
        f"data_quality={card.data_quality}  health={card.health}",
    ]
    if card.not_applicable_reason:
        lines.append(f"  not applicable: {card.not_applicable_reason}")
    for c in [*card.data_quality_checks, *card.health_checks]:
        lines.append(
            f"  {c.id:<28} {c.state:<8} actual={_num(c.actual)} bar={_num(c.threshold)} {c.detail}"
        )
    for k, v in card.metrics.items():
        lines.append(f"  {k:<28} {_num(v)}")
    lines.append(
        f"  realised FCF/share CAGR {_num(card.realised_fcf_ps_cagr, True)}; "
        f"price implies {_num(card.reverse_dcf_implied_growth, True)}/yr (reverse DCF)"
    )
    if card.adjustments:
        lines.append(f"  adjustments: {'; '.join(card.adjustments)}")
    for name, ev in card.lists.items():
        methods = ", ".join(f"{m.method}={_num(m.value)}({m.state})" for m in ev.methods)
        lines.append(
            f"  [{name}] {ev.verdict}: fair value {_num(ev.fair_value)} ({methods}); "
            f"MoS {_num(ev.margin_of_safety, True)} vs {ev.required_mos_pct:.0f}% required; "
            f"ceiling {_num(ev.entry_ceiling)}; entry {ev.entry}; timing {ev.timing}"
        )
        for c in [*ev.entry_checks, *ev.timing_checks]:
            lines.append(
                f"      {c.id:<26} {c.state:<8} actual={_num(c.actual)} bar={_num(c.threshold)} {c.detail}"
            )
        lines.append(f"      why: {'; '.join(ev.reasons)}")
    return "\n".join(lines)
