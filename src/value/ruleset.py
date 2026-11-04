"""The ruleset fingerprint (spec §6.8): ``value_rules`` version plus a hash of the rule keys.

Every scorecard, ticker-file row and (later) shadow row carries both, so a verdict can always be
traced to the exact thresholds that produced it.
"""

from __future__ import annotations

from src.common.config import ValueCfg, ValueRulesCfg
from src.common.value_freshness import rules_digest

# value_rules v1, frozen 2026-10-29 by the operator after the calibration dry run (Part 1,
# Task 16). A rule change is a new version with a written reason, at most quarterly (spec §6.8).
# v2 (Part 2): v1's entry rules unchanged, plus `rules.exits` (spec §7), frozen before the shadow
# ledger's first row so every shadow entry carries the exit rules it was simulated under.
# v3 (Part 3): v2 unchanged, plus `rules.reevaluation` (spec §7.1), frozen before the first
# re-evaluation; it also versions Part 3's exit-engine code (shock stops, the 8-K and
# going-concern thesis exits, review minors M1 M5 M6 M14), which the hash cannot see.
# v4 (Part 4): v3 unchanged, plus `rules.claude` (spec §8.2 driver bounds and the 1.5x clamp,
# §8.4 kill-trigger ranges, trigger 6's nearness), frozen before Claude's first read.
FROZEN: dict[str, str] = {
    "v1": "e1a1b3b096b1",
    "v2": "d07717fe5348",
    "v3": "ad8841127029",
    "v4": "be30d1eaa915",
}


def ruleset_hash(rules: ValueRulesCfg) -> str:
    """12 hex characters of sha256 over the canonical JSON of every rule key."""
    return rules_digest(rules.model_dump(mode="json"))


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
