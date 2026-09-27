"""What produced a number, kept with the number (EVALUATION.md §1).

A result is `(suite, dataset, config, code)`. A run records all four — the dataset by version and
by a digest of its files' content, the config as the full set of knobs it ran with, the code by
git SHA and whether the working tree was dirty — so it can be run again from its record alone
(`python -m eval.runner --reproduce RUN_ID`).

Recording goes to PostgreSQL (`evaluation_runs`, `evaluation_results`, `experiments`) and, when
MLflow is installed, to an MLflow tracking store as well. PostgreSQL is the system of record:
the admin dashboard and `--reproduce` read it. MLflow is for browsing and comparing runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS = REPO_ROOT / "datasets"
CONFIGS = Path(__file__).resolve().parent / "configs"
BASELINES = Path(__file__).resolve().parent / "baselines"


@dataclass(frozen=True)
class CaseRecord:
    """One case's outcome, as the failure browser shows it (EVALUATION.md §8)."""

    case_id: str
    passed: bool | None
    language: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None


@dataclass
class SuiteOutcome:
    summary: dict[str, Any]
    cases: list[CaseRecord]
    report: str
    ok: bool


@dataclass(frozen=True)
class RunSpec:
    """Everything a run's result depends on."""

    suite: str
    config_name: str
    config: dict[str, Any]
    dataset_version: str
    dataset_digest: str
    git_sha: str
    git_dirty: bool


# --- provenance -------------------------------------------------------------


