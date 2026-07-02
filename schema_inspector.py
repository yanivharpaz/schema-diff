"""Database schema introspection for five RDBMS back-ends.

Each handler returns a **normalized** schema dict:

.. code-block:: python

    {
        "db_type": "sqlite",                    # one of: sqlite, postgresql, mysql, oracle, mssql
        "tables": {
            "<table_name>": {
                "columns": [
                    {"name": "...", "type": "...", "nullable": bool,
                     "default_value": ...|None, "is_primary_key": bool, "ordinal_position": int},
                ],
                "primary_keys": ["col1", ...],
                "indexes": [{"name": "...", "columns": [...], "unique": bool}],
            }
        }
    }

Public entry point::

    from schema_inspector import inspect
    schema = inspect({"db_type": "sqlite", "dbfile": "/path/to/db.sqlite"})

"""

from __future__ import annotations

import sqlite3
from typing import Any


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def inspect(connection_info: dict[str, str | int | None]) -> dict[str, Any]:
    """Fetch schema from *connection_info* and return a normalized schema dict.

    Parameters (common across all back-ends):
        db_type:  ``sqlite | postgresql | mysql | oracle | mssql``
        host, port, user, password, database: connection parameters for remote DBs.
        dbfile: file path for SQLite databases.

    Raises ValueError if the driver is not installed.
    """
    db_type = connection_info["db_type"].lower()
    dispatchers = {
        "sqlite":     _inspect_sqlite,
        "postgresql": _inspect_postgresql,
        "mysql":      _inspect_mysql,
        "oracle":     _inspect_oracle,
        "mssql":      _inspect_mssql,
    }
    fn = dispatchers.get(db_type)
    if fn is None:
        raise ValueError(f"Unsupported database type: {db_type!r}")
    return fn(connection_info)


# ---------------------------------------------------------------------------
# SQLite  (stdlib – always available)
# ---------------------------------------------------------------------------

def _inspect_sqlite(info: dict[str, str | int | None]) -> dict[str, Any]:
    conn = sqlite3.connect(str(info["dbfile"]))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        table_names = [r[0] for r in cur.fetchall()]

        tables: dict[str, Any] = {}
        for tname in table_names:
            columns, pk_columns, indexes = _collect_table_info(cur, tname)
            tables[tname] = {
                "columns":      columns,
                "primary_keys": pk_columns,
                "indexes":      indexes,
            }

        return {"db_type": "sqlite", "tables": tables}
    finally:
        conn.close()


def _collect_table_info(cur, tname: str):
    """Collect column/PK/index info for one table via PRAGMA queries."""
    cur.execute(f"PRAGMA table_info('{tname}')")
    pk_columns: list[str] = []
    columns: list[dict] = []
    for row in cur.fetchall():
        # (cid, name, type, notnull, dflt_value, pk)
        columns.append({
            "name":             row[1],
            "type":             row[2] if row[2] else "",
            "nullable":         not bool(row[3]),
            "default_value":    row[4],
            "is_primary_key":   bool(row[5]),
            "ordinal_position": row[0],
        })
        if row[5]:
            pk_columns.append(row[1])

    # Indexes
    cur.execute(f"PRAGMA index_list('{tname}')")
    indexes: list[dict] = []
    for idx_row in cur.fetchall():
        idx_name = idx_row[1]
        unique   = bool(idx_row[2])
        cur.execute(f"PRAGMA index_info('{idx_name}')")
        idx_columns = [r[2] for r in cur.fetchall()]
        indexes.append({
            "name":    idx_name,
            "columns": idx_columns,
            "unique":  unique,
        })

    return columns, pk_columns, indexes


# ---------------------------------------------------------------------------
# PostgreSQL  (psycopg2)
# ---------------------------------------------------------------------------

