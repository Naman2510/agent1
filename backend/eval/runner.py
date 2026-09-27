"""Evaluation entrypoint: every suite, one command (EVALUATION.md §2).

    python -m eval.runner --suite lid                          # the suite's default config
    python -m eval.runner --config eval/configs/retrieval*.toml --record
    python -m eval.runner --reproduce RUN_ID
    python -m eval.runner --experiment eval/experiments/EXP-008.toml --record

A run is `(suite, dataset, config, code)` (eval/recording.py). `--record` keeps it: a row in
`evaluation_runs` with a row per case, and an MLflow run when MLflow is installed. `--reproduce`
runs a recorded run again from its record alone and fails unless the metrics come out identical.
`--experiment` runs a registered experiment's baseline and candidate — configs that must differ in
exactly one knob — and decides it by the rule registered with it (eval/decision.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eval.decision import DecisionRule, decide
from eval.harness import SUITES
from eval.recording import (
    CONFIGS,
    DATASETS,
    ConfigError,
    RunSpec,
    RunStore,
    SuiteOutcome,
    baseline_path,
    check_baseline,
    config_diff,
    dataset_digest,
    default_config_path,
    git_state,
    leaf_paths,
    load_config,
    log_to_mlflow,
    write_baseline,
)

if TYPE_CHECKING:
    from app.core.config import Settings

RULE = "=" * 70


def load_settings() -> Settings:
    """The application's settings — read only when a database is involved, so a suite like `lid`
    runs anywhere, with nothing configured."""
    from app.core.config import get_settings

    return get_settings()


def build_spec(config_name: str, config: dict[str, Any], dataset: str) -> RunSpec:
    suite = SUITES.get(config["suite"])
    if suite is None:
        raise ConfigError(f"unknown suite {config['suite']!r}; known: {', '.join(SUITES)}")
    files = suite.dataset_files(DATASETS / dataset)
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise ConfigError(f"dataset {dataset} lacks {', '.join(missing)}")
    sha, dirty = git_state()
    return RunSpec(
        suite=suite.name,
        config_name=config_name,
        config=config,
        dataset_version=dataset,
        dataset_digest=dataset_digest(files),
        git_sha=sha,
        git_dirty=dirty,
    )


def print_header(spec: RunSpec, *, cases_note: str = "") -> None:
    print(RULE)
    print(f"suite            {spec.suite}")
    print(f"config           {spec.config_name}")
    print(
        f"dataset          {spec.dataset_version} (sha256 {spec.dataset_digest[:12]}){cases_note}"
    )
    print(f"git sha          {spec.git_sha}{' (dirty working tree)' if spec.git_dirty else ''}")
    print(f"started          {datetime.now(UTC).isoformat(timespec='seconds')}")
    print(f"measures         {SUITES[spec.suite].measures}")
    print(RULE)


async def execute(
    spec: RunSpec,
    settings: Settings | None,
    *,
    record: bool,
    show_failures: bool = False,
    reproduces: uuid.UUID | None = None,
    store: RunStore | None = None,
) -> tuple[SuiteOutcome, uuid.UUID | None]:
    """Run one suite under one config; record it if asked. Returns the outcome and run id."""
    print_header(spec)
    suite = SUITES[spec.suite]
    run_id = None
    if record:
        if store is None:
            raise ValueError("recording needs a run store")
        run_id = await store.start(spec, reproduces=reproduces)
    try:
        outcome = await suite.evaluate(
            spec.config, DATASETS / spec.dataset_version, show_failures, settings
        )
    except Exception as exc:
        if run_id is not None and store is not None:
            await store.fail(run_id, f"{type(exc).__name__}: {exc}")
        raise

    print(outcome.report)
    print()
    print("summary_metrics " + json.dumps(outcome.summary, sort_keys=True))

    if run_id is not None and store is not None:
        mlflow_run_id = None
        try:
            mlflow_run_id = log_to_mlflow(spec, outcome, run_id=run_id)
        except ImportError:
            print("NOT LOGGED TO MLFLOW: mlflow is not installed (pip install -e '.[eval]')")
        await store.finish(run_id, outcome, mlflow_run_id=mlflow_run_id)
        print(
            f"recorded         evaluation_runs {run_id}"
            + (f", mlflow {mlflow_run_id}" if mlflow_run_id else "")
        )
    return outcome, run_id


def apply_baseline(
    spec: RunSpec, outcome: SuiteOutcome, run_id: uuid.UUID | None, mode: str | None
) -> int:
    """`write` commits the run's summary as the config's baseline; `check` fails unless the run
    reproduces its committed baseline exactly; `ensure` checks, or writes and prints a baseline
    for a config that has none — for tier T2, whose baselines can only be computed in CI."""
    if mode == "ensure":
        mode = "check" if baseline_path(spec.config_name).exists() else "write"
        printing = mode == "write"
    else:
        printing = False
    if mode == "write":
        if spec.git_dirty:
            print("warning: a baseline from a dirty working tree names code it cannot pin")
        path = write_baseline(spec, outcome, run_id)
        print(f"baseline         {path}")
        if printing:
            # To be reviewed and committed from the log: CI's working tree is thrown away.
            print(path.read_text(encoding="utf-8"))
        return 0
    if mode == "check":
        code, lines = check_baseline(spec, outcome)
        for line in lines:
            print(f"baseline         {line}")
        return code
    return 0


async def run_configs(
    specs: list[RunSpec],
    settings: Settings | None,
    *,
    record: bool,
    show_failures: bool,
    baseline: str | None = None,
) -> int:
    """Run each config, and hold it to its baseline as `baseline` says (apply_baseline)."""
    store = RunStore(settings) if record and settings is not None else None
    status = 0
    try:
        for spec in specs:
            outcome, run_id = await execute(
                spec, settings, record=record, show_failures=show_failures, store=store
            )
            status = max(status, 0 if outcome.ok else 1)
            status = max(status, apply_baseline(spec, outcome, run_id, baseline))
            print()
    finally:
        if store is not None:
            await store.close()
    return status


async def reproduce(run_id: uuid.UUID, settings: Settings, *, record: bool) -> int:
    """Run a recorded run again from its record, and compare."""
    store = RunStore(settings)
    try:
        recorded, recorded_summary = await store.load(run_id)
        now = build_spec(recorded.config_name, recorded.config, recorded.dataset_version)
        if now.dataset_digest != recorded.dataset_digest:
            then, again = recorded.dataset_digest[:12], now.dataset_digest[:12]
            print(
                f"cannot reproduce {run_id}: dataset {recorded.dataset_version} has changed "
                f"since it ran (sha256 {then} then, {again} now)"
            )
            return 2
        if now.git_sha != recorded.git_sha:
            print(f"note: recorded at {recorded.git_sha}, reproducing at {now.git_sha}")
        outcome, _ = await execute(now, settings, record=record, reproduces=run_id, store=store)
    finally:
        await store.close()

    before, after = leaf_paths(recorded_summary), leaf_paths(outcome.summary)
    differences = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if differences:
        print(f"NOT REPRODUCED — {len(differences)} metric(s) differ from run {run_id}:")
        for key in differences:
            print(f"  {key}: {json.dumps(before.get(key))} then, {json.dumps(after.get(key))} now")
        return 1
    print(f"reproduced       every summary metric of run {run_id} came out identical")
    return 0


def describe(rule: DecisionRule, comparison: dict[str, Any]) -> str:
    """The decision's reason in one sentence, from the comparison alone."""
    c = comparison
    if not c.get("cases"):
        return str(c.get("reason", "no comparable cases"))
    low, high = c["gain_95ci"]
    return (
        f"{c['metric']}: {c['baseline_mean']:.4f} → {c['candidate_mean']:.4f} over {c['cases']} "
        f"cases (mean gain {c['mean_gain']:+.4f}, 95% CI [{low:+.4f}, {high:+.4f}]; "
        f"{c['cases_better']} better, {c['cases_worse']} worse). Registered rule: adopt at a gain "
        f"of at least {rule.min_effect} with the interval above zero, reject at the mirror image"
    )


