"""The admin evaluation view (EVALUATION.md §8): recorded runs, decided experiments, failing cases.

Runs are recorded here the way the runner records them (eval/runner.py), so the view is tested
against real records, not hand-made rows.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import User, UserRole
from eval import runner
from eval.recording import CONFIGS, RunStore, load_config


@pytest.fixture(autouse=True)
async def _clean_eval_tables(engine):  # type: ignore[no-untyped-def]
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE experiments, evaluation_results, evaluation_runs"))


async def _admin_headers(client: AsyncClient, db_session: AsyncSession, registered) -> dict:  # type: ignore[no-untyped-def]
    email, password, _ = await registered("evaladmin")
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    user.role = UserRole.ADMIN
    await db_session.commit()
    tokens = (await client.post("/auth/login", json={"email": email, "password": password})).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _record_lid(settings: Settings) -> uuid.UUID:
    spec = runner.build_spec(*load_config(CONFIGS / "lid.toml"), "v1")
    store = RunStore(settings)
    try:
        _, run_id = await runner.execute(spec, settings, record=True, store=store)
    finally:
        await store.close()
    assert run_id is not None
    return run_id


async def test_nothing_recorded_is_empty_lists_not_zeros(
    client: AsyncClient, db_session: AsyncSession, registered
) -> None:  # type: ignore[no-untyped-def]
    headers = await _admin_headers(client, db_session, registered)
    response = await client.get("/admin/evaluation", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"runs": [], "experiments": []}


async def test_each_configs_latest_run_is_shown_with_its_provenance_and_headlines(
    client: AsyncClient, db_session: AsyncSession, registered, settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    headers = await _admin_headers(client, db_session, registered)
    await _record_lid(settings)
    latest = await _record_lid(settings)

    body = (await client.get("/admin/evaluation", headers=headers)).json()

    [run] = body["runs"]
    assert run["id"] == str(latest), "only the latest run of a config"
    assert (run["suite"], run["config_name"], run["dataset_version"]) == ("lid", "lid", "v1")
    assert len(run["dataset_digest"]) == 64
    assert run["case_count"] == 88
    # The lid set has cases the router gets wrong, and the view counts them from the records.
    assert run["failed_count"] > 0
    labels = {h["label"]: h for h in run["headlines"]}
    assert labels["accuracy"]["unit"] == "ratio"
    assert 0 < labels["accuracy"]["value"] <= 1


async def test_a_runs_failing_cases_can_be_browsed(
    client: AsyncClient, db_session: AsyncSession, registered, settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    headers = await _admin_headers(client, db_session, registered)
    run_id = await _record_lid(settings)

    body = (await client.get(f"/admin/evaluation/runs/{run_id}/failures", headers=headers)).json()

    assert body["suite"] == "lid"
    assert body["failed_count"] == len(body["cases"]) > 0
    case = body["cases"][0]
    assert case["expected"]["language"] != case["actual"]["language"]
    assert case["input"]["text"]


async def test_a_decided_experiment_is_shown_with_its_comparison_and_guards(
    client: AsyncClient, db_session: AsyncSession, registered, settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    headers = await _admin_headers(client, db_session, registered)
    baseline, candidate = await _record_lid(settings), await _record_lid(settings)
    store = RunStore(settings)
    try:
        await store.record_experiment(
            slug="EXP-T",
            title="A test experiment",
            hypothesis="h",
            suite="lid",
            variable_changed="x",
            decision_rule={"metric": "m", "higher_is_better": True, "min_effect": 0.1},
            baseline_run_id=baseline,
            candidate_run_id=candidate,
            comparison={
                "metric": "m",
                "cases": 10,
                "baseline_mean": 0.5,
                "candidate_mean": 0.6,
                "mean_gain": 0.1,
                "gain_95ci": [0.05, 0.15],
                "guards": {"g": {"mean_loss": 0.2, "max_loss": 0.0, "failed": True}},
            },
            decision="reject",
            rationale="the guard failed",
        )
    finally:
        await store.close()

    [experiment] = (await client.get("/admin/evaluation", headers=headers)).json()["experiments"]
    assert experiment["slug"] == "EXP-T"
    assert experiment["decision"] == "reject"
    assert experiment["gain_95ci"] == [0.05, 0.15]
    assert experiment["guards"] == [
        {"metric": "g", "mean_loss": 0.2, "max_loss": 0.0, "failed": True}
    ]
    assert experiment["baseline_run_id"] == str(baseline)


async def test_students_cannot_see_evaluation(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    assert (await client.get("/admin/evaluation", headers=headers)).status_code == 403
    missing = f"/admin/evaluation/runs/{uuid.uuid4()}/failures"
    assert (await client.get(missing, headers=headers)).status_code == 403


async def test_an_unknown_run_is_not_found(
    client: AsyncClient, db_session: AsyncSession, registered
) -> None:  # type: ignore[no-untyped-def]
    headers = await _admin_headers(client, db_session, registered)
    response = await client.get(f"/admin/evaluation/runs/{uuid.uuid4()}/failures", headers=headers)
    assert response.status_code == 404
