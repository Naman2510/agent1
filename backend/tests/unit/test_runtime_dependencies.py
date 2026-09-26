"""The production image installs only the base dependencies (infra/docker/backend.Dockerfile,
ADR-0015). Everything the running server imports must therefore be a base dependency.

It was not: RAG tokenising, the TF-IDF/SVD embedder, PDF ingestion and the Silero VAD imported
packages listed only in extras, so an image built exactly as documented could not start. Nothing
noticed, because every test environment installs the extras too. This test removes them.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

# Distribution name -> top-level import name, for every package that appears only in an extra.
# A new extra-only package must be added here, which is the point: it forces the question
# "does the server import this?".
IMPORT_NAMES = {
    "pytest": "pytest",
    "pytest-asyncio": "pytest_asyncio",
    "pytest-cov": "pytest_cov",
    "httpx": "httpx",
    "fakeredis": "fakeredis",
    "ruff": "ruff",
    "mypy": "mypy",
    "jiwer": "jiwer",
    "rank-bm25": "rank_bm25",
    "mlflow": "mlflow",
    "faster-whisper": "faster_whisper",
}

PROBE = """
import importlib.abc, sys
blocked = set(sys.argv[1].split(","))
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in blocked:
            raise ModuleNotFoundError(f"{name} is not a base dependency")
        return None
sys.meta_path.insert(0, Block())
import app.asgi
import app.voice.vad, numpy, onnxruntime  # what every voice connection loads
print("ok")
"""


def _name(requirement: str) -> str:
    for separator in ("[", ">", "<", "=", "!", "~", ";", " "):
        requirement = requirement.split(separator)[0]
    return requirement.strip().lower()


def test_the_server_starts_with_only_its_base_dependencies(tmp_path: Path) -> None:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]
    base = {_name(r) for r in project["dependencies"]}
    extras_only = {
        _name(r) for group in project["optional-dependencies"].values() for r in group
    } - base

    unmapped = extras_only - IMPORT_NAMES.keys()
    assert not unmapped, f"add these to IMPORT_NAMES: {sorted(unmapped)}"

    blocked = ",".join(sorted(IMPORT_NAMES[name] for name in extras_only))
    # An empty working directory, so a developer's backend/.env cannot supply settings that CI
    # lacks. Importing only builds the app; nothing connects, so the stores need not exist.
    result = subprocess.run(  # noqa: S603 - our own interpreter and a constant script
        [sys.executable, "-c", PROBE, blocked],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PATH": "",
            "PYTHONPATH": str(BACKEND),
            "VAANIOS_JWT_SECRET": "x" * 48,
            "VAANIOS_DATABASE_URL": "postgresql+asyncpg://probe:probe@127.0.0.1:1/probe",
            "VAANIOS_REDIS_URL": "redis://127.0.0.1:1/0",
        },
    )
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr[-2000:]