def _inspect_postgresql(info: dict[str, str | int | None]) -> dict[str, Any]:
    try:
        import psycopg2
    except ImportError:
        raise ValueError("psycopg2 is not installed. Install it with: pip install psycopg2-binary")

    conn = psycopg2.connect(
        host=info["host"],
        port=info.get("port", 5432),
        user=info["user"],
        password=info["password"],
        dbname=info["database"],
    )
    cur = conn.cursor()

    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
    """)
    schemas_tables: list[tuple[str, str]] = cur.fetchall()

    tables: dict[str, Any] = {}
    for schema, tname in schemas_tables:
        qualified = f"{schema}.{tname}"

        # Columns
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, tname))
        columns: list[dict] = []
        for row in cur.fetchall():
            columns.append({
                "name":             row[0],
                "type":             row[1].upper(),
                "nullable":         row[2] == 'YES',
                "default_value":    row[3],
                "is_primary_key":   False,
                "ordinal_position": row[4],
            })

        # Primary keys
        cur.execute("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s AND tc.table_name = %s
        """, (schema, tname))
        pk_columns: list[str] = [r[0] for r in cur.fetchall()]
        for col in columns:
            if col["name"] in pk_columns:
                col["is_primary_key"] = True

        # Indexes from pg_indexes
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s
        """, (schema, tname))
        indexes: list[dict] = []
        for idx_name, idx_def in cur.fetchall():
            cols_str = idx_def.split("(")[1].split(")")[0]
            idx_columns = [c.strip() for c in cols_str.split(",")]
            indexes.append({
                "name":    idx_name,
                "columns": idx_columns,
                "unique":  "UNIQUE" in idx_def.upper(),
            })

        tables[qualified] = {
            "columns":      columns,
            "primary_keys": pk_columns,
            "indexes":      indexes,
        }

    conn.close()
    return {"db_type": "postgresql", "tables": tables}


# ---------------------------------------------------------------------------
# MySQL  (mysql-connector-python)
# ---------------------------------------------------------------------------

def _inspect_mysql(info: dict[str, str | int | None]) -> dict[str, Any]:
    try:
        import mysql.connector
    except ImportError:
        raise ValueError("mysql-connector-python is not installed. Install it with: pip install mysql-connector-python")

    conn = mysql.connector.connect(
        host=info["host"],
        port=int(info.get("port", 3306)),
        user=info["user"],
        password=info["password"],
        database=info["database"],
    )
    cur = conn.cursor()

    cur.execute("""
        SELECT TABLE_NAME FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """)
    table_names: list[str] = [r[0] for r in cur.fetchall()]

    tables: dict[str, Any] = {}
    for tname in table_names:
        # Columns
        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, ORDINAL_POSITION
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (tname,))
        columns: list[dict] = []
        for row in cur.fetchall():
            columns.append({
                "name":             row[0],
                "type":             row[1].upper(),
                "nullable":         row[2] == 'YES',
                "default_value":    row[3],
                "is_primary_key":   False,
                "ordinal_position": row[4],
            })

        # Primary keys
        cur.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = 'PRIMARY'
        """, (tname,))
        pk_columns: list[str] = [r[0] for r in cur.fetchall()]
        for col in columns:
            if col["name"] in pk_columns:
                col["is_primary_key"] = True

        # Indexes via SHOW INDEX
        cur.execute(f"SHOW INDEX FROM {tname}")
        indexes: list[dict] = []
        seen_indexes: set[str] = set()
        for row in cur.fetchall():
            idx_name = row[2]
            if idx_name not in seen_indexes:
                seen_indexes.add(idx_name)
                # (Table, Non_unique, Key_name, Seq_in_index, Column_name, ...)
                col_names = [r[4] for r in cur.fetchall() if r[2] == idx_name]
                indexes.append({"name": idx_name, "columns": col_names, "unique": row[1] == 0})

        tables[tname] = {
            "columns":      columns,
            "primary_keys": pk_columns,
            "indexes":      indexes,
        }

    conn.close()
    return {"db_type": "mysql", "tables": tables}


# ---------------------------------------------------------------------------
# Oracle  (oracledb – drop-in replacement for cx_Oracle)
# ---------------------------------------------------------------------------

