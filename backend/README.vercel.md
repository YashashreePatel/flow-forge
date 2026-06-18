# FlowForge API on Vercel

Deploy this folder as a standalone Vercel project.

## Settings

- Root Directory: `backend`
- Framework Preset: Other
- Python entrypoint: `app/main.py`

## Environment Variables

```text
FLOWFORGE_CORS_ORIGINS=https://flow-forge.vercel.app,https://yashashree.vercel.app
FLOWFORGE_AUTH_TOKENS=your-token:yashashree:admin:default
```

`FLOWFORGE_DB_PATH` is optional. On Vercel the fallback is `/tmp/flowforge.db`, which is fine for demos but not durable storage. For persistent workflow state, replace SQLite with a hosted database such as Vercel Postgres/Neon.
