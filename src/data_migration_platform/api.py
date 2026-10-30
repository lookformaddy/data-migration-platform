"""Optional FastAPI surface. Importing this module without FastAPI
installed raises nothing — the app object is simply None, and the API
test module skips. The core engine never depends on the web layer.
"""

from __future__ import annotations

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    _HAS_FASTAPI = True
except Exception:  # pragma: no cover - exercised only when FastAPI missing
    FastAPI = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    BaseModel = object  # type: ignore[assignment]
    _HAS_FASTAPI = False

from data_migration_platform.engine import MigrationEngine
from data_migration_platform.models import MigrationPlan, RunMode
from data_migration_platform.store import TableStore

# A demo store seeded by the caller / tests; the service is stateless
# apart from this store, which mirrors how a real deployment would hold
# a connection pool rather than the data itself.
STORE = TableStore()

if _HAS_FASTAPI:
    app = FastAPI(title="data-migration-platform")

    class PlanPayload(BaseModel):
        plan: dict
        mode: str = "dry_run"

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "data-migration-platform"}

    @app.post("/plans/validate")
    def validate_plan(payload: PlanPayload) -> dict:
        try:
            plan = MigrationPlan.from_dict(payload.plan)
            ordered = [s.step_id for s in plan.ordered_steps()]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"plan_id": plan.plan_id, "valid": True, "ordered_steps": ordered}

    @app.post("/runs")
    def run_plan(payload: PlanPayload) -> dict:
        try:
            plan = MigrationPlan.from_dict(payload.plan)
            mode = RunMode(payload.mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = MigrationEngine(STORE).run(plan, mode=mode)
        return result.manifest.to_dict()
else:  # pragma: no cover
    app = None
