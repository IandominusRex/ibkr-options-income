"""The Claude calls and the prompt blocks each one carries (market picture spec section 11).

Static: it feeds the page's tiles and nothing else. A block is a label for the operator, the
header text the prompt builder emits for it, and the file that emits it.
``tests/test_api_claude_context.py::test_every_block_header_occurs_in_its_builder_file`` reads
each ``builder_file`` and requires its ``header`` to occur there, so a prompt builder that drops
or renames a block fails a test instead of leaving a tile that lies. Nothing here imports a
prompt builder: the API process must not load the enrichment layer.

The market-picture header is emitted by ``common/picture_text.py`` for every reader (each prompt
builder receives the rendered block), and the sector header by ``analytics/sector_context.py``.
"""

from __future__ import annotations

from typing import NamedTuple


class Block(NamedTuple):
    label: str  # what the operator reads on the chip
    header: str  # a substring of the header line the builder emits
    builder_file: str  # repo-relative path of the file that emits it


class Call(NamedTuple):
    kind: str
    label: str
    blocks: tuple[Block, ...]


_PICTURE = "src/common/picture_text.py"
_NOTES = "src/common/dossier_text.py"
_STRATEGIST = "src/claude/prompts/strategist.py"
_ROLL = "src/claude/prompts/roll.py"
_SPREADS = "src/spreads_ai/prompts.py"
_NEWS = "src/news/prompts.py"

CALLS: tuple[Call, ...] = (
    Call(
        "trade_review",
        "Trade review",
        (
            Block("Market picture", "MARKET PICTURE", _PICTURE),
            Block("Your book", "YOUR BOOK", "src/claude/book_context.py"),
            Block("Name notes", "NAME NOTES", _NOTES),
            Block("News", "=== NEWS", "src/claude/news_context.py"),
            Block("Candidates", "TRADE CANDIDATES", _STRATEGIST),
        ),
    ),
    Call(
        "roll_review",
        "Roll review",
        (
            Block("Market picture", "MARKET PICTURE", _PICTURE),
            Block("Name notes", "NAME NOTES", _NOTES),
            Block("Position", "POSITION", _ROLL),
            Block("Live quote", "LIVE QUOTE", _ROLL),
            Block("System proposal", "SYSTEM PROPOSAL", _ROLL),
        ),
    ),
    Call(
        "spreads_picker",
        "Spreads picker",
        (
            Block("Market picture (as of build)", "MARKET PICTURE", _PICTURE),
            Block("Tape", "TAPE (ET)", _SPREADS),
            Block("Events", "=== EVENTS", _SPREADS),
            Block("Headlines", "HEADLINES (untrusted", _SPREADS),
            Block("Menu", "=== MENU", _SPREADS),
        ),
    ),
    Call(
        "news_expert",
        "News expert",
        (
            Block("Facts", "=== FACTS", _NEWS),
            Block("Clusters", "=== CLUSTERS", _NEWS),
            Block("Market picture", "MARKET PICTURE", _PICTURE),
        ),
    ),
    Call(
        "eod_journal",
        "EOD journal",
        (
            Block("Market picture", "MARKET PICTURE", _PICTURE),
            Block("Today's trades", "TODAY'S TRADES", "src/claude/prompts/eod.py"),
        ),
    ),
    Call(
        "scan",
        "/scan",
        (
            Block("Market picture", "MARKET PICTURE", _PICTURE),
            Block("Name notes", "NAME NOTES", _NOTES),
            Block("Sector", "SECTOR & MARKET BACKDROP", "src/analytics/sector_context.py"),
            Block("News", "=== NEWS", "src/claude/news_context.py"),
            Block("Candidates", "TRADE CANDIDATES", _STRATEGIST),
        ),
    ),
    Call(
        "dossier_builder",
        "Dossier builder",
        (
            Block("Facts", "FACTS", _NEWS),
            Block("Clusters", "CLUSTERS", _NEWS),
            Block("Market picture", "MARKET PICTURE", _PICTURE),
        ),
    ),
)
