"""Skill registry — load/save/promote/reject the markdown playbooks and render the active set.

Layout (under the project root, version-controlled so promotions are auditable in git):

    config/skills/
        active/     promoted skills — injected into prompts
        proposed/   Claude-drafted skills awaiting human review
        rejected/   declined drafts, kept for provenance

Each skill is a `<name>.md` file: YAML frontmatter (`name`, `description`, and on drafts the
`rationale` + `supporting_stats` provenance) followed by the markdown body that gets injected.
Promotion/rejection is a file move — deliberately a human-gated git diff, never automatic.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from src.common.config import ROOT
from src.common.schemas import SkillProposal

log = logging.getLogger(__name__)

SKILLS_DIR = ROOT / "config" / "skills"
ACTIVE_DIR = SKILLS_DIR / "active"
PROPOSED_DIR = SKILLS_DIR / "proposed"
REJECTED_DIR = SKILLS_DIR / "rejected"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "skill"


def _ensure_dirs() -> None:
    for d in (ACTIVE_DIR, PROPOSED_DIR, REJECTED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _serialize(p: SkillProposal) -> str:
    front: dict = {"name": p.name, "description": p.description}
    if p.rationale:
        front["rationale"] = p.rationale
    if p.supporting_stats:
        front["supporting_stats"] = p.supporting_stats
    fm = yaml.safe_dump(front, sort_keys=False, default_flow_style=False).strip()
    return f"---\n{fm}\n---\n\n{p.body.strip()}\n"


def _parse(path: Path) -> SkillProposal | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        log.warning("skills: could not read %s", path)
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        log.warning("skills: %s has no frontmatter — skipping", path.name)
        return None
    try:
        front = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        log.warning("skills: %s has invalid frontmatter YAML — skipping", path.name)
        return None
    body = m.group(2).strip()
    name = str(front.get("name") or path.stem)
    description = str(front.get("description") or "")
    if not body:
        log.warning("skills: %s has empty body — skipping", path.name)
        return None
    return SkillProposal(
        name=name,
        description=description,
        body=body,
        rationale=str(front.get("rationale") or ""),
        supporting_stats=front.get("supporting_stats") or {},
    )


def _load_dir(directory: Path) -> list[SkillProposal]:
    if not directory.exists():
        return []
    out: list[SkillProposal] = []
    for path in sorted(directory.glob("*.md")):
        parsed = _parse(path)
        if parsed is not None:
            out.append(parsed)
    return out


def load_active_skills() -> list[SkillProposal]:
    """Promoted skills, sorted by filename. Returns [] if none or the dir is missing."""
    return _load_dir(ACTIVE_DIR)


def list_proposed() -> list[SkillProposal]:
    return _load_dir(PROPOSED_DIR)


def render_active_skills() -> str:
    """The prompt block injected into the strategist/roll prompts. Empty string if no skills.

    This is the ONLY way a skill reaches Claude. It is imported only by the prompt builders —
    never by the engine — which is what keeps the fence enforceable.
    """
    skills = load_active_skills()
    if not skills:
        return ""
    lines = [
        "=== ACTIVE REASONING SKILLS (human-promoted; shape verdict + ranking only) ===",
        "Apply these learned playbooks when forming your recommendation and priority. They do "
        "NOT change the deterministic risk gates — a candidate is already risk-approved.",
        "",
    ]
    for s in skills:
        lines.append(f"## {s.name} — {s.description}")
        lines.append(s.body.strip())
        lines.append("")
    return "\n".join(lines).strip()


def save_proposal(proposal: SkillProposal) -> Path:
    """Write a draft to proposed/. Returns the path. Overwrites a same-named draft."""
    _ensure_dirs()
    proposal.name = _slugify(proposal.name)
    path = PROPOSED_DIR / f"{proposal.name}.md"
    path.write_text(_serialize(proposal), encoding="utf-8")
    log.info("skills: saved proposal %s", path.name)
    return path


def promote(name: str) -> bool:
    """Move a proposed skill into active/. Returns True on success.

    Human-gated: this is invoked by a person via the skills CLI, never by the pipeline.
    """
    name = _slugify(name)
    src = PROPOSED_DIR / f"{name}.md"
    if not src.exists():
        log.warning("skills: cannot promote %s — not found in proposed/", name)
        return False
    _ensure_dirs()
    src.replace(ACTIVE_DIR / f"{name}.md")
    log.info("skills: promoted %s → active/", name)
    return True


def reject(name: str) -> bool:
    """Move a proposed skill into rejected/ (kept for provenance). Returns True on success."""
    name = _slugify(name)
    src = PROPOSED_DIR / f"{name}.md"
    if not src.exists():
        log.warning("skills: cannot reject %s — not found in proposed/", name)
        return False
    _ensure_dirs()
    src.replace(REJECTED_DIR / f"{name}.md")
    log.info("skills: rejected %s → rejected/", name)
    return True


def retire(name: str) -> bool:
    """Move an active skill back to proposed/ (stop injecting it without deleting it)."""
    name = _slugify(name)
    src = ACTIVE_DIR / f"{name}.md"
    if not src.exists():
        log.warning("skills: cannot retire %s — not found in active/", name)
        return False
    _ensure_dirs()
    src.replace(PROPOSED_DIR / f"{name}.md")
    log.info("skills: retired %s → proposed/", name)
    return True
