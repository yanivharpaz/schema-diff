#!/usr/bin/env python3
"""Schema Diff — a zero-dependency web app for comparing database schemas.

Start::

    python server.py

The server runs on http://127.0.0.1:8080 and serves:
- GET /         -> the SPA UI (templates/index.html)
- POST /api/compare -> compare two schemas and return JSON diff
"""

from __future__ import annotations

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Resolve paths relative to this file's directory
_BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE))

from schema_inspector import inspect as db_inspect  # noqa: E402
from diff_engine     import compare               # noqa: E402


# ── Request handler ───────────────────────────────────────────────

class DiffHandler(BaseHTTPRequestHandler):
    """Serve the SPA on GET / and schema comparison on POST /api/compare."""

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- GET ────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path == "/index.html":
            tpl = _BASE / "templates" / "index.html"
            if not tpl.exists():
                self.send_error(404, "templates/index.html not found")
                return
            data = tpl.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    # ---- POST ───────────────────────────────────────────────────
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/compare":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return self._send_json(400, {"error": "Invalid JSON body"})

        source = raw.get("source")
        target = raw.get("target")
        if not source or not target:
            return self._send_json(400, {"error": "Both 'source' and 'target' are required"})

        try:
            schema_a = db_inspect(source)
            schema_b = db_inspect(target)
            result = compare(schema_a, schema_b)
            self._send_json(200, {"error": None, "result": result})
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})


# ── Demo DB creator ───────────────────────────────────────────────

def _create_demo_if_needed() -> None:
    """Create demo_source.sqlite and demo_target.sqlite if they don't exist."""
    src = _BASE / "demo_source.sqlite"
    tgt = _BASE / "demo_target.sqlite"
    if src.exists() or tgt.exists():
        return

    import sqlite3

    # --- Source DB ----------------------------------------------------
    conn = sqlite3.connect(str(src))
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE users (
            id   INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            age  INTEGER,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE orders (
            id         INTEGER PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            total      REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX idx_orders_user ON orders(user_id);
    """)
    c.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@example.com', 30, 'active')")
    conn.commit()
    conn.close()

    # --- Target DB ----------------------------------------------------
    conn = sqlite3.connect(str(tgt))
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE users (
            id          INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            email       TEXT,
            age         TEXT DEFAULT '0',
            status      INTEGER DEFAULT 1,
            last_login  TEXT
        );
        CREATE TABLE products (
            id    INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            price REAL NOT NULL
        );
        CREATE INDEX idx_users_email ON users(email);
    """)
    c.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@example.com', 30, 1, '2025-01-01')")
    conn.commit()
    conn.close()


# ── Main ───────────────────────────────────────────────────────────

def main(host: str = "127.0.0.1", port: int = 8080) -> None:
    _create_demo_if_needed()
    server = HTTPServer((host, port), DiffHandler)
    print(f"Schema Diff is running on http://{host}:{port}")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
