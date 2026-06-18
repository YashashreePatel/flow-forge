from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.schemas import (
    AuditLog,
    DashboardSummary,
    RetryPolicy,
    ScheduleKind,
    TaskStatus,
    WorkflowDefinition,
    WorkflowDefinitionCreate,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowSchedule,
    WorkflowScheduleCreate,
    WorkflowStatus,
    WorkflowStepDefinition,
    WorkflowTask,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def new_trace_id() -> str:
    return uuid.uuid4().hex


class WorkflowStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv("FLOWFORGE_DB_PATH") or self._default_db_path()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _default_db_path(self) -> str:
        if os.getenv("VERCEL"):
            return "/tmp/flowforge.db"
        return "flowforge.db"

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_definitions (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  version INTEGER NOT NULL,
                  steps TEXT NOT NULL,
                  retry_policy TEXT NOT NULL,
                  metadata TEXT NOT NULL,
                  tenant_id TEXT NOT NULL DEFAULT 'default',
                  created_at TEXT NOT NULL,
                  UNIQUE(name, version, tenant_id)
                );

                CREATE TABLE IF NOT EXISTS workflow_executions (
                  id TEXT PRIMARY KEY,
                  definition_id TEXT NOT NULL,
                  workflow_name TEXT NOT NULL,
                  version INTEGER NOT NULL,
                  tenant_id TEXT NOT NULL DEFAULT 'default',
                  status TEXT NOT NULL,
                  current_step TEXT,
                  retry_count INTEGER NOT NULL,
                  trace_id TEXT NOT NULL DEFAULT '',
                  input TEXT NOT NULL,
                  started_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  completed_at TEXT,
                  FOREIGN KEY(definition_id) REFERENCES workflow_definitions(id)
                );

                CREATE TABLE IF NOT EXISTS workflow_tasks (
                  id TEXT PRIMARY KEY,
                  execution_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  position INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  depends_on TEXT NOT NULL DEFAULT '[]',
                  task_queue TEXT NOT NULL DEFAULT 'default',
                  attempts INTEGER NOT NULL,
                  started_at TEXT,
                  completed_at TEXT,
                  lease_expires_at TEXT,
                  worker_id TEXT,
                  error TEXT,
                  FOREIGN KEY(execution_id) REFERENCES workflow_executions(id)
                );

                CREATE TABLE IF NOT EXISTS workflow_events (
                  id TEXT PRIMARY KEY,
                  execution_id TEXT NOT NULL,
                  type TEXT NOT NULL,
                  message TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(execution_id) REFERENCES workflow_executions(id)
                );

                CREATE TABLE IF NOT EXISTS workflow_schedules (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  definition_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  interval_seconds INTEGER,
                  timezone TEXT NOT NULL,
                  enabled INTEGER NOT NULL,
                  input TEXT NOT NULL,
                  next_run_at TEXT NOT NULL,
                  last_run_at TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(definition_id) REFERENCES workflow_definitions(id)
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                  id TEXT PRIMARY KEY,
                  actor TEXT NOT NULL,
                  action TEXT NOT NULL,
                  resource_type TEXT NOT NULL,
                  resource_id TEXT NOT NULL,
                  metadata TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_columns(db)

    def _ensure_columns(self, db: sqlite3.Connection) -> None:
        desired = {
            "workflow_definitions": {
                "tenant_id": "TEXT NOT NULL DEFAULT 'default'",
            },
            "workflow_executions": {
                "tenant_id": "TEXT NOT NULL DEFAULT 'default'",
                "trace_id": "TEXT NOT NULL DEFAULT ''",
            },
            "workflow_tasks": {
                "depends_on": "TEXT NOT NULL DEFAULT '[]'",
                "task_queue": "TEXT NOT NULL DEFAULT 'default'",
                "lease_expires_at": "TEXT",
                "worker_id": "TEXT",
            },
        }
        for table, columns in desired.items():
            existing = {
                row["name"]
                for row in db.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for name, definition in columns.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def create_definition(
        self, payload: WorkflowDefinitionCreate, actor: str = "system"
    ) -> WorkflowDefinition:
        definition = WorkflowDefinition(
            id=new_id("wfd"),
            created_at=utcnow(),
            **payload.model_dump(),
        )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO workflow_definitions
                (id, name, version, steps, retry_policy, metadata, tenant_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    definition.id,
                    definition.name,
                    definition.version,
                    json.dumps([step.model_dump() for step in definition.steps]),
                    definition.retry_policy.model_dump_json(),
                    json.dumps(definition.metadata),
                    definition.tenant_id,
                    definition.created_at.isoformat(),
                ),
            )
            self.add_audit_log(
                db,
                actor,
                "workflow_definition.created",
                "workflow_definition",
                definition.id,
                {"name": definition.name, "version": definition.version},
            )
        return definition

    def list_definitions(self, tenant_id: str | None = None) -> list[WorkflowDefinition]:
        query = "SELECT * FROM workflow_definitions"
        params: tuple[Any, ...] = ()
        if tenant_id:
            query += " WHERE tenant_id = ?"
            params = (tenant_id,)
        query += " ORDER BY name ASC, version DESC"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._definition_from_row(row) for row in rows]

    def get_definition(self, definition_id: str) -> WorkflowDefinition | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM workflow_definitions WHERE id = ?", (definition_id,)
            ).fetchone()
        return self._definition_from_row(row) if row else None

    def get_latest_definition(
        self, name: str, tenant_id: str = "default"
    ) -> WorkflowDefinition | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT * FROM workflow_definitions
                WHERE name = ? AND tenant_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (name, tenant_id),
            ).fetchone()
        return self._definition_from_row(row) if row else None

    def create_execution(
        self,
        definition: WorkflowDefinition,
        workflow_input: dict[str, Any],
        tenant_id: str | None = None,
        actor: str = "system",
    ) -> WorkflowExecution:
        now = utcnow()
        execution_id = new_id("wfe")
        execution_tenant = tenant_id or definition.tenant_id
        tasks = list(definition.steps)
        current_step = self._current_step_label(tasks)
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO workflow_executions
                (id, definition_id, workflow_name, version, tenant_id, status,
                 current_step, retry_count, trace_id, input, started_at, updated_at,
                 completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    definition.id,
                    definition.name,
                    definition.version,
                    execution_tenant,
                    WorkflowStatus.RUNNING,
                    current_step,
                    0,
                    new_trace_id(),
                    json.dumps(workflow_input),
                    now.isoformat(),
                    now.isoformat(),
                    None,
                ),
            )
            for position, step in enumerate(tasks):
                db.execute(
                    """
                    INSERT INTO workflow_tasks
                    (id, execution_id, name, position, status, depends_on, task_queue,
                     attempts, started_at, completed_at, lease_expires_at, worker_id,
                     error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("task"),
                        execution_id,
                        step.name,
                        position,
                        TaskStatus.WAITING if step.depends_on else TaskStatus.RUNNING,
                        json.dumps(step.depends_on),
                        step.task_queue,
                        0,
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
            self.add_event(db, execution_id, "execution.started", f"Started {definition.name}")
            self.add_audit_log(
                db,
                actor,
                "workflow_execution.started",
                "workflow_execution",
                execution_id,
                {"definition_id": definition.id},
            )
        return self.get_execution(execution_id)  # type: ignore[return-value]

    def get_execution(self, execution_id: str) -> WorkflowExecution | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM workflow_executions WHERE id = ?", (execution_id,)
            ).fetchone()
            if not row:
                return None
            tasks = db.execute(
                "SELECT * FROM workflow_tasks WHERE execution_id = ? ORDER BY position",
                (execution_id,),
            ).fetchall()
            events = db.execute(
                "SELECT * FROM workflow_events WHERE execution_id = ? ORDER BY created_at",
                (execution_id,),
            ).fetchall()
        return self._execution_from_row(row, tasks, events)

    def list_executions(
        self, limit: int = 50, tenant_id: str | None = None
    ) -> list[WorkflowExecution]:
        query = "SELECT * FROM workflow_executions"
        params: list[Any] = []
        if tenant_id:
            query += " WHERE tenant_id = ?"
            params.append(tenant_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
            tasks_by_execution = self._group_rows(
                db.execute("SELECT * FROM workflow_tasks ORDER BY position").fetchall(),
                "execution_id",
            )
            events_by_execution = self._group_rows(
                db.execute("SELECT * FROM workflow_events ORDER BY created_at").fetchall(),
                "execution_id",
            )
        return [
            self._execution_from_row(
                row,
                tasks_by_execution.get(row["id"], []),
                events_by_execution.get(row["id"], []),
            )
            for row in rows
        ]

    def transition_execution(
        self,
        execution_id: str,
        status: WorkflowStatus,
        message: str,
        actor: str = "system",
        current_step: str | None = None,
        completed: bool = False,
    ) -> WorkflowExecution | None:
        now = utcnow()
        with self.connect() as db:
            db.execute(
                """
                UPDATE workflow_executions
                SET status = ?, current_step = COALESCE(?, current_step),
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    current_step,
                    now.isoformat(),
                    now.isoformat() if completed else None,
                    execution_id,
                ),
            )
            if status == WorkflowStatus.CANCELED:
                db.execute(
                    """
                    UPDATE workflow_tasks
                    SET status = ?
                    WHERE execution_id = ? AND status IN (?, ?)
                    """,
                    (TaskStatus.CANCELED, execution_id, TaskStatus.WAITING, TaskStatus.RUNNING),
                )
            self.add_event(db, execution_id, f"execution.{status.lower()}", message)
            self.add_audit_log(
                db,
                actor,
                f"workflow_execution.{status.lower()}",
                "workflow_execution",
                execution_id,
                {},
            )
        return self.get_execution(execution_id)

    def reset_failed_execution(
        self, execution_id: str, actor: str = "system"
    ) -> WorkflowExecution | None:
        execution = self.get_execution(execution_id)
        if not execution or execution.status != WorkflowStatus.FAILED:
            return execution
        failed_task = next(
            (task for task in execution.tasks if task.status == TaskStatus.FAILED), None
        )
        if not failed_task:
            return execution
        now = utcnow()
        with self.connect() as db:
            db.execute(
                """
                UPDATE workflow_executions
                SET status = ?, current_step = ?, retry_count = retry_count + 1,
                    updated_at = ?, completed_at = NULL
                WHERE id = ?
                """,
                (WorkflowStatus.RUNNING, failed_task.name, now.isoformat(), execution_id),
            )
            db.execute(
                """
                UPDATE workflow_tasks
                SET status = ?, error = NULL, completed_at = NULL,
                    lease_expires_at = NULL, worker_id = NULL
                WHERE id = ?
                """,
                (TaskStatus.RUNNING, failed_task.id),
            )
            self.add_event(db, execution_id, "execution.retry", f"Retrying from {failed_task.name}")
            self.add_audit_log(
                db,
                actor,
                "workflow_execution.retry",
                "workflow_execution",
                execution_id,
                {"task": failed_task.name},
            )
        return self.get_execution(execution_id)

    def lease_ready_tasks(
        self, worker_id: str, task_queue: str = "default", limit: int = 10
    ) -> list[WorkflowTask]:
        expires_at = utcnow() + timedelta(minutes=5)
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT task.*
                FROM workflow_tasks task
                JOIN workflow_executions execution ON execution.id = task.execution_id
                WHERE task.status = ?
                  AND task.task_queue = ?
                  AND execution.status = ?
                  AND (task.lease_expires_at IS NULL OR task.lease_expires_at < ?)
                ORDER BY task.position ASC
                LIMIT ?
                """,
                (
                    TaskStatus.RUNNING,
                    task_queue,
                    WorkflowStatus.RUNNING,
                    utcnow().isoformat(),
                    limit,
                ),
            ).fetchall()
            for row in rows:
                db.execute(
                    """
                    UPDATE workflow_tasks
                    SET worker_id = ?, lease_expires_at = ?
                    WHERE id = ?
                    """,
                    (worker_id, expires_at.isoformat(), row["id"]),
                )
        return [self._task_from_row(row) for row in rows]

    def mark_task_started(self, task_id: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE workflow_tasks
                SET attempts = attempts + 1, started_at = COALESCE(started_at, ?)
                WHERE id = ?
                """,
                (utcnow().isoformat(), task_id),
            )

    def mark_task_completed(self, execution_id: str, task_id: str, task_name: str) -> None:
        now = utcnow()
        with self.connect() as db:
            db.execute(
                """
                UPDATE workflow_tasks
                SET status = ?, completed_at = ?, error = NULL,
                    lease_expires_at = NULL, worker_id = NULL
                WHERE id = ?
                """,
                (TaskStatus.COMPLETED, now.isoformat(), task_id),
            )
            self.add_event(db, execution_id, "task.completed", f"Completed {task_name}")
            self._activate_ready_dependents(db, execution_id)
            self._refresh_execution_state(db, execution_id)

    def mark_task_failed(self, execution_id: str, task_id: str, task_name: str, error: str) -> None:
        now = utcnow()
        with self.connect() as db:
            db.execute(
                """
                UPDATE workflow_tasks
                SET status = ?, completed_at = ?, error = ?,
                    lease_expires_at = NULL, worker_id = NULL
                WHERE id = ?
                """,
                (TaskStatus.FAILED, now.isoformat(), error, task_id),
            )
            db.execute(
                """
                UPDATE workflow_executions
                SET status = ?, current_step = ?, updated_at = ?
                WHERE id = ?
                """,
                (WorkflowStatus.FAILED, task_name, now.isoformat(), execution_id),
            )
            self.add_event(db, execution_id, "task.failed", f"{task_name} failed: {error}")

    def create_schedule(
        self, payload: WorkflowScheduleCreate, actor: str = "system"
    ) -> WorkflowSchedule:
        schedule = WorkflowSchedule(
            id=new_id("sch"),
            created_at=utcnow(),
            next_run_at=self._next_run_at(payload.kind, payload.interval_seconds),
            **payload.model_dump(),
        )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO workflow_schedules
                (id, name, definition_id, kind, interval_seconds, timezone, enabled,
                 input, next_run_at, last_run_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule.id,
                    schedule.name,
                    schedule.definition_id,
                    schedule.kind,
                    schedule.interval_seconds,
                    schedule.timezone,
                    1 if schedule.enabled else 0,
                    json.dumps(schedule.input),
                    schedule.next_run_at.isoformat(),
                    None,
                    schedule.created_at.isoformat(),
                ),
            )
            self.add_audit_log(
                db,
                actor,
                "workflow_schedule.created",
                "workflow_schedule",
                schedule.id,
                {"definition_id": schedule.definition_id},
            )
        return schedule

    def list_schedules(self) -> list[WorkflowSchedule]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM workflow_schedules ORDER BY created_at DESC"
            ).fetchall()
        return [self._schedule_from_row(row) for row in rows]

    def due_schedules(self) -> list[WorkflowSchedule]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM workflow_schedules
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (utcnow().isoformat(),),
            ).fetchall()
        return [self._schedule_from_row(row) for row in rows]

    def mark_schedule_ran(self, schedule: WorkflowSchedule) -> None:
        now = utcnow()
        next_run_at = self._next_run_at(schedule.kind, schedule.interval_seconds, now)
        with self.connect() as db:
            db.execute(
                """
                UPDATE workflow_schedules
                SET last_run_at = ?, next_run_at = ?
                WHERE id = ?
                """,
                (now.isoformat(), next_run_at.isoformat(), schedule.id),
            )

    def list_audit_logs(self, limit: int = 100) -> list[AuditLog]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._audit_from_row(row) for row in rows]

    def dashboard_summary(self) -> DashboardSummary:
        executions = self.list_executions(limit=10_000)
        total = len(executions)
        completed = sum(1 for item in executions if item.status == WorkflowStatus.COMPLETED)
        durations = [
            (item.completed_at - item.started_at).total_seconds()
            for item in executions
            if item.completed_at
        ]
        task_rows = self._task_metrics()
        queue_depth_by_name: dict[str, int] = {}
        queued_tasks = 0
        for row in task_rows:
            if row["status"] in (TaskStatus.WAITING, TaskStatus.RUNNING):
                queue_depth_by_name[row["task_queue"]] = (
                    queue_depth_by_name.get(row["task_queue"], 0) + row["count"]
                )
                queued_tasks += row["count"]
        return DashboardSummary(
            total_definitions=len(self.list_definitions()),
            total_executions=total,
            running=sum(1 for item in executions if item.status == WorkflowStatus.RUNNING),
            failed=sum(1 for item in executions if item.status == WorkflowStatus.FAILED),
            completed=completed,
            canceled=sum(1 for item in executions if item.status == WorkflowStatus.CANCELED),
            success_rate=round((completed / total) * 100, 2) if total else 0,
            average_runtime_seconds=round(sum(durations) / len(durations), 3) if durations else 0,
            queued_tasks=queued_tasks,
            active_schedules=sum(1 for schedule in self.list_schedules() if schedule.enabled),
            queue_depth_by_name=queue_depth_by_name,
        )

    def add_event(
        self, db: sqlite3.Connection, execution_id: str, event_type: str, message: str
    ) -> None:
        db.execute(
            """
            INSERT INTO workflow_events (id, execution_id, type, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_id("evt"), execution_id, event_type, message, utcnow().isoformat()),
        )

    def add_audit_log(
        self,
        db: sqlite3.Connection,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        metadata: dict[str, Any],
    ) -> None:
        db.execute(
            """
            INSERT INTO audit_logs
            (id, actor, action, resource_type, resource_id, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("aud"),
                actor,
                action,
                resource_type,
                resource_id,
                json.dumps(metadata),
                utcnow().isoformat(),
            ),
        )

    def _activate_ready_dependents(self, db: sqlite3.Connection, execution_id: str) -> None:
        rows = db.execute(
            "SELECT * FROM workflow_tasks WHERE execution_id = ?", (execution_id,)
        ).fetchall()
        completed_names = {
            row["name"] for row in rows if TaskStatus(row["status"]) == TaskStatus.COMPLETED
        }
        for row in rows:
            if TaskStatus(row["status"]) != TaskStatus.WAITING:
                continue
            depends_on = json.loads(row["depends_on"])
            if all(dep in completed_names for dep in depends_on):
                db.execute(
                    "UPDATE workflow_tasks SET status = ? WHERE id = ?",
                    (TaskStatus.RUNNING, row["id"]),
                )

    def _refresh_execution_state(self, db: sqlite3.Connection, execution_id: str) -> None:
        rows = db.execute(
            "SELECT * FROM workflow_tasks WHERE execution_id = ? ORDER BY position",
            (execution_id,),
        ).fetchall()
        now = utcnow()
        if all(TaskStatus(row["status"]) == TaskStatus.COMPLETED for row in rows):
            db.execute(
                """
                UPDATE workflow_executions
                SET status = ?, current_step = NULL, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (WorkflowStatus.COMPLETED, now.isoformat(), now.isoformat(), execution_id),
            )
            return
        running = [
            row["name"] for row in rows if TaskStatus(row["status"]) == TaskStatus.RUNNING
        ]
        current_step = ", ".join(running) if running else None
        db.execute(
            """
            UPDATE workflow_executions
            SET current_step = ?, updated_at = ?
            WHERE id = ?
            """,
            (current_step, now.isoformat(), execution_id),
        )

    def _task_metrics(self) -> list[sqlite3.Row]:
        with self.connect() as db:
            return db.execute(
                """
                SELECT task_queue, status, COUNT(*) AS count
                FROM workflow_tasks
                GROUP BY task_queue, status
                """
            ).fetchall()

    def _definition_from_row(self, row: sqlite3.Row) -> WorkflowDefinition:
        raw_steps = json.loads(row["steps"])
        steps = [
            WorkflowStepDefinition(name=item, depends_on=[])
            if isinstance(item, str)
            else WorkflowStepDefinition.model_validate(item)
            for item in raw_steps
        ]
        return WorkflowDefinition(
            id=row["id"],
            name=row["name"],
            version=row["version"],
            steps=steps,
            retry_policy=RetryPolicy.model_validate_json(row["retry_policy"]),
            metadata=json.loads(row["metadata"]),
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _execution_from_row(
        self,
        row: sqlite3.Row,
        task_rows: Iterable[sqlite3.Row],
        event_rows: Iterable[sqlite3.Row],
    ) -> WorkflowExecution:
        return WorkflowExecution(
            id=row["id"],
            definition_id=row["definition_id"],
            workflow_name=row["workflow_name"],
            version=row["version"],
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
            status=WorkflowStatus(row["status"]),
            current_step=row["current_step"],
            retry_count=row["retry_count"],
            trace_id=row["trace_id"] or new_trace_id(),
            input=json.loads(row["input"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            tasks=[self._task_from_row(task) for task in task_rows],
            events=[self._event_from_row(event) for event in event_rows],
        )

    def _task_from_row(self, row: sqlite3.Row) -> WorkflowTask:
        return WorkflowTask(
            id=row["id"],
            execution_id=row["execution_id"],
            name=row["name"],
            position=row["position"],
            status=TaskStatus(row["status"]),
            depends_on=json.loads(row["depends_on"]) if row["depends_on"] else [],
            task_queue=row["task_queue"],
            attempts=row["attempts"],
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            lease_expires_at=datetime.fromisoformat(row["lease_expires_at"]) if row["lease_expires_at"] else None,
            worker_id=row["worker_id"],
            error=row["error"],
        )

    def _event_from_row(self, row: sqlite3.Row) -> WorkflowEvent:
        return WorkflowEvent(
            id=row["id"],
            execution_id=row["execution_id"],
            type=row["type"],
            message=row["message"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _schedule_from_row(self, row: sqlite3.Row) -> WorkflowSchedule:
        return WorkflowSchedule(
            id=row["id"],
            name=row["name"],
            definition_id=row["definition_id"],
            kind=ScheduleKind(row["kind"]),
            interval_seconds=row["interval_seconds"],
            timezone=row["timezone"],
            enabled=bool(row["enabled"]),
            input=json.loads(row["input"]),
            next_run_at=datetime.fromisoformat(row["next_run_at"]),
            last_run_at=datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _audit_from_row(self, row: sqlite3.Row) -> AuditLog:
        return AuditLog(
            id=row["id"],
            actor=row["actor"],
            action=row["action"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            metadata=json.loads(row["metadata"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _group_rows(self, rows: Iterable[sqlite3.Row], key: str) -> dict[str, list[sqlite3.Row]]:
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row[key], []).append(row)
        return grouped

    def _current_step_label(self, steps: list[WorkflowStepDefinition]) -> str | None:
        ready = [step.name for step in steps if not step.depends_on]
        return ", ".join(ready) if ready else None

    def _next_run_at(
        self,
        kind: ScheduleKind,
        interval_seconds: int | None,
        from_time: datetime | None = None,
    ) -> datetime:
        base = from_time or utcnow()
        if kind == ScheduleKind.INTERVAL:
            return base + timedelta(seconds=interval_seconds or 3600)
        if kind == ScheduleKind.DAILY:
            return base + timedelta(days=1)
        if kind == ScheduleKind.WEEKLY:
            return base + timedelta(days=7)
        return base + timedelta(hours=1)
