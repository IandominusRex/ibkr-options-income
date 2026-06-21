"""Active trading profile — overlays a named YAML profile onto the base risk/weights config.

Usage:
    from src.common.profile import get_effective_risk, get_effective_weights, activate, active

    # At scan start, sync the in-process profile from the DB setting:
    from src.storage.system_settings import get_active_profile
    activate(get_active_profile())

    # Then anywhere in the engine/strategies:
    risk = get_effective_risk()
    weights = get_effective_weights()

The profile name is stored in system_settings (DB) so it persists across restarts and
survives across processes.  ``activate()`` must be called at the top of each scan to pull
the DB value into the in-process state used by ``get_effective_risk/weights``.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import yaml

log = logging.getLogger(__name__)

VALID_PROFILES: frozenset[str] = frozenset({"default", "conservative", "balanced", "aggressive"})

_active: str = "default"


def activate(name: str) -> None:
    """Set the active profile for this process. Call at scan start."""
    global _active
    if name not in VALID_PROFILES:
        log.warning("Unknown profile %r — falling back to default", name)
        name = "default"
    _active = name


def active() -> str:
    """Return the currently active profile name."""
    return _active


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into a deep copy of *base*."""
    result: dict = copy.deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _load_overlay(name: str) -> dict[str, Any]:
    from src.common.config import CONFIG_DIR  # lazy import avoids circular dependency

    path = CONFIG_DIR / "profiles" / f"{name}.yaml"
    if not path.exists():
        log.warning("Profile %r not found at %s — no overlay applied", name, path)
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_effective_risk() -> dict[str, Any]:
    """Return risk_limits merged with the active profile's risk overrides."""
    from src.common.config import get_config  # lazy import

    base = get_config().risk
    if _active in ("default", ""):
        return base
    overlay = _load_overlay(_active)
    risk_overlay = overlay.get("risk", {})
    if not risk_overlay:
        return base
    return _deep_merge(base, risk_overlay)


def get_effective_weights() -> dict[str, Any]:
    """Return scoring_weights merged with the active profile's weights overrides."""
    from src.common.config import get_config  # lazy import

    base = get_config().weights
    if _active in ("default", ""):
        return base
    overlay = _load_overlay(_active)
    weights_overlay = overlay.get("weights", {})
    if not weights_overlay:
        return base
    return _deep_merge(base, weights_overlay)
