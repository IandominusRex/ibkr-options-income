"""Part 6 Task 11: plain words for the value book's reason codes on a wheel card.

Every ``release_*`` code and every value-book code the Rules Engine can return reads as a phrase
in both label maps (Telegram's and the web's), and the two maps agree on those codes. The codes
are found in the engine's source with ``ast``, so a code added there without a phrase fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.api.routers.options import _REASON_LABELS
from src.notify.formatters import _REJECT_REASON_LABELS

ROOT = Path(__file__).resolve().parents[1]
ENGINE_FILES = (ROOT / "src/engine/risk_engine.py", ROOT / "src/engine/capital.py")
# The Part 5 codes that can reach a wheel card besides release_* (ruling 21); above_value_ceiling
# is raised by the promote drain, not the engine.
VALUE_CODES = {
    "book_attribution_mismatch",
    "value_book_unreadable",
    "gross_notional_cap",
    "combined_name_cap",
    "reserved_for_spreads_book",
    "above_value_ceiling",
}


def _engine_literals() -> set[str]:
    out: set[str] = set()
    for path in ENGINE_FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value)
    return out


def _codes() -> set[str]:
    literals = _engine_literals()
    release = {c for c in literals if c.startswith("release_") and c.replace("_", "").isalpha()}
    return release | VALUE_CODES


def test_every_release_and_value_code_has_words_in_both_maps() -> None:
    literals = _engine_literals()
    codes = _codes()
    assert {"release_not_paper", "release_at_loss", "release_daily_cap"} <= codes
    # the engine still raises each value code it is supposed to (a rename must not hide here)
    assert (VALUE_CODES - {"above_value_ceiling"}) <= literals
    missing_telegram = sorted(c for c in codes if c not in _REJECT_REASON_LABELS)
    missing_web = sorted(c for c in codes if c not in _REASON_LABELS)
    assert missing_telegram == [] and missing_web == []
    for code in codes:
        assert _REJECT_REASON_LABELS[code].strip() and " " in _REJECT_REASON_LABELS[code]
        assert "_" not in _REJECT_REASON_LABELS[code]


def test_the_two_maps_agree_on_those_codes() -> None:
    for code in sorted(_codes()):
        assert _REJECT_REASON_LABELS[code] == _REASON_LABELS[code], code
