"""Read-only MCP server for the cyber-recovery demo."""

import json
from pathlib import Path
import re
import sqlite3
from typing import Literal
import warnings

warnings.filterwarnings(
    "ignore",
    message=r"Field 'lifespan' has an incomplete definition.*",
)
from mcp.server.fastmcp import FastMCP

DEMO_ROOT = Path(__file__).parent / "demo-data"
DOCUMENT_ROOT = DEMO_ROOT / "documents"
POSTURE_DB = DEMO_ROOT / "backup_posture.db"

mcp = FastMCP(
    "Recovery Evidence",
    instructions="Read-only access to approved recovery documents and backup posture.",
    log_level="WARNING",
)


def _require_setup() -> None:
    if not DOCUMENT_ROOT.is_dir() or not POSTURE_DB.is_file():
        raise RuntimeError(
            "Demo data is missing. Run `python .\\setup_demo.py` first."
        )


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9-]+", value.lower()) if len(token) > 2}


@mcp.tool()
def search_recovery_documents(query: str, max_results: int = 3) -> str:
    """Search approved incident and recovery-policy documents."""
    _require_setup()
    if not query.strip():
        raise ValueError("query must not be empty")
    if not 1 <= max_results <= 5:
        raise ValueError("max_results must be between 1 and 5")

    query_tokens = _tokens(query)
    matches: list[tuple[int, str, str]] = []
    for path in sorted(DOCUMENT_ROOT.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        score = len(query_tokens & _tokens(content))
        if score:
            matches.append((score, path.name, content))

    matches.sort(key=lambda item: (-item[0], item[1]))
    if not matches:
        return "No approved recovery documents matched the query."
    return "\n\n".join(
        f"SOURCE: {name}\n{content}" for _, name, content in matches[:max_results]
    )


@mcp.tool()
def query_backup_posture(
    view: Literal["summary", "at_risk_assets", "recovery_sequence"],
) -> str:
    """Query a governed read-only view of backup and recovery posture."""
    _require_setup()
    queries = {
        "summary": """
            SELECT * FROM recovery_posture ORDER BY tier, service_name
        """,
        "at_risk_assets": """
            SELECT workload_id, service_name, tier, rpo_target_minutes, backup_age_minutes,
                   immutable_copy, last_recovery_test_status, evidence_note
            FROM recovery_posture
            WHERE backup_age_minutes > rpo_target_minutes
               OR immutable_copy = 0
               OR last_recovery_test_status <> 'passed'
            ORDER BY tier, service_name
        """,
        "recovery_sequence": """
            SELECT workload_id, service_name, tier, latest_recovery_point_utc,
                   immutable_copy, last_recovery_test_status, last_test_duration_minutes,
                   evidence_note
            FROM recovery_posture
            ORDER BY CASE workload_id
                WHEN 'active-directory' THEN 1
                WHEN 'patient-scheduling-sql' THEN 2
                WHEN 'claims-postgres' THEN 3
                ELSE 4
            END
        """,
    }
    with sqlite3.connect(f"file:{POSTURE_DB}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute(queries[view]).fetchall()]
    return json.dumps({"view": view, "rows": rows}, indent=2, ensure_ascii=True)


if __name__ == "__main__":
    from demo_cli import run_cli

    run_cli(lambda: mcp.run(transport="stdio"), stderr=True)
