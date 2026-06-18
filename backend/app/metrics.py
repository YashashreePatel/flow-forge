from __future__ import annotations

from app.storage import WorkflowStore


def prometheus_metrics(store: WorkflowStore) -> str:
    summary = store.dashboard_summary()
    lines = [
        "# HELP flowforge_workflow_executions_total Total workflow executions.",
        "# TYPE flowforge_workflow_executions_total gauge",
        f"flowforge_workflow_executions_total {summary.total_executions}",
        "# HELP flowforge_workflow_running Current running workflow executions.",
        "# TYPE flowforge_workflow_running gauge",
        f"flowforge_workflow_running {summary.running}",
        "# HELP flowforge_workflow_failed Current failed workflow executions.",
        "# TYPE flowforge_workflow_failed gauge",
        f"flowforge_workflow_failed {summary.failed}",
        "# HELP flowforge_workflow_success_rate Workflow success rate percentage.",
        "# TYPE flowforge_workflow_success_rate gauge",
        f"flowforge_workflow_success_rate {summary.success_rate}",
        "# HELP flowforge_task_queue_depth Tasks waiting or running by queue.",
        "# TYPE flowforge_task_queue_depth gauge",
    ]
    for queue, depth in summary.queue_depth_by_name.items():
        lines.append(f'flowforge_task_queue_depth{{queue="{queue}"}} {depth}')
    lines.append("")
    return "\n".join(lines)
