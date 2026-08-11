"""Build the focused roll prompt sent to `claude -p` when a trigger fires."""

from __future__ import annotations

from src.common.schemas import OptionQuote, PositionSnapshot, RollAlert


def build_roll_prompt(alert: RollAlert, pos: PositionSnapshot, quote: OptionQuote) -> str:
    """Return the prompt string for a single-position roll/hold/close decision."""
    right_label = pos.right.value if pos.right else "?"
    strategy = "Covered Call" if right_label == "C" else "Cash-Secured Put"

    lines: list[str] = [
        "You are a disciplined options income strategist. A trigger has fired on an open "
        f"short {strategy} position. Evaluate whether to roll, hold, or close.",
        "",
    ]
    lines += [
        "=== POSITION ===",
        f"Symbol:     {pos.symbol}",
        f"Underlying: {pos.underlying}  ({right_label})",
    ]
    if pos.strike is not None:
        lines.append(f"Strike:     ${pos.strike:.2f}")
    if pos.expiry is not None:
        lines.append(f"Expiry:     {pos.expiry}")
    if pos.delta is not None:
        lines.append(f"Entry delta:{pos.delta:.3f}")
    lines.append(f"Qty:        {pos.position:.0f} contracts")

    lines += [
        "",
        "=== TRIGGER ===",
        f"Type:   {alert.trigger}",
        f"Detail: {alert.detail}",
    ]

    lines += [
        "",
        "=== LIVE QUOTE ===",
    ]
    if quote.bid is not None and quote.ask is not None:
        lines.append(f"Bid/Ask:  ${quote.bid:.4f} / ${quote.ask:.4f}  (mid ${quote.mid:.4f})")
    if quote.delta is not None:
        lines.append(f"Delta:    {quote.delta:.3f}")
    if quote.iv is not None:
        lines.append(f"IV:       {quote.iv:.2%}")
    if quote.theta is not None:
        lines.append(f"Theta:    {quote.theta:.4f}")
    lines.append(f"DTE:      {quote.dte}")

    lines += [
        "",
        "=== YOUR TASK ===",
        "Recommend roll, hold, or close. Return a single JSON object — no prose, "
        "no markdown fences.",
        "",
        "Schema (all fields required):",
        "{",
        f'  "position_symbol": "{pos.symbol}",',
        '  "recommendation": "<roll | hold | close>",',
        '  "roll_target": "<e.g. roll to $195 Aug 15 CC at 0.28 delta — or empty string if hold/close>",',
        '  "rationale": "<2-3 sentences explaining the decision>",',
        '  "risks": "<2-3 sentences on key risks>",',
        '  "confidence": <float 0.0-1.0>',
        "}",
        "",
        "Return ONLY the JSON object.",
    ]

    return "\n".join(lines)
