"""Pure schema comparison logic — zero I/O, fully testable."""

from __future__ import annotations


def compare(
    source: dict, target: dict
) -> dict:
    """Compare two normalized schemas and return a structured diff.

    Each argument is a dict with keys ``db_type`` and ``tables``.
    Returns a diff dict that the frontend renders as colored tables.
    """
    src_tables = source["tables"]
    tgt_tables = target["tables"]

    src_names = set(src_tables.keys())
    tgt_names = set(tgt_tables.keys())

    only_in_source = sorted(src_names - tgt_names)
    only_in_target = sorted(tgt_names - src_names)
    common_tables = sorted(src_names & tgt_names)

    differences: dict[str, dict] = {}
    for tname in common_tables:
        table_diff = _compare_tables(src_tables[tname], tgt_tables[tname])
        if table_diff is not None:
            differences[tname] = table_diff

    return {
        "source_type": source["db_type"],
        "target_type": target["db_type"],
        "tables_in_source_only": only_in_source,
        "tables_in_target_only": only_in_target,
        "differences": differences,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compare_tables(table_a: dict, table_b: dict) -> dict | None:
    """Return column-level diff detail if tables differ; *None* if identical."""
    cols_a = {c["name"]: c for c in table_a["columns"]}
    cols_b = {c["name"]: c for c in table_b["columns"]}

    names_a = set(cols_a)
    names_b = set(cols_b)

    only_in_left = sorted(names_a - names_b)
    only_in_right = sorted(names_b - names_a)

    common = sorted(names_a & names_b)
    column_diffs: list[dict] = []

    for cname in common:
        ca, cb = cols_a[cname], cols_b[cname]
        changes: dict[str, dict] = {}

        if ca["type"] != cb["type"]:
            changes["type"] = {"source": ca["type"], "target": cb["type"]}

        if ca["nullable"] != cb["nullable"]:
            changes["nullable"] = {
                "source": ca["nullable"],
                "target": cb["nullable"],
            }

        a_dv = ca.get("default_value")
        b_dv = cb.get("default_value")
        if a_dv is not None or b_dv is not None:
            if str(a_dv) != str(b_dv):
                changes["default"] = {
                    "source": a_dv,
                    "target": b_dv,
                }

        if changes:
            column_diffs.append({"name": cname, "changes": changes})

    pk_a = table_a.get("primary_keys", [])
    pk_b = table_b.get("primary_keys", [])
    pk_diff = None
    if sorted(pk_a) != sorted(pk_b):
        pk_diff = {"source": pk_a, "target": pk_b}

    has_diff = bool(only_in_left or only_in_right or column_diffs or pk_diff)
    if not has_diff:
        return None

    result: dict = {}
    if only_in_left:
        result["columns_only_in_source"] = only_in_left
    if only_in_right:
        result["columns_only_in_target"] = only_in_right
    if column_diffs:
        result["column_differences"] = column_diffs
    if pk_diff:
        result["primary_key_difference"] = pk_diff

    return result


# ---------------------------------------------------------------------------
# Inline smoke tests (run via `python diff_engine.py`)
# ---------------------------------------------------------------------------

def _make_table(cols, primary_keys=None):
    """Helper for inline tests."""
    if primary_keys is None:
        primary_keys = [c["name"] for c in cols if "PRIMARY KEY" in c.get("type", "").upper()]
    return {"columns": cols, "primary_keys": primary_keys, "indexes": []}


def _make_schema(tables_dict):
    return {"db_type": "sqlite", "tables": tables_dict}


if __name__ == "__main__":
    import json

    # ---- Test 1: identical schemas -> no diffs ----
    s1 = _make_schema({
        "users": _make_table([
            {"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True},
            {"name": "name", "type": "TEXT", "nullable": False, "default_value": None, "is_primary_key": False},
        ]),
    })
    s2 = _make_schema({
        "users": _make_table([
            {"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True},
            {"name": "name", "type": "TEXT", "nullable": False, "default_value": None, "is_primary_key": False},
        ]),
    })
    diff = compare(s1, s2)
    assert diff["differences"] == {}, f"Expected no diffs, got {diff['differences']}"
    assert diff["tables_in_source_only"] == []
    assert diff["tables_in_target_only"] == []
    print("Test 1 PASSED: identical schemas produce no diffs")

    # ---- Test 2: table only in one side ----
    t2_user_cols = [{"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True}]
    t2_order_cols = [{"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True}]
    s3 = _make_schema({"users": _make_table(t2_user_cols)})
    s4 = _make_schema({"orders": _make_table(t2_order_cols)})
    diff = compare(s3, s4)
    assert "users" in diff["tables_in_source_only"]
    assert "orders" in diff["tables_in_target_only"]
    print("Test 2 PASSED: tables only in one side detected")

    # ---- Test 3: column-level differences ----
    col_a = [
        {"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True},
        {"name": "email", "type": "VARCHAR(255)", "nullable": False, "default_value": None, "is_primary_key": False},
    ]
    col_b = [
        {"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True},
        {"name": "email", "type": "TEXT", "nullable": True, "default_value": "'n/a'", "is_primary_key": False},
    ]
    s5 = _make_schema({"users": _make_table(col_a)})
    s6 = _make_schema({"users": _make_table(col_b)})
    diff = compare(s5, s6)
    assert "users" in diff["differences"]
    ud = diff["differences"]["users"]
    assert ud["column_differences"][0]["name"] == "email"
    assert ud["column_differences"][0]["changes"]["type"]["source"] == "VARCHAR(255)"
    assert ud["column_differences"][0]["changes"]["type"]["target"] == "TEXT"
    print("Test 3 PASSED: column type/nullable/default changes detected")

    # ---- Test 4: columns only in one side (per table) ----
    col_c = [
        {"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True},
        {"name": "extra_col", "type": "TEXT", "nullable": True, "default_value": None, "is_primary_key": False},
    ]
    col_d = [
        {"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True},
    ]
    s7 = _make_schema({"users": _make_table(col_c)})
    s8 = _make_schema({"users": _make_table(col_d)})
    diff = compare(s7, s8)
    assert "extra_col" in diff["differences"]["users"]["columns_only_in_source"]
    print("Test 4 PASSED: columns-only-in-one detected")

    # ---- Test 5: PK difference ----
    col_e = [{"name": "id", "type": "INTEGER", "nullable": False, "default_value": None, "is_primary_key": True}]
    col_f = [
        {"name": "a", "type": "TEXT", "nullable": False, "default_value": None, "is_primary_key": True},
        {"name": "b", "type": "TEXT", "nullable": False, "default_value": None, "is_primary_key": True},
    ]
    s9 = _make_schema({"t": _make_table(col_e)})
    s10 = _make_schema({"t": _make_table(col_f, primary_keys=["a", "b"])})
    diff = compare(s9, s10)
    assert "primary_key_difference" in diff["differences"]["t"]
    print("Test 5 PASSED: PK differences detected")

    print("\nAll tests passed!")
