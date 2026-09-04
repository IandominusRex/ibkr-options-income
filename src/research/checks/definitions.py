"""Load and validate the check catalogue."""

from __future__ import annotations

import functools
from enum import StrEnum

import yaml
from pydantic import BaseModel, field_validator

from src.common.config import CONFIG_DIR


class CheckOp(StrEnum):
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    BETWEEN = "between"
    TRUTHY = "truthy"


class CheckDef(BaseModel):
    id: str
    category: str
    fn: str
    op: CheckOp
    threshold: float | list[float] | None = None
    statement: str
    requires: list[str]
    applies_to: str = "all"

    @field_validator("threshold")
    @classmethod
    def _bounds(cls, v, info):
        if info.data.get("op") is CheckOp.BETWEEN:
            if not isinstance(v, list) or len(v) != 2:
                raise ValueError("op 'between' requires a [low, high] threshold")
        return v


@functools.lru_cache(maxsize=1)
def load_checks() -> list[CheckDef]:
    raw = yaml.safe_load((CONFIG_DIR / "research_checks.yaml").read_text(encoding="utf-8"))
    return [CheckDef(**c) for c in (raw or {}).get("checks", [])]


def checks_for(*, is_etf: bool) -> list[CheckDef]:
    """The catalogue applicable to one instrument type."""
    want = "etf" if is_etf else "stock"
    return [c for c in load_checks() if c.applies_to in ("all", want)]
