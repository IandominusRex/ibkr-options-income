"""The ruleset fingerprint (spec §6.8): ``value_rules`` version plus a hash of the rule keys.

Every scorecard, ticker-file row and (later) shadow row carries both, so a verdict can always be
traced to the exact thresholds that produced it.
"""

from __future__ import annotations

import hashlib
import json

from src.common.config import ValueCfg, ValueRulesCfg

# value_rules v1, frozen 2026-10-29 by the operator after the calibration dry run (Part 1,
# Task 16). A rule change is a new version with a written reason, at most quarterly (spec §6.8).
# v2 (Part 2): v1's entry rules unchanged, plus `rules.exits` (spec §7), frozen before the shadow
# ledger's first row so every shadow entry carries the exit rules it was simulated under.
FROZEN: dict[str, str] = {"v1": "e1a1b3b096b1", "v2": "d07717fe5348"}


def ruleset_hash(rules: ValueRulesCfg) -> str:
    """12 hex characters of sha256 over the canonical JSON of every rule key."""
    canonical = json.dumps(rules.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def ruleset_id(cfg: ValueCfg) -> tuple[str, str]:
    """``(version, hash)``. A frozen version whose rules no longer hash to the pinned value
    raises, because a verdict would otherwise carry a version whose rules quietly changed."""
    digest = ruleset_hash(cfg.rules)
    pinned = FROZEN.get(cfg.ruleset_version)
    if pinned is not None and pinned != digest:
        raise ValueError(
            f"value ruleset {cfg.ruleset_version} is frozen at {pinned}, but config/value.yaml's "
            f"rules hash to {digest}: bump ruleset_version (spec §6.8)"
        )
    return cfg.ruleset_version, digest
