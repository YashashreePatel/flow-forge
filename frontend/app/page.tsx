"use client";

import {
  Activity,
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  CirclePause,
  CirclePlay,
  Clock3,
  GitBranch,
  Moon,
  Play,
  RefreshCcw,
  Square,
  Sun,
  TerminalSquare
} from "lucide-react";
import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";

type WorkflowStatus = "RUNNING" | "PAUSED" | "COMPLETED" | "FAILED" | "CANCELED";
type TaskStatus = "WAITING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELED";

type WorkflowStep = {
  name: string;
  depends_on: string[];
  task_queue: string;
};

type WorkflowDefinition = {
  id: string;
  name: string;
  version: number;
  steps: WorkflowStep[];
  tenant_id: string;
  created_at: string;
};

type WorkflowTask = {
  id: string;
  name: string;
  position: number;
  status: TaskStatus;
  depends_on: string[];
  task_queue: string;
  attempts: number;
  error?: string | null;
};

type WorkflowExecution = {
  id: string;
  definition_id: string;
  workflow_name: string;
  version: number;
  tenant_id: string;
  status: WorkflowStatus;
  current_step?: string | null;
  retry_count: number;
  trace_id: string;
  started_at: string;
  updated_at: string;
  tasks: WorkflowTask[];
};

type DashboardSummary = {
  total_definitions: number;
  total_executions: number;
  running: number;
  failed: number;
  completed: number;
  canceled: number;
  success_rate: number;
  average_runtime_seconds: number;
  queued_tasks: number;
  active_schedules: number;
  queue_depth_by_name: Record<string, number>;
};

type WorkflowSchedule = {
  id: string;
  name: string;
  definition_id: string;
  kind: "interval" | "hourly" | "daily" | "weekly";
  interval_seconds?: number | null;
  enabled: boolean;
  next_run_at: string;
};

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const defaultWorkflow = `{
  "name": "order-processing",
  "version": 2,
  "steps": [
    { "name": "validate-payment" },
    { "name": "reserve-inventory", "depends_on": ["validate-payment"] },
    { "name": "generate-invoice", "depends_on": ["reserve-inventory"] },
    { "name": "send-email", "depends_on": ["generate-invoice"] }
  ],
  "retry_policy": {
    "strategy": "exponential",
    "max_attempts": 3,
    "initial_delay_seconds": 1
  }
}`;

