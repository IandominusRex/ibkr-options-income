"""M3 (whole-branch review fix): the two reason-label dictionaries must not drift.

`src.notify.formatters._REJECT_REASON_LABELS` (Telegram) and
`src.api.routers.options._REASON_LABELS` (web) carry the same mapping twice, on purpose: the
formatters module is Telegram-coupled (MarkdownV2 escaping, chat-length constraints) and the
web layer must not import it. Duplication that nothing checks is duplication that rots — the
`dedupe_pre_gate` label had to be added to both by hand in `dd07aa9`, and nothing would have
noticed if one had been missed. These tests are that check.
"""

from __future__ import annotations

from src.api.routers.options import _REASON_LABELS, _humanize_reason
from src.notify.formatters import _REJECT_REASON_LABELS, _humanize_reject_reason


def test_both_dictionaries_hold_exactly_the_same_codes() -> None:
    telegram_only = set(_REJECT_REASON_LABELS) - set(_REASON_LABELS)
    web_only = set(_REASON_LABELS) - set(_REJECT_REASON_LABELS)
    assert not telegram_only, f"only in src/notify/formatters.py: {sorted(telegram_only)}"
    assert not web_only, f"only in src/api/routers/options.py: {sorted(web_only)}"


def test_every_shared_code_maps_to_the_identical_phrase() -> None:
    differing = {
        code: (_REJECT_REASON_LABELS[code], _REASON_LABELS[code])
        for code in _REJECT_REASON_LABELS
        if _REJECT_REASON_LABELS[code] != _REASON_LABELS.get(code)
    }
    assert not differing, f"same code, different wording: {differing}"


def test_both_humanizers_agree_on_every_code_and_on_the_fallback() -> None:
    """Guards the accessors, not just the raw dicts — a lookup could still diverge."""
    for code in _REJECT_REASON_LABELS:
        assert _humanize_reject_reason(code) == _humanize_reason(code), code
    # Unknown codes de-snake-case identically in both, never to an empty string.
    assert _humanize_reject_reason("some_new_gate") == _humanize_reason("some_new_gate")
    assert _humanize_reason("some_new_gate") == "some new gate"


def test_the_dedupe_pre_gate_label_is_present_in_both() -> None:
    """The code this branch introduced — the reason the drift guard exists."""
    expected = "a better strike on this name already claimed the shared risk budget"
    assert _REJECT_REASON_LABELS["dedupe_pre_gate"] == expected
    assert _REASON_LABELS["dedupe_pre_gate"] == expected