def git_state(repo: Path = REPO_ROOT) -> tuple[str, bool]:
    """The commit, and whether the working tree differs from it. A run from a dirty tree is
    recorded as such: its SHA alone does not say what code produced it."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not tied to a commit means not reproducible; saying so beats a number that looks
        # authoritative.
        return "unknown", True
    return sha, bool(status.strip())


def dataset_digest(files: Iterable[Path], *, root: Path = DATASETS) -> str:
    """SHA-256 over each file's path relative to `root` and its bytes, in path order. A version
    label says which dataset was meant; the digest says which bytes were actually read."""
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def files_under(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.is_file())


# --- configs ----------------------------------------------------------------


class ConfigError(ValueError):
    pass


class SuiteUnavailableError(ConfigError):
    """The suite cannot run here: a package or model it needs is not available. Said plainly,
    with what it needs, rather than as a traceback from deep inside a download."""


def load_config(path: Path) -> tuple[str, dict[str, Any]]:
    """A run config: a TOML file naming its suite, with every knob the suite reads.

    The name is the file's stem. What the suite does not read does not belong here, and what it
    reads must be here: a knob left to a default in code cannot be seen in the record.
    """
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config.get("suite"), str):
        raise ConfigError(f"{path}: a config must name its suite")
    return path.stem, config


def default_config_path(suite: str) -> Path:
    return CONFIGS / f"{suite}.toml"


def leaf_paths(tree: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """`{"a": {"b": 1}}` -> `{"a.b": 1}`. Lists are leaves."""
    leaves: dict[str, Any] = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping):
            leaves.update(leaf_paths(value, f"{path}."))
        else:
            leaves[path] = value
    return leaves


def config_diff(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    """The knobs two configs set differently — added, removed or changed."""
    a, b = leaf_paths(baseline), leaf_paths(candidate)
    return sorted(
        key for key in a.keys() | b.keys() if a.get(key, _MISSING) != b.get(key, _MISSING)
    )


_MISSING = object()


# --- baselines ----------------------------------------------------------------
#
# A recorded run lives in this machine's database; a baseline is its summary committed to the
# repository, with its provenance, so any machine — CI on every push — can run the same config
# over the same data and demand the same numbers.


def baseline_path(config_name: str) -> Path:
    return BASELINES / f"{config_name}.json"


def write_baseline(spec: RunSpec, outcome: SuiteOutcome, run_id: uuid.UUID | None) -> Path:
    path = baseline_path(spec.config_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "config_name": spec.config_name,
        "config": spec.config,
        "suite": spec.suite,
        "dataset_version": spec.dataset_version,
        "dataset_digest": spec.dataset_digest,
        "git_sha": spec.git_sha,
        "git_dirty": spec.git_dirty,
        "evaluation_run_id": str(run_id) if run_id is not None else None,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": outcome.summary,
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def check_baseline(spec: RunSpec, outcome: SuiteOutcome) -> tuple[int, list[str]]:
    """0 when the run reproduces its committed baseline; 1 when a metric differs; 2 when the
    comparison is not meaningful — no baseline, or the config or data changed since."""
    path = baseline_path(spec.config_name)
    if not path.exists():
        return 2, [f"no baseline for {spec.config_name} ({path})"]
    baseline = json.loads(path.read_text(encoding="utf-8"))
    if baseline["config"] != spec.config:
        return 2, [f"{spec.config_name}: the config changed since its baseline was recorded"]
    if baseline["dataset_digest"] != spec.dataset_digest:
        return 2, [f"{spec.config_name}: dataset {spec.dataset_version} changed since its baseline"]
    before, after = leaf_paths(baseline["summary"]), leaf_paths(outcome.summary)
    differences = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if differences:
        return 1, [
            f"{spec.config_name}: {key} was {json.dumps(before.get(key))} at "
            f"{baseline['git_sha']}, is {json.dumps(after.get(key))} now"
            for key in differences
        ]
    return 0, [
        f"{spec.config_name}: every metric matches the baseline recorded at {baseline['git_sha']}"
    ]


# --- MLflow -----------------------------------------------------------------

_METRIC_NAME = re.compile(r"[^A-Za-z0-9_\-./ ]")


def metric_name(path: str) -> str:
    """MLflow accepts letters, digits, `_ - . / `; `recall@5` becomes `recall_at_5`."""
    return _METRIC_NAME.sub("_", path.replace("@", "_at_"))


def numeric_metrics(summary: Mapping[str, Any]) -> dict[str, float]:
    return {
        metric_name(path): float(value)
        for path, value in leaf_paths(summary).items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }


def log_to_mlflow(spec: RunSpec, outcome: SuiteOutcome, *, run_id: uuid.UUID | None) -> str:
    """Log a finished run to MLflow; returns its MLflow run id.

    The tracking store is `MLFLOW_TRACKING_URI`, or SQLite at `mlflow.db` in the repository root
    (MLflow 3 retired its plain-file store); artifacts go to `MLFLOW_ARTIFACT_ROOT`, or
    `mlartifacts/`. Raises ImportError when MLflow is not installed: the caller says so rather than
    skipping quietly.
    """
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow

    mlflow.set_tracking_uri(
        os.environ.get("MLFLOW_TRACKING_URI", f"sqlite:///{REPO_ROOT / 'mlflow.db'}")
    )
    name = f"vaanios-{spec.suite}"
    if mlflow.get_experiment_by_name(name) is None:
        mlflow.create_experiment(
            name,
            artifact_location=os.environ.get(
                "MLFLOW_ARTIFACT_ROOT", (REPO_ROOT / "mlartifacts").as_uri()
            ),
        )
    mlflow.set_experiment(name)
    with mlflow.start_run(run_name=f"{spec.config_name}@{spec.git_sha}") as active:
        mlflow.log_params(
            {
                "suite": spec.suite,
                "config_name": spec.config_name,
                "dataset_version": spec.dataset_version,
                "dataset_digest": spec.dataset_digest,
                "git_sha": spec.git_sha,
                "git_dirty": spec.git_dirty,
                **{f"config.{k}": json.dumps(v) for k, v in leaf_paths(spec.config).items()},
            }
        )
        mlflow.log_metrics(numeric_metrics(outcome.summary))
        if run_id is not None:
            mlflow.set_tag("evaluation_run_id", str(run_id))
        mlflow.log_dict(
            {"summary": outcome.summary, "cases": [asdict(case) for case in outcome.cases]},
            "outcome.json",
        )
        return str(active.info.run_id)


# --- PostgreSQL -------------------------------------------------------------


class RunStore:
    """Evaluation runs and experiments in PostgreSQL, through the application's own models."""

    def __init__(self, settings: Settings) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.session import create_engine

        self._engine = create_engine(settings)
        self._factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self) -> None:
        await self._engine.dispose()

    async def start(
        self, spec: RunSpec, *, reproduces: uuid.UUID | None = None, notes: str | None = None
    ) -> uuid.UUID:
        from app.db.models import EvalStatus, EvaluationRun

        async with self._factory() as session:
            run = EvaluationRun(
                suite=spec.suite,
                config_name=spec.config_name,
                config=spec.config,
                dataset_version=spec.dataset_version,
                dataset_digest=spec.dataset_digest,
                git_sha=spec.git_sha,
                git_dirty=spec.git_dirty,
                status=EvalStatus.RUNNING,
                reproduces_run_id=reproduces,
                notes=notes,
            )
            session.add(run)
            await session.commit()
            return run.id

    async def finish(
        self, run_id: uuid.UUID, outcome: SuiteOutcome, *, mlflow_run_id: str | None
    ) -> None:
        from app.db.models import EvalStatus, EvaluationResult, EvaluationRun

        async with self._factory() as session:
            run = await session.get(EvaluationRun, run_id)
            if run is None:
                raise LookupError(f"no evaluation run {run_id}")
            run.status = EvalStatus.COMPLETED
            run.summary_metrics = outcome.summary
            run.case_count = len(outcome.cases)
            run.mlflow_run_id = mlflow_run_id
            run.finished_at = datetime.now(UTC)
            session.add_all(
                EvaluationResult(
                    run_id=run_id,
                    case_id=case.case_id,
                    language=case.language,
                    input=case.input,
                    expected=case.expected,
                    actual=case.actual,
                    metrics=case.metrics,
                    passed=case.passed,
                    notes=case.notes,
                )
                for case in outcome.cases
            )
            await session.commit()

    async def fail(self, run_id: uuid.UUID, error: str) -> None:
        from app.db.models import EvalStatus, EvaluationRun

        async with self._factory() as session:
            run = await session.get(EvaluationRun, run_id)
            if run is not None:
                run.status = EvalStatus.FAILED
                run.finished_at = datetime.now(UTC)
                run.notes = f"{run.notes + chr(10) if run.notes else ''}failed: {error}"
                await session.commit()

    async def load(self, run_id: uuid.UUID) -> tuple[RunSpec, dict[str, Any]]:
        """A recorded run's spec and its summary metrics."""
        from app.db.models import EvalStatus, EvaluationRun

        async with self._factory() as session:
            run = await session.get(EvaluationRun, run_id)
            if run is None:
                raise LookupError(f"no evaluation run {run_id}")
            if run.status is not EvalStatus.COMPLETED:
                raise LookupError(f"run {run_id} did not complete ({run.status})")
            spec = RunSpec(
                suite=run.suite,
                config_name=run.config_name,
                config=run.config,
                dataset_version=run.dataset_version,
                dataset_digest=run.dataset_digest,
                git_sha=run.git_sha,
                git_dirty=run.git_dirty,
            )
            return spec, run.summary_metrics

    async def record_experiment(
        self,
        *,
        slug: str,
        title: str,
        hypothesis: str,
        suite: str,
        variable_changed: str,
        decision_rule: dict[str, Any],
        baseline_run_id: uuid.UUID,
        candidate_run_id: uuid.UUID,
        comparison: dict[str, Any],
        decision: str,
        rationale: str,
    ) -> uuid.UUID:
        """Insert or replace an experiment's record: re-running an experiment re-decides it."""
        from sqlalchemy import select

        from app.db.models import Experiment, ExperimentDecision

        async with self._factory() as session:
            existing = await session.execute(select(Experiment).where(Experiment.slug == slug))
            experiment = existing.scalar_one_or_none()
            if experiment is None:
                experiment = Experiment(slug=slug)
                session.add(experiment)
            experiment.title = title
            experiment.hypothesis = hypothesis
            experiment.suite = suite
            experiment.variable_changed = variable_changed
            experiment.decision_rule = decision_rule
            experiment.baseline_run_id = baseline_run_id
            experiment.candidate_run_id = candidate_run_id
            experiment.comparison = comparison
            experiment.decision = ExperimentDecision(decision)
            experiment.rationale = rationale
            experiment.decided_at = datetime.now(UTC)
            await session.commit()
            return experiment.id
