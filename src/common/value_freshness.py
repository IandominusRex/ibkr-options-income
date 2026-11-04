"""The ticker file's freshness test, in one neutral place (value book Part 6, ruling 16).

Standard library only: the value process writes the key beside each file, and the API (which may
import nothing but ``src.value.scorecard`` and ``src.value.schemas`` from the value package)
reads it back on open, so both import this module and neither imports the other's code.
``src/value/ticker_file.py`` re-exports ``freshness_key`` and ``is_current`` unchanged.

A file is current when the key stored beside it equals the key of the cheap input parts now (the
newest accession and the newest bar in research.db), the regime and the ruleset. The scorecard's
own fingerprint is not compared with the cheap parts: the two latest-accession readings disagree
by design.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def freshness_key(parts: dict[str, Any], regime: str, version: str, digest: str) -> str:
    """A hash of the cheap input parts, the regime and the ruleset."""
    blob = json.dumps(
        {"parts": parts, "regime": regime, "version": version, "digest": digest},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def is_current(
    stored_freshness_json: str | None, parts: dict[str, Any], regime: str, version: str, digest: str
) -> bool:
    """A file is current when the key stored beside it equals the key of the current cheap parts.
    A file written before the column (None) or an unreadable one is stale: recomputed once."""
    if not stored_freshness_json:
        return False
    try:
        stored = json.loads(stored_freshness_json).get("key")
    except (ValueError, AttributeError):
        return False
    return bool(stored == freshness_key(parts, regime, version, digest))


def rules_digest(rules_dump: Mapping[str, Any]) -> str:
    """12 hex characters of sha256 over the canonical JSON of every rule key (the
    ``value_rules`` hash, spec §6.8): ``rules.model_dump(mode="json")`` in, the digest out.
    ``src/value/ruleset.py`` delegates here, so the two cannot drift."""
    canonical = json.dumps(rules_dump, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
