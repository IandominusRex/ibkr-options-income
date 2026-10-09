# tests/test_news_grounding.py
from __future__ import annotations

from src.news import grounding as G
from src.news.schemas import DigestRead, DigestReads, Explanation, FactSheet


def _facts() -> FactSheet:
    s = FactSheet()
    s.add("Move today", -6.2, "-6.2%")
    s.add("RSI14", 27.0, "RSI 27")
    s.add("Position NVDA 165P", 3.1, "165P 14 DTE · 3.1% OTM = 0.9 exp. moves")
    return s


def test_extract_numbers_marks_what_must_ground() -> None:
    nums = {
        v: must
        for v, _d, must in G.extract_numbers(
            "fell 6.2% in its 2nd drop, 3 sources, $165, 14 DTE, 12bp"
        )
    }
    assert nums[6.2] and nums[165.0] and nums[14.0] and nums[12.0]
    assert nums[2.0] is False and nums[3.0] is False


def test_grounded_tolerances_and_sign() -> None:
    refs = _facts().numbers()
    assert G.grounded(6.2, 1, refs, 0.02)
    assert G.grounded(0.9, 1, refs, 0.02)
    assert not G.grounded(8.4, 1, refs, 0.02)


def test_ground_strips_sentences_and_fixes_evidence() -> None:
    e = Explanation(
        headline="NVDA slides",
        what_happened="NVDA fell 8.4% on curbs.",
        read="A 6.2% drop at RSI 27 looks stretched. Analysts see 40% downside.",
        bull="b",
        bear="c",
        verdict="overreaction_likely",
        confidence="medium",
        book_impact="165P is 3.1% OTM.",
        evidence=["F1", "F99", "N7"],
    )
    out, trimmed = G.ground(
        e,
        facts=_facts(),
        news_numbers=[],
        news_ids={"N1"},
        rel_tol=0.02,
        fallback_what="Move today: -6.2%",
    )
    assert trimmed
    assert out.what_happened == "Move today: -6.2%"
    assert out.read == "A 6.2% drop at RSI 27 looks stretched."
    assert out.evidence == ["F1"] and out.verdict == "overreaction_likely"


def test_no_valid_evidence_downgrades_verdict() -> None:
    e = Explanation(
        headline="h",
        what_happened="w",
        read="r",
        bull="b",
        bear="c",
        verdict="further_downside_likely",
        confidence="high",
        evidence=["F42"],
    )
    out, _ = G.ground(
        e, facts=_facts(), news_numbers=[], news_ids=set(), rel_tol=0.02, fallback_what=None
    )
    assert out.verdict == "unclear" and out.confidence == "low"


def test_ground_digest_drops_bad_items() -> None:
    r = DigestReads(
        items=[
            DigestRead(
                cluster_id=1,
                headline="Fed",
                read="Yields up 9bp.",
                verdict="priced_in",
                evidence=["N1"],
            ),
            DigestRead(
                cluster_id=2, headline="Oil", read="Crude +14%.", verdict="unclear", evidence=[]
            ),
        ]
    )
    out = G.ground_digest(r, refs=[9.0], valid_ids={"N1"}, rel_tol=0.02)
    assert out.items[0].read == "Yields up 9bp." and out.items[1].read == ""


def test_headline_numbers_ground_and_unit_prefix_dollar() -> None:
    e = Explanation(
        headline="h",
        what_happened="Deal valued at $12B.",
        read="r",
        bull="b",
        bear="c",
        verdict="priced_in",
        confidence="low",
        evidence=["N1"],
    )
    out, trimmed = G.ground(
        e, facts=FactSheet(), news_numbers=[12.0], news_ids={"N1"}, rel_tol=0.02, fallback_what=None
    )
    assert (
        not trimmed and out.what_happened == "Deal valued at $12B." and out.verdict == "priced_in"
    )


def test_ground_digest_never_falls_back_to_the_ungrounded_llm_headline() -> None:
    """Final review: a digest headline stripped for an invented number fell back to the same
    LLM headline (`head or it.headline[:80]`), so the invented number was posted anyway."""
    r = DigestReads(
        items=[
            DigestRead(cluster_id=1, headline="Oil +14%", read="", verdict="unclear", evidence=[])
        ]
    )
    out = G.ground_digest(r, refs=[9.0], valid_ids=set(), rel_tol=0.02)
    assert "14" not in out.items[0].headline
