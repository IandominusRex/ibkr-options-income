"""The news fence (spec §10). Imports parsed with ast, reusing the spreads fence's resolver."""

from __future__ import annotations

from pathlib import Path

from tests.test_spreads_fence import imported_modules

ROOT = Path(__file__).resolve().parents[1]
NEWS = sorted((ROOT / "src" / "news").rglob("*.py"))
_ROW_CLASSES = (
    "NewsItemRow(",
    "NewsClusterRow(",
    "EconEventRow(",
    "EarningsEventRow(",
    "FeedStateRow(",
    "NewsPostRow(",
    "AlertStateRow(",
    "NewsRequestRow(",
    "NewsStateRow(",
    "TickerAliasRow(",
)


def _pkg_files(*parts: str) -> list[Path]:
    return sorted((ROOT.joinpath(*parts)).rglob("*.py"))


def test_trading_path_never_imports_news() -> None:
    for pkg in (("src", "engine"), ("src", "execution"), ("src", "strategies"), ("src", "spreads")):
        for path in _pkg_files(*pkg):
            bad = [
                m for m in imported_modules(path) if m == "src.news" or m.startswith("src.news.")
            ]
            assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_news_never_imports_the_trading_path() -> None:
    forbidden = (
        "src.engine",
        "src.execution",
        "src.strategies",
        "src.spreads",
        "src.orchestrator",
        "src.notify.approval_service",
    )
    for path in NEWS:
        bad = [
            m
            for m in imported_modules(path)
            if any(m == f or m.startswith(f + ".") for f in forbidden)
        ]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_only_src_news_constructs_news_rows() -> None:
    for path in (ROOT / "src").rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[:2] == ("src", "news"):
            continue
        # src/research/store/models.py has its own, unrelated NewsItemRow (research.db); a
        # writer of news.db outside src/news/ has to import the row class from src.news.
        if not any(m == "src.news" or m.startswith("src.news.") for m in imported_modules(path)):
            continue
        text = path.read_text(encoding="utf-8")
        for cls in _ROW_CLASSES:
            assert cls not in text, (
                f"{rel} constructs {cls[:-1]} — only src/news/ may write news.db"
            )


def test_notify_imports_only_the_brief_queue() -> None:
    for path in _pkg_files("src", "notify"):
        mods = [m for m in imported_modules(path) if m == "src.news" or m.startswith("src.news.")]
        bad = [m for m in mods if not (m == "src.news.briefs" or m.startswith("src.news.briefs."))]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_api_never_imports_the_rw_engine() -> None:
    for path in _pkg_files("src", "api"):
        bad = [m for m in imported_modules(path) if m.startswith("src.news.store.session")]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"
