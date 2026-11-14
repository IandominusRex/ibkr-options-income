"""Clear the spreads book's month stop: the human reset (risk-envelope Task 4, ruling E2).

    python -m scripts.spreads_reset_month

The spreads service sets the month stop once the traded book's month to date (realised + open)
reaches -``risk.max_monthly_loss_pct_of_nlv`` (2%) of net liquidation, and no new spreads open
while it is set, across months, until this clears it. A reset inside the month that tripped
changes nothing: the next entry check finds the month still down and sets it again. Prints what
it cleared and sends one notice to the spreads thread. Writes only ``spread_flags`` in
``data/spreads.db``.
"""

from __future__ import annotations

import argparse
import asyncio

from src.spreads import store


def clear() -> str | None:
    """Clear the month stop and print what was cleared; the notice text, or None if unset."""
    store.init_spreads_db()
    cleared = store.month_stop_clear()
    if cleared is None:
        print("no month stop is set: nothing to clear")
        return None
    text = (
        f"Spreads month stop for {cleared.get('month')} cleared by hand "
        f"(month to date ${cleared.get('pnl_usd') or 0:,.0f} against NLV "
        f"${cleared.get('nlv_usd') or 0:,.0f}, set {cleared.get('set_at')}). New entries may "
        "open again on the next entry check, unless this month is down 2% too."
    )
    print(text)
    return text


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description="Clear the spreads month stop").parse_args(argv)
    text = clear()
    if text is not None:
        from src.notify.notices import send_notice

        asyncio.run(send_notice(text, thread="spreads"))


if __name__ == "__main__":
    main()
