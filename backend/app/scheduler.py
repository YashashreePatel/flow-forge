from __future__ import annotations

from app.engine import WorkflowEngine
from app.schemas import WorkflowExecution
from app.storage import WorkflowStore


class WorkflowScheduler:
    def __init__(self, store: WorkflowStore, engine: WorkflowEngine) -> None:
        self.store = store
        self.engine = engine

    def tick(self, actor: str = "scheduler") -> list[WorkflowExecution]:
        started: list[WorkflowExecution] = []
        for schedule in self.store.due_schedules():
            definition = self.store.get_definition(schedule.definition_id)
            if not definition:
                self.store.mark_schedule_ran(schedule)
                continue
            execution = self.store.create_execution(
                definition,
                schedule.input,
                tenant_id=definition.tenant_id,
                actor=actor,
            )
            completed = self.engine.run_until_blocked(execution.id) or execution
            started.append(completed)
            self.store.mark_schedule_ran(schedule)
        return started
