"""A name's running average cost, in one neutral place (value book Part 6, final review I-C).

Standard library only: the book (``src/value/book.py::totals``) and the API's read-only reader
(``src/api/value_db.py``, which may import nothing from the value package but its scorecard and
schemas) both fold the same orders through this, so neither can drift from the other.

The rule: a buy adds its shares at their price to the position's cost; a sale takes its shares out
at the *current average*, leaving the average of what remains unchanged; a full exit resets the
state, so a re-entry starts afresh. Orders must be folded oldest first.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunningCost:
    qty: float = 0.0  # shares held now
    spent: float = 0.0  # their cost at the running average

    @property
    def avg(self) -> float | None:
        return self.spent / self.qty if self.qty > 0 else None

    def buy(self, filled: float, price: float) -> None:
        self.qty += filled
        self.spent += filled * price

    def sell(self, filled: float) -> float | None:
        """Take *filled* shares out at the running average and return that average (None when
        nothing was held, so there is no cost to measure a sale against)."""
        avg = self.avg
        if avg is None:
            return None
        left = max(0.0, self.qty - filled)
        self.qty, self.spent = left, avg * left
        return avg
