"""A generated artifact that drifts is worse than no artifact: the frontend reads it."""

from __future__ import annotations

import json
from pathlib import Path

from src.api.main import create_app

REGEN = (
    'python -c "import json; from src.api.main import create_app; '
    'print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json'
    "  &&  cd web && npm run gen:api"
)


def test_the_checked_in_openapi_matches_the_live_app() -> None:
    live = create_app().openapi()
    disk = json.loads(Path("docs/web/openapi.json").read_text())
    assert live == disk, f"docs/web/openapi.json is stale. Regenerate:\n  {REGEN}"