export default function Home() {
  const [definitions, setDefinitions] = useState<WorkflowDefinition[]>([]);
  const [executions, setExecutions] = useState<WorkflowExecution[]>([]);
  const [schedules, setSchedules] = useState<WorkflowSchedule[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [definitionJson, setDefinitionJson] = useState(defaultWorkflow);
  const [selectedDefinitionId, setSelectedDefinitionId] = useState("");
  const [inputJson, setInputJson] = useState(`{"order_id":"ord_123"}`);
  const [scheduleName, setScheduleName] = useState("hourly order-processing");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function refresh() {
    const [definitionResponse, executionResponse, summaryResponse, scheduleResponse] =
      await Promise.all([
        fetch(`${apiUrl}/workflow-definitions`),
        fetch(`${apiUrl}/workflow-executions?limit=20`),
        fetch(`${apiUrl}/dashboard/summary`),
        fetch(`${apiUrl}/workflow-schedules`)
      ]);

    if (!definitionResponse.ok || !executionResponse.ok || !summaryResponse.ok || !scheduleResponse.ok) {
      throw new Error("FlowForge API is unavailable");
    }

    const nextDefinitions = (await definitionResponse.json()) as WorkflowDefinition[];
    setDefinitions(nextDefinitions);
    setExecutions((await executionResponse.json()) as WorkflowExecution[]);
    setSummary((await summaryResponse.json()) as DashboardSummary);
    setSchedules((await scheduleResponse.json()) as WorkflowSchedule[]);
    setSelectedDefinitionId((current) => current || nextDefinitions[0]?.id || "");
  }

  useEffect(() => {
    refresh().catch((caught: Error) => setError(caught.message));
    const interval = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(interval);
  }, []);

  const activeExecution = useMemo(() => executions[0], [executions]);
  const queueDepth = Object.entries(summary?.queue_depth_by_name ?? {});

  async function createDefinition(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`${apiUrl}/workflow-definitions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: definitionJson
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create workflow");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function startExecution() {
    if (!selectedDefinitionId) {
      setError("Create or select a workflow definition first");
      return;
    }
    setError(null);
    const response = await fetch(`${apiUrl}/workflow-definitions/${selectedDefinitionId}/executions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: JSON.parse(inputJson) })
    });
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    await refresh();
  }

  async function createSchedule() {
    if (!selectedDefinitionId) {
      setError("Create or select a workflow definition first");
      return;
    }
    setError(null);
    const response = await fetch(`${apiUrl}/workflow-schedules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: scheduleName,
        definition_id: selectedDefinitionId,
        kind: "hourly",
        input: JSON.parse(inputJson)
      })
    });
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    await refresh();
  }

  async function action(executionId: string, command: "pause" | "resume" | "retry" | "cancel") {
    setError(null);
    const response = await fetch(`${apiUrl}/workflow-executions/${executionId}/${command}`, {
      method: "POST"
    });
    if (!response.ok) {
      setError(await response.text());
    }
    await refresh();
  }

  return (
    <main className={`app-root ${theme === "dark" ? "theme-dark" : ""}`}>
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <aside className="sidebar">
          <div className="sidebar-header">
            <div className="flex items-center gap-2">
              <div className="brand-mark">
                <GitBranch size={17} />
              </div>
              <div>
                <h1 className="text-sm font-semibold">FlowForge</h1>
                <p className="sidebar-muted">orchestration plane</p>
              </div>
            </div>
          </div>
          <nav className="space-y-1 px-3 py-4 text-sm">
            <NavItem icon={<Activity size={15} />} label="Runs" active />
            <NavItem icon={<TerminalSquare size={15} />} label="Definitions" />
            <NavItem icon={<CalendarClock size={15} />} label="Schedules" />
            <NavItem icon={<Clock3 size={15} />} label="Audit" />
          </nav>
          <div className="sidebar-api">
            <p>API</p>
            <p className="mt-1 truncate font-mono text-[var(--sidebar-strong)]">{apiUrl}</p>
          </div>
        </aside>

        <section className="min-w-0">
          <header className="topbar">
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 lg:px-6">
              <div>
                <p className="eyebrow">Operations</p>
                <h2 className="text-lg font-semibold">Workflow executions</h2>
              </div>
              <div className="flex items-center gap-2">
                <span className="hidden text-xs text-[var(--muted)] sm:inline">
                  {summary?.running ?? 0} running · {summary?.failed ?? 0} failed
                </span>
                <button
                  className="btn-secondary"
                  onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
                  type="button"
                  title="Toggle theme"
                >
                  {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
                  {theme === "dark" ? "Light" : "Dark"}
                </button>
                <button
                  className="btn-secondary"
                  onClick={() => refresh().catch((caught: Error) => setError(caught.message))}
                  type="button"
                  title="Refresh dashboard"
                >
                  <RefreshCcw size={14} />
                  Refresh
                </button>
              </div>
            </div>
          </header>

          <div className="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:px-6">
            <div className="min-w-0 space-y-4">
              {error ? (
                <div className="alert-error">
                  <AlertTriangle className="mt-0.5 shrink-0" size={17} />
                  <span>{error}</span>
                </div>
              ) : null}

              <section className="metric-strip">
                <Metric label="Executions" value={summary?.total_executions ?? 0} />
                <Metric label="Success rate" value={`${summary?.success_rate ?? 0}%`} />
                <Metric label="Queued tasks" value={summary?.queued_tasks ?? 0} />
                <Metric label="Schedules" value={summary?.active_schedules ?? 0} last />
              </section>

              <section className="panel">
                <div className="panel-header flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold">Current run</h3>
                    <p className="text-xs text-[var(--muted)]">
                      {activeExecution?.current_step ?? "No active step"}
                    </p>
                  </div>
                  {activeExecution ? <StatusPill status={activeExecution.status} /> : null}
                </div>

                {activeExecution ? (
                  <div>
                    <div className="section-row grid gap-3 md:grid-cols-[1fr_auto]">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">
                          {activeExecution.workflow_name} v{activeExecution.version}
                        </p>
                        <div className="mt-1 grid gap-1 text-xs text-[var(--muted)] sm:grid-cols-2">
                          <p className="truncate font-mono">{activeExecution.id}</p>
                          <p className="truncate font-mono">trace {activeExecution.trace_id}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <IconButton title="Pause" onClick={() => action(activeExecution.id, "pause")}>
                          <CirclePause size={15} />
                        </IconButton>
                        <IconButton title="Resume" onClick={() => action(activeExecution.id, "resume")}>
                          <CirclePlay size={15} />
                        </IconButton>
                        <IconButton title="Retry" onClick={() => action(activeExecution.id, "retry")}>
                          <RefreshCcw size={15} />
                        </IconButton>
                        <IconButton title="Cancel" onClick={() => action(activeExecution.id, "cancel")}>
                          <Square size={15} />
                        </IconButton>
                      </div>
                    </div>

                    <div className="overflow-x-auto">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Task</th>
                            <th>State</th>
                            <th>Queue</th>
                            <th>Dependencies</th>
                            <th className="text-right">Attempts</th>
                          </tr>
                        </thead>
                        <tbody>
                          {activeExecution.tasks.map((task) => (
                            <tr key={task.id}>
                              <td>
                                <p className="font-medium">{task.position + 1}. {task.name}</p>
                                {task.error ? <p className="mt-1 text-xs text-red-700">{task.error}</p> : null}
                              </td>
                              <td><StatusPill status={task.status} /></td>
                              <td className="font-mono text-xs text-[var(--subtle)]">{task.task_queue}</td>
                              <td className="max-w-[260px] text-xs text-[var(--subtle)]">
                                {task.depends_on.length ? task.depends_on.join(", ") : "none"}
                              </td>
                              <td className="text-right font-mono text-xs">{task.attempts}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (
                  <div className="px-4 py-10 text-sm text-[var(--muted)]">No executions yet.</div>
                )}
              </section>

              <section className="grid gap-4 xl:grid-cols-2">
                <DataPanel title="Recent executions">
                  <div className="divide-y divide-[var(--line-soft)]">
                    {executions.length ? executions.map((execution) => (
                      <div className="grid gap-3 px-4 py-3 sm:grid-cols-[1fr_auto_auto]" key={execution.id}>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{execution.workflow_name}</p>
                          <p className="truncate text-xs text-[var(--muted)]">{execution.current_step ?? "No active step"}</p>
                        </div>
                        <StatusPill status={execution.status} />
                        <p className="text-xs text-[var(--muted)]">retry {execution.retry_count}</p>
                      </div>
                    )) : <EmptyState />}
                  </div>
                </DataPanel>

                <DataPanel title="Schedules">
                  <div className="divide-y divide-[var(--line-soft)]">
                    {schedules.length ? schedules.map((schedule) => (
                      <div className="grid gap-3 px-4 py-3 sm:grid-cols-[1fr_auto]" key={schedule.id}>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{schedule.name}</p>
                          <p className="text-xs text-[var(--muted)]">
                            {schedule.kind} · next {new Date(schedule.next_run_at).toLocaleString()}
                          </p>
                        </div>
                        <span className="text-xs font-semibold text-[var(--subtle)]">
                          {schedule.enabled ? "enabled" : "disabled"}
                        </span>
                      </div>
                    )) : <EmptyState />}
                  </div>
                </DataPanel>
              </section>
            </div>

            <aside className="space-y-4">
              <DataPanel title="Create definition">
                <form className="space-y-3 p-4" onSubmit={createDefinition}>
                  <textarea
                    className="code-input h-72"
                    value={definitionJson}
                    onChange={(event) => setDefinitionJson(event.target.value)}
                    spellCheck={false}
                  />
                  <button
                    className="btn-primary w-full disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={isSubmitting}
                    type="submit"
                  >
                    <CheckCircle2 size={15} />
                    Create definition
                  </button>
                </form>
              </DataPanel>

              <DataPanel title="Run controls">
                <div className="space-y-3 p-4">
                  <select
                    className="field h-9"
                    value={selectedDefinitionId}
                    onChange={(event) => setSelectedDefinitionId(event.target.value)}
                  >
                    <option value="">Select definition</option>
                    {definitions.map((definition) => (
                      <option key={definition.id} value={definition.id}>
                        {definition.name} v{definition.version}
                      </option>
                    ))}
                  </select>
                  <textarea
                    className="field h-24 resize-none p-3 font-mono text-xs"
                    value={inputJson}
                    onChange={(event) => setInputJson(event.target.value)}
                    spellCheck={false}
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      className="btn-accent"
                      onClick={() => startExecution().catch((caught: Error) => setError(caught.message))}
                      type="button"
                    >
                      <Play size={15} />
                      Start
                    </button>
                    <button
                      className="btn-secondary justify-center"
                      onClick={() => createSchedule().catch((caught: Error) => setError(caught.message))}
                      type="button"
                    >
                      <CalendarClock size={15} />
                      Schedule
                    </button>
                  </div>
                  <input
                    className="field h-9"
                    value={scheduleName}
                    onChange={(event) => setScheduleName(event.target.value)}
                  />
                </div>
              </DataPanel>

              <DataPanel title="Queues">
                <div className="divide-y divide-[var(--line-soft)]">
                  {queueDepth.length ? queueDepth.map(([queue, depth]) => (
                    <div className="flex items-center justify-between px-4 py-3 text-sm" key={queue}>
                      <span className="font-mono text-xs text-[var(--subtle)]">{queue}</span>
                      <span className="font-semibold">{depth}</span>
                    </div>
                  )) : <EmptyState />}
                </div>
              </DataPanel>
            </aside>
          </div>
        </section>
      </div>
    </main>
  );
}

function NavItem({
  active,
  icon,
  label
}: {
  active?: boolean;
  icon: ReactNode;
  label: string;
}) {
  return (
    <div className={`nav-item ${active ? "nav-item-active" : ""}`}>
      {icon}
      <span>{label}</span>
    </div>
  );
}

function Metric({
  label,
  last,
  value
}: {
  label: string;
  last?: boolean;
  value: string | number;
}) {
  return (
    <div className={`metric-cell ${last ? "" : "metric-cell-bordered"}`}>
      <p className="eyebrow">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function DataPanel({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function EmptyState() {
  return <div className="px-4 py-6 text-sm text-[var(--muted)]">No records.</div>;
}

function StatusPill({ status }: { status: WorkflowStatus | TaskStatus }) {
  return (
    <span className={`status-pill status-${status.toLowerCase()}`}>
      {status}
    </span>
  );
}

function IconButton({
  children,
  onClick,
  title
}: {
  children: ReactNode;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      className="icon-button"
      onClick={onClick}
      title={title}
      type="button"
    >
      {children}
    </button>
  );
}
