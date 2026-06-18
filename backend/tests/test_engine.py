from app.engine import WorkflowEngine
from app.scheduler import WorkflowScheduler
from app.schemas import (
    ScheduleKind,
    TaskStatus,
    WorkflowDefinitionCreate,
    WorkflowScheduleCreate,
    WorkflowStatus,
)
from app.storage import WorkflowStore


def test_engine_completes_ordered_workflow(tmp_path):
    store = WorkflowStore(str(tmp_path / "flowforge.db"))
    definition = store.create_definition(
        WorkflowDefinitionCreate(
            name="order-processing",
            steps=["validate-payment", "reserve-inventory", "send-email"],
        )
    )
    execution = store.create_execution(definition, {"order_id": "ord_123"})

    result = WorkflowEngine(store).run_until_blocked(execution.id)

    assert result is not None
    assert result.status == WorkflowStatus.COMPLETED
    assert [task.status for task in result.tasks] == [TaskStatus.COMPLETED] * 3


def test_engine_persists_failed_step_and_retries(tmp_path):
    store = WorkflowStore(str(tmp_path / "flowforge.db"))
    definition = store.create_definition(
        WorkflowDefinitionCreate(
            name="invoice",
            steps=["generate-invoice", "send-email"],
        )
    )
    execution = store.create_execution(definition, {"fail_steps": ["generate-invoice"]})

    failed = WorkflowEngine(store).run_until_blocked(execution.id)
    assert failed is not None
    assert failed.status == WorkflowStatus.FAILED
    assert failed.current_step == "generate-invoice"

    def recovered_handler(step_name, execution):
        return None

    retried = WorkflowEngine(store, recovered_handler).retry(execution.id)

    assert retried is not None
    assert retried.status == WorkflowStatus.COMPLETED
    assert retried.retry_count == 1


def test_engine_runs_dag_workflow(tmp_path):
    store = WorkflowStore(str(tmp_path / "flowforge.db"))
    definition = store.create_definition(
        WorkflowDefinitionCreate(
            name="video-pipeline",
            steps=[
                {"name": "ingest"},
                {"name": "generate-thumbnail", "depends_on": ["ingest"]},
                {"name": "generate-preview", "depends_on": ["ingest"]},
                {
                    "name": "publish-video",
                    "depends_on": ["generate-thumbnail", "generate-preview"],
                },
            ],
        )
    )
    execution = store.create_execution(definition, {})

    result = WorkflowEngine(store).run_until_blocked(execution.id)

    assert result is not None
    assert result.status == WorkflowStatus.COMPLETED
    assert all(task.status == TaskStatus.COMPLETED for task in result.tasks)
    assert result.tasks[1].depends_on == ["ingest"]
    assert result.tasks[3].depends_on == ["generate-thumbnail", "generate-preview"]


def test_scheduler_starts_due_workflow(tmp_path):
    store = WorkflowStore(str(tmp_path / "flowforge.db"))
    engine = WorkflowEngine(store)
    definition = store.create_definition(
        WorkflowDefinitionCreate(name="hourly-etl", steps=["extract", "load"])
    )
    schedule = store.create_schedule(
        WorkflowScheduleCreate(
            name="hourly-etl",
            definition_id=definition.id,
            kind=ScheduleKind.INTERVAL,
            interval_seconds=60,
        )
    )

    with store.connect() as db:
        db.execute(
            "UPDATE workflow_schedules SET next_run_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", schedule.id),
        )

    started = WorkflowScheduler(store, engine).tick()

    assert len(started) == 1
    assert started[0].status == WorkflowStatus.COMPLETED
    assert store.list_schedules()[0].last_run_at is not None
