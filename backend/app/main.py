from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app.auth import Principal, require_role
from app.engine import WorkflowEngine
from app.metrics import prometheus_metrics
from app.scheduler import WorkflowScheduler
from app.schemas import (
    AuditLog,
    DashboardSummary,
    WorkflowDefinition,
    WorkflowDefinitionCreate,
    WorkflowExecution,
    WorkflowExecutionCreate,
    WorkflowSchedule,
    WorkflowScheduleCreate,
    WorkflowStatus,
)
from app.storage import WorkflowStore

app = FastAPI(title="FlowForge API", version="0.1.0")


def cors_origins() -> list[str]:
    configured = os.getenv("FLOWFORGE_CORS_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = WorkflowStore()
engine = WorkflowEngine(store)
scheduler = WorkflowScheduler(store, engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/workflow-definitions", response_model=WorkflowDefinition, status_code=201)
def create_workflow_definition(
    payload: WorkflowDefinitionCreate,
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> WorkflowDefinition:
    try:
        return store.create_definition(payload, actor=principal.subject)
    except Exception as exc:  # noqa: BLE001 - SQLite unique violations should become API errors.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/workflow-definitions", response_model=list[WorkflowDefinition])
def list_workflow_definitions(
    principal: Annotated[Principal, Depends(require_role("viewer"))],
    tenant_id: str | None = None,
) -> list[WorkflowDefinition]:
    return store.list_definitions(tenant_id=tenant_id or principal.tenant_id)


@app.post(
    "/workflow-definitions/{definition_id}/executions",
    response_model=WorkflowExecution,
    status_code=201,
)
def start_workflow_execution(
    definition_id: str,
    payload: WorkflowExecutionCreate,
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> WorkflowExecution:
    definition = store.get_definition(definition_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    execution = store.create_execution(
        definition,
        payload.input,
        tenant_id=payload.tenant_id,
        actor=principal.subject,
    )
    return engine.run_until_blocked(execution.id) or execution


@app.post(
    "/workflows/{workflow_name}/executions",
    response_model=WorkflowExecution,
    status_code=201,
)
def start_latest_workflow_execution(
    workflow_name: str,
    payload: WorkflowExecutionCreate,
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> WorkflowExecution:
    definition = store.get_latest_definition(workflow_name, payload.tenant_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    execution = store.create_execution(
        definition,
        payload.input,
        tenant_id=payload.tenant_id,
        actor=principal.subject,
    )
    return engine.run_until_blocked(execution.id) or execution


@app.get("/workflow-executions", response_model=list[WorkflowExecution])
def list_workflow_executions(
    principal: Annotated[Principal, Depends(require_role("viewer"))],
    limit: int = 50,
    tenant_id: str | None = None,
) -> list[WorkflowExecution]:
    return store.list_executions(limit=limit, tenant_id=tenant_id or principal.tenant_id)


@app.get("/workflow-executions/{execution_id}", response_model=WorkflowExecution)
def get_workflow_execution(
    execution_id: str,
    principal: Annotated[Principal, Depends(require_role("viewer"))],
) -> WorkflowExecution:
    execution = store.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    return execution


@app.post("/workflow-executions/{execution_id}/retry", response_model=WorkflowExecution)
def retry_workflow_execution(
    execution_id: str,
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> WorkflowExecution:
    execution = engine.retry(execution_id, actor=principal.subject)
    if not execution:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    return execution


@app.post("/workflow-executions/{execution_id}/pause", response_model=WorkflowExecution)
def pause_workflow_execution(
    execution_id: str,
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> WorkflowExecution:
    execution = store.transition_execution(
        execution_id,
        WorkflowStatus.PAUSED,
        "Paused by operator",
        actor=principal.subject,
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    return execution


@app.post("/workflow-executions/{execution_id}/resume", response_model=WorkflowExecution)
def resume_workflow_execution(
    execution_id: str,
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> WorkflowExecution:
    execution = store.transition_execution(
        execution_id,
        WorkflowStatus.RUNNING,
        "Resumed by operator",
        actor=principal.subject,
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    return engine.run_until_blocked(execution.id) or execution


@app.post("/workflow-executions/{execution_id}/cancel", response_model=WorkflowExecution)
def cancel_workflow_execution(
    execution_id: str,
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> WorkflowExecution:
    execution = store.transition_execution(
        execution_id,
        WorkflowStatus.CANCELED,
        "Canceled by operator",
        actor=principal.subject,
        completed=True,
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    return execution


@app.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    principal: Annotated[Principal, Depends(require_role("viewer"))],
) -> DashboardSummary:
    return store.dashboard_summary()


@app.post("/workflow-schedules", response_model=WorkflowSchedule, status_code=201)
def create_workflow_schedule(
    payload: WorkflowScheduleCreate,
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> WorkflowSchedule:
    if not store.get_definition(payload.definition_id):
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    return store.create_schedule(payload, actor=principal.subject)


@app.get("/workflow-schedules", response_model=list[WorkflowSchedule])
def list_workflow_schedules(
    principal: Annotated[Principal, Depends(require_role("viewer"))],
) -> list[WorkflowSchedule]:
    return store.list_schedules()


@app.post("/workflow-schedules/tick", response_model=list[WorkflowExecution])
def run_due_workflow_schedules(
    principal: Annotated[Principal, Depends(require_role("operator"))],
) -> list[WorkflowExecution]:
    return scheduler.tick(actor=principal.subject)


@app.post("/workers/{worker_id}/lease-tasks")
def lease_worker_tasks(
    worker_id: str,
    principal: Annotated[Principal, Depends(require_role("operator"))],
    task_queue: str = "default",
    limit: int = 10,
) -> dict[str, list[str]]:
    return {"task_ids": engine.lease_once(worker_id, task_queue=task_queue, limit=limit)}


@app.get("/audit-logs", response_model=list[AuditLog])
def list_audit_logs(
    principal: Annotated[Principal, Depends(require_role("admin"))],
    limit: int = 100,
) -> list[AuditLog]:
    return store.list_audit_logs(limit=limit)


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=prometheus_metrics(store), media_type="text/plain")
