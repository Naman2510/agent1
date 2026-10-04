"""Write the HTTP API's OpenAPI document to docs/openapi.json.

    python scripts/export_openapi.py

tests/unit/test_openapi_snapshot.py fails when the code and the committed document disagree, so a
change to the API shows up in review as a change to the contract, not only to the code. (The voice
socket is not HTTP and is not in it: docs/ARCHITECTURE.md §10.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app

OUT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def build_spec() -> dict[str, Any]:
    # Building the app connects to nothing, and any well-formed settings describe the same API.
    settings = Settings(
        database_url="postgresql+asyncpg://openapi:openapi@localhost:5432/openapi",
        redis_url="redis://localhost:6379/0",
        jwt_secret="x" * 32,
        _env_file=None,
    )
    return create_app(settings).openapi()


def render(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(build_spec()), encoding="utf-8")
    print(f"wrote {OUT}")
