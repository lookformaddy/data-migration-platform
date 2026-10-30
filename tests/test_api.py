import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from data_migration_platform.api import STORE, app  # noqa: E402
from data_migration_platform.cli import build_demo_store, demo_plan  # noqa: E402


@pytest.fixture()
def client():
    STORE.tables = build_demo_store().tables
    return TestClient(app)


def test_health_and_plan_validation(client):
    assert client.get("/health").json()["status"] == "ok"
    resp = client.post("/plans/validate", json={"plan": demo_plan().to_dict(), "mode": "dry_run"})
    assert resp.status_code == 200
    assert resp.json()["ordered_steps"] == ["customers", "orders"]


def test_plan_cycle_rejected(client):
    plan = demo_plan().to_dict()
    plan["steps"][0]["depends_on"] = ["orders"]
    plan["steps"][1]["depends_on"] = ["customers"]
    resp = client.post("/plans/validate", json={"plan": plan, "mode": "dry_run"})
    assert resp.status_code == 422


def test_run_dry_run_via_api_does_not_mutate(client):
    before = dict(STORE.tables)
    resp = client.post("/runs", json={"plan": demo_plan().to_dict(), "mode": "dry_run"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "dry_run_ok"
    assert STORE.tables == before