def _inspect_oracle(info: dict[str, str | int | None]) -> dict[str, Any]:
    try:
        import oracledb
    except ImportError:
        raise ValueError("oracledb is not installed. Install it with: pip install oracledb")

    dsn = f"{info['host']}:{int(info.get('port', 1521))}/{info.get('service_name', info['database'])}"
    conn = oracledb.connect(
        user=info["user"],
        password=info["password"],
        dsn=dsn,
    )
    cur = conn.cursor()

    owner = str(info["user"]).upper()

    cur.execute("SELECT table_name FROM all_tables WHERE owner = :owner ORDER BY table_name", {"owner": owner})
    table_names: list[str] = [r[0] for r in cur.fetchall()]

    tables: dict[str, Any] = {}
    for tname in table_names:
        # Columns
        cur.execute("""
            SELECT column_name, data_type, nullable, data_default, column_id
            FROM all_tab_columns
            WHERE owner = :owner AND table_name = :tname
            ORDER BY column_id
        """, {"owner": owner, "tname": tname})
        columns: list[dict] = []
        for row in cur.fetchall():
            nullable = row[2] == 'Y'
            default_val = row[3]
            if isinstance(default_val, str):
                default_val = default_val.strip()
            columns.append({
                "name":             row[0],
                "type":             row[1].upper(),
                "nullable":         nullable,
                "default_value":    default_val,
                "is_primary_key":   False,
                "ordinal_position": row[4],
            })

        # Primary keys
        cur.execute("""
            SELECT acc.column_name
            FROM all_cons_columns acc
            JOIN all_constraints ac
              ON acc.constraint_name = ac.constraint_name AND acc.owner = ac.owner
            WHERE ac.constraint_type = 'P'
              AND ac.owner = :owner AND ac.table_name = :tname
        """, {"owner": owner, "tname": tname})
        pk_columns: list[str] = [r[0] for r in cur.fetchall()]
        for col in columns:
            if col["name"] in pk_columns:
                col["is_primary_key"] = True

        # Indexes
        cur.execute("""
            SELECT index_name, uniqueness
            FROM all_indexes
            WHERE owner = :owner AND table_name = :tname
        """, {"owner": owner, "tname": tname})
        indexes: list[dict] = []
        for idx_row in cur.fetchall():
            idx_name = idx_row[0]
            unique   = idx_row[1] == 'UNIQUE'
            cur.execute("""
                SELECT column_name FROM all_ind_columns
                WHERE index_owner = :owner AND index_name = :idx
                ORDER BY column_position
            """, {"owner": owner, "idx": idx_name})
            idx_columns = [r[0] for r in cur.fetchall()]
            indexes.append({"name": idx_name, "columns": idx_columns, "unique": unique})

        tables[tname] = {
            "columns":      columns,
            "primary_keys": pk_columns,
            "indexes":      indexes,
        }

    conn.close()
    return {"db_type": "oracle", "tables": tables}


# ---------------------------------------------------------------------------
# SQL Server  (pyodbc)
# ---------------------------------------------------------------------------

def _inspect_mssql(info: dict[str, str | int | None]) -> dict[str, Any]:
    try:
        import pyodbc
    except ImportError:
        raise ValueError("pyodbc is not installed. Install it with: pip install pyodbc")

    driver_found = False
    for candidate in [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server",
    ]:
        if candidate in pyodbc.drivers():
            driver = candidate
            driver_found = True
            break
    if not driver_found:
        raise ValueError("No SQL Server ODBC driver found. Install one and try again.")

    port = int(info.get("port", 1433))
    server_host = info["host"] if ":" not in str(info["host"]) else f"[{info['host']}]"
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server_host},{port};"
        f"DATABASE={info['database']};"
        f"UID={info['user']};"
        f"PWD={info['password']}"
    )
    conn = pyodbc.connect(conn_str)
    cur = conn.cursor()

    cur.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """)
    schemas_tables: list[tuple[str, str]] = cur.fetchall()

    tables: dict[str, Any] = {}
    for schema, tname in schemas_tables:
        qualified = f"{schema}.{tname}"

        # Columns
        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, (schema, tname))
        columns: list[dict] = []
        for row in cur.fetchall():
            columns.append({
                "name":             row[0],
                "type":             row[1].upper(),
                "nullable":         row[2] == 'YES',
                "default_value":    row[3],
                "is_primary_key":   False,
                "ordinal_position": row[4],
            })

        # Primary keys
        cur.execute("""
            SELECT KU.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS TC
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE KU
              ON TC.CONSTRAINT_NAME = KU.CONSTRAINT_NAME
             AND TC.TABLE_SCHEMA = KU.TABLE_SCHEMA
            WHERE TC.CONSTRAINT_TYPE = 'PRIMARY KEY'
              AND TC.TABLE_SCHEMA = ? AND TC.TABLE_NAME = ?
        """, (schema, tname))
        pk_columns: list[str] = [r[0] for r in cur.fetchall()]
        for col in columns:
            if col["name"] in pk_columns:
                col["is_primary_key"] = True

        # Indexes via sp_helpindex
        indexes: list[dict] = []
        try:
            cur.execute(f"EXEC sp_helpindex '{qualified}'")
            for row in cur.fetchall():
                idx_name    = row[0]
                idx_columns = [r[0] for r in cur.columns if hasattr(r, 'table_name') and r.table_name == f"#{tname}_idx"]
                indexes.append({"name": idx_name, "columns": [], "unique": "unique" in str(row[2]).lower()})
        except Exception:
            pass  # sp_helpindex may not work for every table; skip gracefully

        tables[qualified] = {
            "columns":      columns,
            "primary_keys": pk_columns,
            "indexes":      indexes,
        }

    conn.close()
    return {"db_type": "mssql", "tables": tables}
