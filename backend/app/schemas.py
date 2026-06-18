from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class WorkflowStatus(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class TaskStatus(StrEnum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class RetryStrategy(StrEnum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"


class RetryPolicy(BaseModel):
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    max_attempts: int = Field(default=3, ge=0, le=20)
    initial_delay_seconds: int = Field(default=1, ge=0, le=3600)


class WorkflowStepDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    depends_on: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86_400)
    task_queue: str = Field(default="default", min_length=1, max_length=80)


class WorkflowDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(default=1, ge=1)
    steps: list[WorkflowStepDefinition] = Field(min_length=1)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = Field(default="default", min_length=1, max_length=80)

    @field_validator("steps", mode="before")
    @classmethod
    def normalize_steps(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise TypeError("steps must be a list")
        normalized: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                normalized.append({"name": item, "depends_on": []})
            elif isinstance(item, WorkflowStepDefinition):
                normalized.append(item.model_dump())
            elif isinstance(item, dict):
                normalized.append(item)
            else:
                raise TypeError("each step must be a string or object")
        return normalized


class WorkflowDefinition(WorkflowDefinitionCreate):
    id: str
    created_at: datetime


class WorkflowExecutionCreate(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = Field(default="default", min_length=1, max_length=80)


class WorkflowTask(BaseModel):
    id: str
    execution_id: str
    name: str
    position: int
    status: TaskStatus
    depends_on: list[str] = Field(default_factory=list)
    task_queue: str = "default"
    attempts: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    worker_id: str | None = None
    error: str | None = None


class WorkflowEvent(BaseModel):
    id: str
    execution_id: str
    type: str
    message: str
    created_at: datetime


class WorkflowExecution(BaseModel):
    id: str
    definition_id: str
    workflow_name: str
    version: int
    tenant_id: str
    status: WorkflowStatus
    current_step: str | None
    retry_count: int
    trace_id: str
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    tasks: list[WorkflowTask] = Field(default_factory=list)
    events: list[WorkflowEvent] = Field(default_factory=list)


class ScheduleKind(StrEnum):
    INTERVAL = "interval"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


class WorkflowScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    definition_id: str
    kind: ScheduleKind = ScheduleKind.HOURLY
    interval_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    enabled: bool = True
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowSchedule(WorkflowScheduleCreate):
    id: str
    next_run_at: datetime
    last_run_at: datetime | None = None
    created_at: datetime


class AuditLog(BaseModel):
    id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class DashboardSummary(BaseModel):
    total_definitions: int
    total_executions: int
    running: int
    failed: int
    completed: int
    canceled: int
    success_rate: float
    average_runtime_seconds: float
    queued_tasks: int
    active_schedules: int
    queue_depth_by_name: dict[str, int] = Field(default_factory=dict)
