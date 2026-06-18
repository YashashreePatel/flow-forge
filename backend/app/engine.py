from __future__ import annotations

from collections.abc import Callable

from app.schemas import TaskStatus, WorkflowExecution, WorkflowStatus
from app.storage import WorkflowStore

StepHandler = Callable[[str, WorkflowExecution], None]


class WorkflowEngine:
    def __init__(self, store: WorkflowStore, step_handler: StepHandler | None = None) -> None:
        self.store = store
        self.step_handler = step_handler or self._default_step_handler

    def run_until_blocked(self, execution_id: str) -> WorkflowExecution | None:
        execution = self.store.get_execution(execution_id)
        while execution and execution.status == WorkflowStatus.RUNNING:
            running_tasks = [
                task for task in execution.tasks if task.status == TaskStatus.RUNNING
            ]
            if not running_tasks:
                return execution

            for running_task in running_tasks:
                self.store.mark_task_started(running_task.id)
                try:
                    self.step_handler(running_task.name, execution)
                except Exception as exc:  # noqa: BLE001 - handler failures are workflow data.
                    self.store.mark_task_failed(
                        execution.id,
                        running_task.id,
                        running_task.name,
                        str(exc),
                    )
                    return self.store.get_execution(execution.id)

                self.store.mark_task_completed(
                    execution.id,
                    running_task.id,
                    running_task.name,
                )
            execution = self.store.get_execution(execution.id)

        return execution

    def retry(self, execution_id: str, actor: str = "system") -> WorkflowExecution | None:
        execution = self.store.reset_failed_execution(execution_id, actor=actor)
        if execution and execution.status == WorkflowStatus.RUNNING:
            return self.run_until_blocked(execution.id)
        return execution

    def lease_once(
        self, worker_id: str, task_queue: str = "default", limit: int = 10
    ) -> list[str]:
        tasks = self.store.lease_ready_tasks(worker_id, task_queue, limit)
        return [task.id for task in tasks]

    def _default_step_handler(self, step_name: str, execution: WorkflowExecution) -> None:
        failures = execution.input.get("fail_steps", [])
        if step_name in failures:
            raise RuntimeError(f"Injected failure for {step_name}")
