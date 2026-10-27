"""split_message: long Telegram text is cut at boundaries and every chunk parses on its own."""

from __future__ import annotations

from src.notify.splitting import LIMIT, MAX_CHUNKS, _units, open_entities, split_message


def _lines(n: int, width: int = 60) -> str:
    return "\n".join(f"line {i:03d} " + "x" * width for i in range(n))


def test_short_text_is_returned_untouched() -> None:
    assert split_message("hello *world*") == ["hello *world*"]


def test_every_chunk_fits_and_no_line_is_lost() -> None:
    text = _lines(200)  # ~14k characters
    chunks = split_message(text, markdown=False)
    assert len(chunks) > 1
    assert all(_units(c) <= LIMIT for c in chunks)
    got = [line for c in chunks for line in c.split("\n") if line]
    assert got == [line for line in text.split("\n") if line]  # in order, none cut mid-line


def test_cut_prefers_a_blank_line() -> None:
    para = "\n".join("p" * 50 for _ in range(30))  # ~1.5k characters
    text = "\n\n".join([para] * 5)
    chunks = split_message(text, limit=3300, markdown=False)
    assert all(c.count("\n\n") == 0 or not c.endswith("\n") for c in chunks)
    assert all(not c.startswith("\n") for c in chunks)
    assert chunks[0].endswith("p" * 50)  # ended on a paragraph, not mid-line


def test_an_entity_open_at_a_cut_is_closed_and_reopened() -> None:
    body = "\n".join(f"row {i} " + "y" * 70 for i in range(120))
    text = f"*{body}*"  # one bold run across the whole message
    chunks = split_message(text)
    assert len(chunks) > 1
    for c in chunks:
        assert open_entities(c) == [], c[:30]  # each chunk is balanced on its own
        assert c.startswith("*") and c.endswith("*")


def test_escaped_markers_are_not_entities() -> None:
    text = "\\*not bold\\* and \\_not italic\\_ " + "z" * 10
    assert open_entities(text) == []


def test_a_cut_never_strands_a_backslash() -> None:
    text = "\\.".join(["ab"] * 3000)  # an escaped dot every third character
    chunks = split_message(text)
    assert len(chunks) > 1
    for c in chunks:
        assert (len(c) - len(c.rstrip("\\"))) % 2 == 0


def test_code_span_contents_are_not_scanned_for_markers() -> None:
    assert open_entities("`a * b _ c`") == []
    assert open_entities("`unterminated *") == ["`"]


def test_emoji_count_as_two_units() -> None:
    text = "\n".join("🔍" * 40 for _ in range(150))  # 6000 characters, 12000 units
    chunks = split_message(text, markdown=False)
    assert all(_units(c) <= LIMIT for c in chunks)


def test_absurd_length_is_capped_with_an_ellipsis() -> None:
    chunks = split_message(_lines(3000), markdown=False)
    assert len(chunks) == MAX_CHUNKS
    assert chunks[-1].endswith("…")
