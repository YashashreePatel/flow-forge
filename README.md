# FlowForge

Distributed workflow orchestration platform inspired by Temporal and Netflix Conductor.

FlowForge lets teams define, execute, monitor, and recover long-running business workflows without hand-rolling retry logic, state persistence, or dashboard plumbing.

## MVP

This repository contains a Phase 1-3 vertical slice:

- Create workflow definitions from JSON.
- Start workflow executions.
- Execute ordered tasks with persistent state.
- Retry failed executions with fixed or exponential backoff policy metadata.
- Pause, resume, cancel, and inspect executions.
- View a dashboard-ready REST API and a Next.js operator UI.
- Define DAG workflows with task dependencies.
- Start the latest workflow version by workflow name.
- Create interval/hourly/daily/weekly schedules.
- Use role-based bearer tokens for viewer/operator/admin actions.
- Export Prometheus metrics and trace IDs.
- Run API, worker, frontend, and observability services through Docker Compose.

## Repository Layout

```text
backend/       FastAPI API, SQLite-backed persistence, Python workflow engine
frontend/      Next.js, TypeScript, Tailwind dashboard
docker-compose.yml
monitoring/     Prometheus, Grafana, Loki local configuration
k8s/            Kubernetes deployment manifests
```

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

The API starts at `http://localhost:8000`.

Useful endpoints:

- `GET /health`
- `POST /workflow-definitions`
- `GET /workflow-definitions`
- `POST /workflow-definitions/{definition_id}/executions`
- `POST /workflows/{workflow_name}/executions`
- `GET /workflow-executions`
- `POST /workflow-executions/{execution_id}/retry`
- `POST /workflow-executions/{execution_id}/pause`
- `POST /workflow-executions/{execution_id}/resume`
- `POST /workflow-executions/{execution_id}/cancel`
- `POST /workflow-schedules`
- `GET /workflow-schedules`
- `POST /workflow-schedules/tick`
- `GET /audit-logs`
- `GET /dashboard/summary`
- `GET /metrics`

## DAG Workflow Example

```json
{
  "name": "video-pipeline",
  "version": 1,
  "steps": [
    { "name": "ingest" },
    { "name": "generate-thumbnail", "depends_on": ["ingest"] },
    { "name": "generate-preview", "depends_on": ["ingest"] },
    {
      "name": "publish-video",
      "depends_on": ["generate-thumbnail", "generate-preview"]
    }
  ]
}
```

Steps without dependencies become runnable immediately. Dependent steps are released when all upstream steps complete.

## Auth And RBAC

Local development allows anonymous admin access for convenience. To exercise bearer-token RBAC, pass:

```bash
Authorization: Bearer dev-admin-token
Authorization: Bearer dev-operator-token
Authorization: Bearer dev-viewer-token
```

For deployments, set `FLOWFORGE_AUTH_TOKENS` as comma-separated token descriptors:

```text
token:subject:role1|role2:tenant
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The dashboard starts at `http://localhost:3000`.

Set `NEXT_PUBLIC_API_URL` to point at the backend if it is not running on `http://localhost:8000`.

For a single Vercel multi-service deployment, set:

```text
NEXT_PUBLIC_API_URL=/_/backend
NEXT_PUBLIC_BASE_PATH=/archive/flow-forge
```

## Docker

```bash
docker compose up --build
```

This starts:

- Frontend on `http://localhost:3000`
- Backend on `http://localhost:8000`
- PostgreSQL and Redis placeholders for Phase 2 storage/queue migration
- Worker scheduler loop
- Prometheus on `http://localhost:9090`
- Grafana on `http://localhost:3001`
- Jaeger on `http://localhost:16686`
- Loki on `http://localhost:3100`

## Kubernetes

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/
```

The manifests define API, worker, frontend, and Prometheus deployments. They are intentionally plain YAML so they can later be wrapped by Helm or Kustomize.

## Test

```bash
cd backend
python -m pytest
```

## Roadmap

Next production hardening should replace SQLite with PostgreSQL repositories, use Redis Streams or a broker for task dispatch, sign JWTs through an identity provider, and emit OpenTelemetry spans to Jaeger instead of only carrying trace IDs.
