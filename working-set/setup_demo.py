"""Create the fictional documents and SQLite data used by the demo."""

from pathlib import Path
import sqlite3

DEMO_ROOT = Path(__file__).parent / "demo-data"
DOCUMENT_ROOT = DEMO_ROOT / "documents"
POSTURE_DB = DEMO_ROOT / "backup_posture.db"

DOCUMENTS = {
    "cyber-recovery-standard.md": """# Contoso Health Cyber Recovery Standard

## Recovery gates
1. Isolate affected production networks and disable compromised identities before restore activity.
2. Tier-0 workloads require an immutable recovery point no older than their approved RPO.
3. Restore identity and DNS dependencies before dependent applications.
4. Validate candidate recovery points in the clean room with malware scanning and application-owner checks.
5. Security and the application owner must approve production cutover.

## Service objectives
- Tier 0: RPO 15 minutes, RTO 2 hours.
- Tier 1: RPO 4 hours, RTO 8 hours.

Do not treat a successful backup job as proof that a recovery point is clean or recoverable.
""",
    "incident-ir-2026-0926.md": """# Incident IR-2026-0926

- At 09:42 UTC, EDR detected mass file renames on the primary virtualization cluster.
- The account svc-backup-legacy showed anomalous authentication from a production jump host.
- Network containment of the cluster started at 09:51 UTC and remains in progress.
- The identity team reports that Active Directory is operational, but privileged-session revocation
  has not yet been independently verified.
- Business priority is patient scheduling first, followed by claims processing.
- No production restore has been authorized. All analysis must use read-only evidence.
""",
}

POSTURE_ROWS = [
    (
        "patient-scheduling-sql",
        "Patient scheduling",
        0,
        15,
        12,
        120,
        68,
        1,
        "2026-09-26T09:35:00Z",
        "2026-09-20",
        "passed",
        "Clean-room restore passed; application owner validated login and booking.",
    ),
    (
        "claims-postgres",
        "Claims processing",
        0,
        15,
        38,
        120,
        105,
        1,
        "2026-09-26T09:08:00Z",
        "2026-09-18",
        "failed",
        "Database restored, but DNS dependency prevented application validation.",
    ),
    (
        "active-directory",
        "Identity services",
        0,
        15,
        9,
        120,
        44,
        1,
        "2026-09-26T09:38:00Z",
        "2026-09-22",
        "passed",
        "Forest recovery test passed; privileged-session revocation was out of scope.",
    ),
    (
        "finance-vmware",
        "Finance virtual machines",
        1,
        240,
        75,
        480,
        210,
        0,
        "2026-09-26T08:32:00Z",
        "2026-08-15",
        "passed_with_exceptions",
        "Restore passed, but the selected copy was not immutable.",
    ),
]


def main() -> None:
    DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)
    for name, content in DOCUMENTS.items():
        (DOCUMENT_ROOT / name).write_text(content, encoding="utf-8")

    with sqlite3.connect(POSTURE_DB) as connection:
        connection.executescript(
            """
            DROP TABLE IF EXISTS recovery_posture;
            CREATE TABLE recovery_posture (
                workload_id TEXT PRIMARY KEY,
                service_name TEXT NOT NULL,
                tier INTEGER NOT NULL,
                rpo_target_minutes INTEGER NOT NULL,
                backup_age_minutes INTEGER NOT NULL,
                rto_target_minutes INTEGER NOT NULL,
                last_test_duration_minutes INTEGER NOT NULL,
                immutable_copy INTEGER NOT NULL CHECK (immutable_copy IN (0, 1)),
                latest_recovery_point_utc TEXT NOT NULL,
                last_recovery_test_date TEXT NOT NULL,
                last_recovery_test_status TEXT NOT NULL,
                evidence_note TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO recovery_posture VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            POSTURE_ROWS,
        )

    print(f"Created demo documents in {DOCUMENT_ROOT}")
    print(f"Created demo posture database at {POSTURE_DB}")
    print("Setup complete. Run: python .\\02_concurrent_workflow_demo.py")


if __name__ == "__main__":
    from demo_cli import run_cli

    run_cli(main)
