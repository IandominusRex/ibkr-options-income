"""Pure text helpers for dedupe and clustering. No I/O."""

from __future__ import annotations

import hashlib
import re
import string
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|cmpid|guccounter)$", re.I)
_PUNCT = str.maketrans({c: " " for c in string.punctuation if c not in "$%."})
_STOP = frozenset(
    "a an the and or of to in on for at by with from as is are be was were after before over "
    "amid into its it this that these those new says said report reports update live".split()
)


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), "")
    )


def normalize_title(title: str, source: str | None = None) -> str:
    t = title.strip()
    if source and t.lower().endswith(f" - {source.lower()}"):
        t = t[: -(len(source) + 3)]
    t = t.lower().translate(_PUNCT).replace("…", " ")
    return " ".join(t.split()).strip(" .")


def title_hash(title: str, source: str | None = None) -> str:
    return sha1(normalize_title(title, source))


def url_hash(url: str | None, title: str, source: str | None = None) -> str:
    if url:
        return sha1(canonical_url(url))
    return "t:" + title_hash(title, source)[:38]


def title_tokens(title: str) -> frozenset[str]:
    return frozenset(w for w in normalize_title(title).split() if len(w) >= 2 and w not in _STOP)


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host or None
