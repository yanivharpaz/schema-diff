# Schema Diff

A **zero-dependency** Python web app for comparing two database schemas side-by-side.

Built with the Python standard library — no pip installs required to run the server or use SQLite. Connectors for PostgreSQL, MySQL, Oracle, and SQL Server are optional and only needed when those databases are actually used.

## Quick start

```bash
cd schema_diff   # or wherever you placed the files
python server.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080) in your browser.

### Demo databases

Two SQLite demo databases are created automatically on first run:

| File | Description |
|------|-------------|
| `demo_source.sqlite` | Source schema (`users`, `orders`) |
| `demo_target.sqlite` | Target schema (`users`, `products`) with deliberate differences |

Click **Load Demo DBs** in the UI to auto-fill both forms and compare them instantly.

## Supported databases

| Database | Driver (optional) | Install |
|----------|------------------|---------|
| SQLite   | `sqlite3` (stdlib) | None |
| PostgreSQL | `psycopg2` | `pip install psycopg2-binary` |
| MySQL    | `mysql-connector-python` | `pip install mysql-connector-python` |
| Oracle   | `oracledb` | `pip install oracledb` |
| SQL Server | `pyodbc` | `pip install pyodbc` |

## How it works

```
┌─────────────┐      POST /api/compare       ┌───────────────┐
│   Browser   │ ────────────────────────────> │    server.py  │
│ (SPA UI)    │ <──────────────────────────── │  + inspector  │
└─────────────┘     JSON diff results         │  + diff engine│
                                                └───────────────┘
```

1. Choose database type and fill connection details for **source** (A) and **target** (B).
2. Click **Compare Schemas**.
3. `server.py` calls `schema_inspector.inspect()` for each connection, producing a normalized schema dict.
4. `diff_engine.compare()` produces the diff → returned as JSON to the browser.

## File structure

```
├── server.py            # HTTP entry point (http.server)
├── schema_inspector.py  # 5 DB introspection handlers
├── diff_engine.py       # Pure comparison logic
├── templates/
│   └── index.html       # SPA UI (HTML + CSS + JS)
├── demo_source.sqlite   # Demo DB A (created on first run)
├── demo_target.sqlite   # Demo DB B (created on first run)
└── README.md
```