def _per_case(outcome: SuiteOutcome) -> dict[str, dict[str, float]]:
    return {case.case_id: dict(case.metrics) for case in outcome.cases}


async def run_experiment(
    experiment: dict[str, Any],
    dataset: str,
    settings: Settings | None,
    *,
    record: bool,
    show_failures: bool = False,
    baseline_mode: str | None = None,
) -> int:
    """Run both configs and decide. Each run can be held to its own baseline too, so CI need not
    run the same config twice — once for its baseline and once for the experiment."""
    baseline_name, baseline = load_config(CONFIGS / experiment["baseline"])
    candidate_name, candidate = load_config(CONFIGS / experiment["candidate"])
    changed = config_diff(baseline, candidate)
    if len(changed) != 1:
        # EVALUATION.md §7: an experiment changes one variable, or it cannot be attributed.
        what = ", ".join(changed) or "nothing"
        print(f"refusing {experiment['slug']}: its configs differ in {what}, not in one knob")
        return 2
    rule = DecisionRule.from_config(experiment["decision_rule"])

    print(f"experiment       {experiment['slug']} — {experiment['title']}")
    print(f"hypothesis       {experiment['hypothesis']}")
    if "prediction" in experiment:
        print(f"predicted        {experiment['prediction']}")
    print(f"variable         {changed[0]}: {baseline_name} → {candidate_name}")
    print()

    store = RunStore(settings) if record and settings is not None else None
    status = 0
    try:
        base_spec = build_spec(baseline_name, baseline, dataset)
        base_outcome, base_id = await execute(
            base_spec, settings, record=record, show_failures=show_failures, store=store
        )
        status = max(status, apply_baseline(base_spec, base_outcome, base_id, baseline_mode))
        print()
        cand_spec = build_spec(candidate_name, candidate, dataset)
        cand_outcome, cand_id = await execute(
            cand_spec, settings, record=record, show_failures=show_failures, store=store
        )
        status = max(status, apply_baseline(cand_spec, cand_outcome, cand_id, baseline_mode))
        decision, comparison = decide(rule, _per_case(base_outcome), _per_case(cand_outcome))
        rationale = describe(rule, comparison)
        print()
        print(RULE)
        print(f"decision         {decision.upper()}")
        print(f"because          {rationale}")
        for metric, guard in comparison.get("guards", {}).items():
            verdict = " — FAILED" if guard["failed"] else ""
            print(
                f"guard            {metric}: mean loss {guard['mean_loss']:+.4f} "
                f"(allowed {guard['max_loss']}){verdict}"
            )
        print(RULE)
        if store is not None and base_id is not None and cand_id is not None:
            await store.record_experiment(
                slug=experiment["slug"],
                title=experiment["title"],
                hypothesis=experiment["hypothesis"],
                suite=baseline["suite"],
                variable_changed=changed[0],
                decision_rule=experiment["decision_rule"],
                baseline_run_id=base_id,
                candidate_run_id=cand_id,
                comparison=comparison,
                decision=decision,
                rationale=rationale,
            )
            print(f"recorded         experiments {experiment['slug']}")
    finally:
        if store is not None:
            await store.close()
    return status


