"""The bridge hedge's record (risk-envelope Task 37; spec §3.10.2, §3.10.11, ruling H2).

    python -m scripts.hedge_report            # print the record (read-only)
    python -m scripts.hedge_report --review   # also post the one-page review record, "default: off"

Read-only: the record comes from ``src/reporting/hedge.py`` (premium spent and received, each
pre-registered down leg's cover ratio at the trough and at exit against no hedge, execution against
the approved mid, the rolling 60-session R² of NLV on the instrument). ``--review`` posts the same
text the bridge posts on its own at the glide's end or after 20 zero-size sessions, to the account
thread. No IBKR connection; nothing is written.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.common.logging import setup_logging
from src.common.market_hours import today_et
from src.reporting.hedge import build_report, render, review_record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The bridge hedge's record (read-only)")
    ap.add_argument(
        "--review", action="store_true", help="post the one-page review record (default: off)"
    )
    args = ap.parse_args(argv)
    setup_logging()
    today = today_et()
    if not args.review:
        print(render(build_report(today)))
        return 0
    text = review_record(today=today)
    print(text)
    from src.notify.notices import send_notice

    sent = asyncio.run(send_notice(text))
    print("posted" if sent else "not posted (see the log)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
