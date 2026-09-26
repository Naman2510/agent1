"""The committed API contract, docs/openapi.json, matches the code.

docs/API.md promised this check in Phase 0 and nothing implemented it. By Phase 7 that document
listed endpoints that did not exist, missed ones that did, and described pagination the API never
had.

The comparison is of what a client depends on — operations, parameters, request and response
models, and each model's fields — not of the rendered JSON, which a FastAPI or pydantic release can
reformat without changing the API (CI installs the newest compatible versions).
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
EXPORT = BACKEND / "scripts" / "export_openapi.py"
COMMITTED = BACKEND.parent / "docs" / "openapi.json"


def _schema_ref(schema: dict[str, Any] | None) -> str | None:
    if not schema:
        return None
    return str(schema.get("$ref", schema.get("type", "inline")))


def contract(spec: dict[str, Any]) -> dict[str, Any]:
    operations: dict[str, Any] = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {})
            operations[f"{method.upper()} {path}"] = {
                "parameters": sorted(
                    (p["name"], p["in"], bool(p.get("required"))) for p in op.get("parameters", [])
                ),
                "body": _schema_ref(body.get("schema")),
                "responses": {
                    status: _schema_ref(
                        response.get("content", {}).get("application/json", {}).get("schema")
                    )
                    for status, response in op.get("responses", {}).items()
                },
            }
    schemas = {
        name: {
            "fields": sorted(schema.get("properties", {})),
            "required": sorted(schema.get("required", [])),
        }
        for name, schema in spec.get("components", {}).get("schemas", {}).items()
    }
    return {"operations": operations, "schemas": schemas}


def test_the_committed_openapi_document_matches_the_code() -> None:
    export = runpy.run_path(str(EXPORT))
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert contract(committed) == contract(export["build_spec"]()), (
        "the HTTP API changed: run `python scripts/export_openapi.py` and commit docs/openapi.json"
    )


def test_the_contract_notices_a_changed_field() -> None:
    """The projection is not so loose that it misses what matters."""
    spec = json.loads(COMMITTED.read_text(encoding="utf-8"))
    changed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    changed["components"]["schemas"]["SessionResponse"]["properties"].pop("turn_count")
    assert contract(changed) != contract(spec)
