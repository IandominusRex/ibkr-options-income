"""Multi-week stories whose survival Python decides (spec section 8).

The picture tracks up to a handful of stories (a tariff fight, a rates repricing). Left to the
model, a story could be kept alive forever by finding something loosely related each rebuild, and
its own earlier prose would harden into fact. So both are taken away from it:

* a story is **alive** only while enough clusters that Python matched to it (ticker, topic and
  tag overlap, Jaccard) were seen inside the window, or while it is younger than the window;
* its identity (id, title, start date) is stored here; its **description is never stored**, so it
  can never be fed back into a prompt.

Pure functions: the loop in ``picture.py`` loads the rows and clusters and saves what these return.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.news.schemas import ClusterView
from src.news.store.models import PictureStoryRow

ET = ZoneInfo("America/New_York")

# The four style tags the tagger puts on a cluster (scheduled, rumor, quantified, forward_looking)
# say how a headline is written, not what it is about. Any number of unrelated clusters carry
# "quantified", so counting it would let a stranger keep a story alive.
_STYLE_TAGS = frozenset({"scheduled", "rumor", "quantified", "forward_looking"})


def cluster_signature(c: ClusterView) -> set[str]:
    """What a cluster is about: its tickers, its topic tags and its topic class. Never its title
    words (ruling 21). An unclassified topic ("other") names nothing, so it is left out."""
    sig = {t.upper() for t in c.tickers} | {t for t in c.tags if t not in _STYLE_TAGS}
    if c.topic_class and c.topic_class != "other":
        sig.add(f"topic:{c.topic_class}")
    return sig


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def match_clusters(
    stories: list[PictureStoryRow], clusters: list[ClusterView], *, jaccard: float
) -> dict[int, list[int]]:
    """Attach each cluster no story holds yet to the story it overlaps most.

    *clusters* holds the candidates (pile 1 and 2 clusters seen lately) and the clusters the
    stories already hold; a story's signature is the union of its held clusters' signatures. A
    candidate attaches to the story with the highest Jaccard of at least *jaccard* (ties go to the
    older story); a story whose held clusters are all unknown has no signature and attracts
    nothing. Returns ``{story id: [newly attached cluster ids]}`` for the stories that gained any.
    """
    by_id = {c.id: c for c in clusters}
    held: set[int] = {cid for st in stories for cid in (st.cluster_ids or [])}
    signatures: dict[int, set[str]] = {}
    for st in stories:
        sig: set[str] = set()
        for cid in st.cluster_ids or []:
            if cid in by_id:
                sig |= cluster_signature(by_id[cid])
        signatures[st.id] = sig
    order = sorted(stories, key=lambda st: (st.started_on, st.id))
    out: dict[int, list[int]] = {}
    for c in sorted(clusters, key=lambda c: c.id):
        if c.id in held:
            continue
        mine = cluster_signature(c)
        best: PictureStoryRow | None = None
        best_score = 0.0
        for st in order:
            score = _jaccard(mine, signatures[st.id])
            if score > best_score:
                best, best_score = st, score
        if best is not None and best_score >= jaccard:
            out.setdefault(best.id, []).append(c.id)
    return out


def story_alive(
    story: PictureStoryRow,
    new_ids: list[int],
    *,
    now: datetime,
    window_days: int,
    min_new: int,
) -> bool:
    """A story is alive while it has *min_new* supporting clusters seen inside the window
    (*new_ids*: its clusters, old or newly attached, that the caller found inside it), or while it
    started within the window: a story needs time to gather support."""
    started: date = story.started_on
    if (now.astimezone(ET).date() - started).days <= window_days:
        return True
    return len(set(new_ids)) >= min_new
