from __future__ import annotations

import os
import time

from app.engine import WorkflowEngine
from app.scheduler import WorkflowScheduler
from app.storage import WorkflowStore


def main() -> None:
    store = WorkflowStore()
    engine = WorkflowEngine(store)
    scheduler = WorkflowScheduler(store, engine)
    worker_id = os.getenv("FLOWFORGE_WORKER_ID", "local-worker")
    task_queue = os.getenv("FLOWFORGE_TASK_QUEUE", "default")
    interval_seconds = int(os.getenv("FLOWFORGE_WORKER_INTERVAL_SECONDS", "5"))

    while True:
        scheduler.tick(actor=worker_id)
        engine.lease_once(worker_id, task_queue=task_queue)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