def _quiet_application_logs() -> None:
    """The report is the output. The application's own INFO lines (a voice turn logs several)
    would bury it; warnings and errors still show."""
    import logging

    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))


def main() -> int:
    _quiet_application_logs()
    parser = argparse.ArgumentParser(description="Run a VaaniOS evaluation suite.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--suite", choices=sorted(SUITES), help="run a suite's default config")
    mode.add_argument("--config", nargs="+", type=Path, help="run each of these configs")
    mode.add_argument("--reproduce", type=uuid.UUID, metavar="RUN_ID", help="re-run a recorded run")
    mode.add_argument("--experiment", type=Path, help="run and decide a registered experiment")
    parser.add_argument("--dataset", default="v1")
    parser.add_argument(
        "--tier",
        choices=["T1", "T2", "T3"],
        help="run only the given configs of this CI tier (a config's `tier`, T1 when it has none)",
    )
    parser.add_argument(
        "--record", action="store_true", help="keep the run in PostgreSQL and MLflow"
    )
    parser.add_argument("--failures", action="store_true", help="print every failing case")
    baselines = parser.add_mutually_exclusive_group()
    baselines.add_argument(
        "--write-baseline",
        action="store_true",
        help="commit each run's summary as its config's baseline (eval/baselines/)",
    )
    baselines.add_argument(
        "--check-baseline",
        action="store_true",
        help="fail unless each run reproduces its config's committed baseline",
    )
    baselines.add_argument(
        "--ensure-baseline",
        action="store_true",
        help="check each run against its baseline, or write and print one where there is none",
    )
    args = parser.parse_args()
    baseline_mode = (
        "write"
        if args.write_baseline
        else "check"
        if args.check_baseline
        else "ensure"
        if args.ensure_baseline
        else None
    )

    try:
        if args.reproduce is not None:
            return asyncio.run(reproduce(args.reproduce, load_settings(), record=args.record))
        if args.experiment is not None:
            experiment = tomllib.loads(args.experiment.read_text(encoding="utf-8"))
            suite = load_config(CONFIGS / experiment["baseline"])[1]["suite"]
            needed = args.record or SUITES[suite].needs_database
            settings = load_settings() if needed else None
            return asyncio.run(
                run_experiment(
                    experiment,
                    args.dataset,
                    settings,
                    record=args.record,
                    show_failures=args.failures,
                    baseline_mode=baseline_mode,
                )
            )
        paths = args.config or [default_config_path(args.suite)]
        loaded = [load_config(path) for path in paths]
        if args.tier is not None:
            # EVALUATION.md §6: T1 runs on every push with nothing to download; T2 needs local
            # models fetched first; T3 needs a paid credential.
            for name, config in loaded:
                if config.get("tier", "T1") != args.tier:
                    print(f"skipped          {name} (tier {config.get('tier', 'T1')})")
            loaded = [(n, c) for n, c in loaded if c.get("tier", "T1") == args.tier]
        specs = [build_spec(name, config, args.dataset) for name, config in loaded]
        needed = args.record or any(SUITES[spec.suite].needs_database for spec in specs)
        settings = load_settings() if needed else None
        return asyncio.run(
            run_configs(
                specs,
                settings,
                record=args.record,
                show_failures=args.failures,
                baseline=baseline_mode,
            )
        )
    except (ConfigError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
