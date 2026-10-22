# Repository (spec1 §11): all parameterized SQL behind functions.
# JSON fields are (de)serialized here so services pass plain dicts. Strings
# never enter SQL via f-strings — every query uses ? placeholders.

import json
import sqlite3
from datetime import datetime
from typing import Any, Optional

LIMIT_FIELDS = ("temperature_warning", "temperature_critical",
                "vibration_warning", "vibration_critical",
                "motor_load_warning", "motor_load_critical")


def _iso(dt: datetime) -> str:
    return dt.isoformat(sep=" ")


def _loads(text: Optional[str]) -> Any:
    return json.loads(text) if text else None


# ---------------------------------------------------------------- machines ---

def upsert_machine(conn, machine: dict) -> None:
    conn.execute(
        """INSERT INTO machines (machine_id, machine_name, machine_type, location,
                                 team, status)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (machine_id) DO UPDATE SET
             machine_name = excluded.machine_name, machine_type = excluded.machine_type,
             location = excluded.location, team = excluded.team,
             status = excluded.status""",
        (machine["machine_id"], machine.get("machine_name", ""),
         machine.get("machine_type", ""), machine.get("location", ""),
         machine.get("team", ""), machine.get("status", "active")),
    )


def list_machines(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM machines ORDER BY machine_id"
    ).fetchall()


def get_machine(conn, machine_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM machines WHERE machine_id = ?", (machine_id,)
    ).fetchone()


# ---------------------------------------------------------------- readings ---

def insert_reading(conn, reading, validation_status: str = "valid") -> None:
    conn.execute(
        """INSERT OR IGNORE INTO sensor_readings
             (machine_id, timestamp, temperature_c, vibration_mm_s, motor_load_percent,
              rpm, operating_hours, data_source, validation_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (reading["machine_id"], _iso(reading["timestamp"]),
         reading.get("temperature_c"), reading.get("vibration_mm_s"),
         reading.get("motor_load_percent"), reading.get("rpm"),
         reading.get("operating_hours"), reading.get("data_source", ""),
         validation_status),
    )


def latest_reading(conn, machine_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM sensor_readings WHERE machine_id = ?
           ORDER BY timestamp DESC LIMIT 1""",
        (machine_id,),
    ).fetchone()


def readings_window(conn, machine_id: str, limit: int) -> list[sqlite3.Row]:
    """Latest `limit` readings, oldest-first (trend order)."""
    return conn.execute(
        """SELECT * FROM (
             SELECT * FROM sensor_readings WHERE machine_id = ?
             ORDER BY timestamp DESC LIMIT ?
           ) ORDER BY timestamp ASC""",
        (machine_id, limit),
    ).fetchall()


# ------------------------------------------------------------------ limits ---

def insert_limit_version(conn, machine_id: str, limits: dict,
                         effective_from: datetime) -> int:
    """Append-only versioning: close the active version, insert the new one."""
    now = _iso(effective_from)
    cur = conn.execute(
        "SELECT MAX(version) FROM machine_limits WHERE machine_id = ?", (machine_id,)
    ).fetchone()
    version = (cur[0] or 0) + 1
    conn.execute(
        "UPDATE machine_limits SET effective_to = ? WHERE machine_id = ? AND effective_to IS NULL",
        (now, machine_id),
    )
    conn.execute(
        f"""INSERT INTO machine_limits
              (machine_id, {', '.join(LIMIT_FIELDS)}, effective_from, effective_to, version)
            VALUES (?, {', '.join('?' * len(LIMIT_FIELDS))}, ?, NULL, ?)""",
        (machine_id, *(limits[f] for f in LIMIT_FIELDS), now, version),
    )
    return version


def active_limits(conn, machine_id: str,
                  as_of: Optional[datetime] = None) -> Optional[sqlite3.Row]:
    """Limits active now, or active at a past timestamp (decision reproduction)."""
    point = _iso(as_of) if as_of else None
    row = conn.execute(
        f"""SELECT * FROM machine_limits WHERE machine_id = ?
              AND effective_from <= ?
              AND (effective_to IS NULL OR effective_to > ?)
            ORDER BY effective_from DESC LIMIT 1""",
        (machine_id, point, point),
    ) if point else conn.execute(
        "SELECT * FROM machine_limits WHERE machine_id = ? AND effective_to IS NULL",
        (machine_id,),
    )
    return row.fetchone()


def list_limit_versions(conn, machine_id: str) -> list[sqlite3.Row]:
    """All threshold versions for one machine, newest first (history view)."""
    return conn.execute(
        f"""SELECT id, machine_id, {', '.join(LIMIT_FIELDS)},
                   effective_from, effective_to, version
            FROM machine_limits WHERE machine_id = ?
            ORDER BY version DESC""",
        (machine_id,),
    ).fetchall()


# --------------------------------------------------------------- decisions ---

def insert_decision(conn, decision: dict) -> int:
    cur = conn.execute(
        """INSERT INTO maintenance_decisions
             (machine_id, input_snapshot, rule_alerts, tev1_action,
              tev1_probabilities, tev1_confidence, policy_outcome, llm_explanation,
              model_name, policy_version, latency_ms, error_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (decision["machine_id"], json.dumps(decision["input_snapshot"]),
         json.dumps(decision["rule_alerts"]), decision.get("tev1_action"),
         json.dumps(decision["tev1_probabilities"])
         if decision.get("tev1_probabilities") is not None else None,
         decision.get("tev1_confidence"), decision["policy_outcome"],
         json.dumps(decision["llm_explanation"])
         if decision.get("llm_explanation") is not None else None,
         decision.get("model_name"), decision.get("policy_version"),
         decision.get("latency_ms"), decision.get("error_status")),
    )
    return cur.lastrowid


def list_decisions(conn, machine_id: Optional[str] = None,
                   limit: int = 50) -> list[sqlite3.Row]:
    if machine_id:
        return conn.execute(
            """SELECT *, json_extract(input_snapshot, '$.timestamp') AS reading_ts
               FROM maintenance_decisions WHERE machine_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (machine_id, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM maintenance_decisions ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


def decision_belongs_to_machine(conn, machine_id: str, decision_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM maintenance_decisions WHERE id = ? AND machine_id = ?",
        (decision_id, machine_id),
    ).fetchone() is not None


# -------------------------------------------------------------- inspections ---

def insert_inspection(conn, inspection: dict) -> int:
    cur = conn.execute(
        """INSERT INTO inspections
             (machine_id, inspection_date, inspector, findings,
              component_condition, action_taken, resolution_status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (inspection["machine_id"], inspection["inspection_date"],
         inspection.get("inspector", ""), inspection.get("findings", ""),
         inspection.get("component_condition", ""),
         inspection.get("action_taken", ""),
         inspection.get("resolution_status", "open")),
    )
    return cur.lastrowid


def list_inspections(conn, machine_id: Optional[str] = None) -> list[sqlite3.Row]:
    if machine_id:
        return conn.execute(
            "SELECT * FROM inspections WHERE machine_id = ? ORDER BY inspection_date DESC",
            (machine_id,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM inspections ORDER BY inspection_date DESC"
    ).fetchall()


def pending_inspections(conn) -> int:
    """Inspection records whose linked machine decisions are still unresolved.
    ponytail: proxy = decisions flagged for review within the last 30 days minus
    closed inspections; upgrade to a proper review state table if the demo needs it."""
    row = conn.execute(
        """SELECT COUNT(*) FROM maintenance_decisions d
           WHERE d.created_at >= datetime('now', '-30 days')
             AND (d.policy_outcome LIKE '%review%' OR d.policy_outcome LIKE '%urgent%'
                  OR d.tev1_action = 'urgent_maintenance')
             AND d.id NOT IN (
               SELECT CASE WHEN json_valid(a.details)
                           THEN CAST(json_extract(a.details, '$.decision_id') AS INTEGER)
                      END
               FROM audit_logs a WHERE a.event_type = 'inspection_recorded'
                 AND CASE WHEN json_valid(a.details)
                          THEN COALESCE(json_extract(a.details, '$.resolution_status'),
                                        'closed')
                     END = 'closed'
                 AND CASE WHEN json_valid(a.details)
                          THEN json_extract(a.details, '$.decision_id')
                     END IS NOT NULL)"""
    ).fetchone()
    return row[0]


# -------------------------------------------------------------------- audit ---

def record_audit(conn, user_id: str, event_type: str, entity_type: str,
                 entity_id: str, details: dict | str = "") -> None:
    conn.execute(
        """INSERT INTO audit_logs (user_id, event_type, entity_type, entity_id, details)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, event_type, entity_type, entity_id,
         details if isinstance(details, str) else json.dumps(details)),
    )


def list_audit(conn, entity_id: Optional[str] = None,
               limit: int = 100) -> list[sqlite3.Row]:
    if entity_id:
        return conn.execute(
            "SELECT * FROM audit_logs WHERE entity_id = ? ORDER BY timestamp DESC LIMIT ?",
            (entity_id, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()


# ---------------------------------------------------------------- dashboard ---

def dashboard_kpis(conn) -> dict:
    """Executive-dashboard aggregates (spec1 §10 page 1) in one round trip."""
    def one(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    return {
        "registered_machines": one("SELECT COUNT(*) FROM machines WHERE status = 'active'"),
        "machines_requiring_review": one(
            """SELECT COUNT(DISTINCT machine_id) FROM maintenance_decisions d
               WHERE d.created_at >= datetime('now', '-30 days')
                 AND (d.policy_outcome LIKE '%review%' OR d.policy_outcome LIKE '%urgent%'
                      OR d.tev1_action = 'urgent_maintenance')
                 AND NOT EXISTS (
                   SELECT 1 FROM audit_logs a
                   WHERE a.event_type = 'inspection_recorded'
                     AND CASE WHEN json_valid(a.details)
                              THEN COALESCE(json_extract(a.details, '$.resolution_status'),
                                            'closed')
                         END = 'closed'
                     AND CASE WHEN json_valid(a.details)
                              THEN json_extract(a.details, '$.decision_id')
                         END = d.id)"""),
        "active_high_priority_alerts": one(
            """SELECT COUNT(DISTINCT machine_id) FROM maintenance_decisions
               WHERE created_at >= datetime('now', '-7 days')
                 AND policy_outcome = 'urgent_human_review'"""),
        "pending_inspections": pending_inspections(conn),
        "recent_decisions": one(
            """SELECT COUNT(*) FROM maintenance_decisions
               WHERE created_at >= datetime('now', '-7 days')"""),
    }


def machine_action_statuses(conn) -> list[dict]:
    """Latest machine decision as a conservative dashboard action flag."""
    rows = conn.execute(
        """SELECT m.machine_id, m.machine_name, d.id AS decision_id,
                  d.created_at, d.tev1_action, d.policy_outcome,
                  CASE WHEN d.id IS NOT NULL
                            AND (d.policy_outcome LIKE '%review%'
                                 OR d.policy_outcome LIKE '%urgent%'
                                 OR d.tev1_action = 'urgent_maintenance')
                            AND NOT EXISTS (
                              SELECT 1 FROM audit_logs a
                              WHERE a.event_type = 'inspection_recorded'
                                AND CASE WHEN json_valid(a.details)
                                         THEN COALESCE(
                                           json_extract(a.details,
                                                        '$.resolution_status'),
                                           'closed')
                                    END = 'closed'
                                AND CASE WHEN json_valid(a.details)
                                         THEN json_extract(a.details,
                                                           '$.decision_id')
                                    END = d.id)
                       THEN 1 ELSE 0 END AS review_pending
           FROM machines m
           LEFT JOIN maintenance_decisions d
             ON d.id = (SELECT id FROM maintenance_decisions
                        WHERE machine_id = m.machine_id
                        ORDER BY created_at DESC, id DESC LIMIT 1)
           ORDER BY m.machine_id"""
    ).fetchall()
    statuses = []
    for row in rows:
        decision = dict(row)
        if decision["decision_id"] is None:
            flag, label = "⚪", "Not assessed"
        elif decision["review_pending"]:
            flag, label = "🔴", "Action required"
        elif (decision["tev1_action"] == "monitor"
              and decision["policy_outcome"] == "policy_auto_decision"):
            flag, label = "🟢", "No action required"
        else:
            flag, label = "🟡", "Wait & observe"
        statuses.append({**decision, "flag": flag, "status": label})
    return statuses


def action_counts(conn, since_days: int = 7) -> list[tuple[str, int]]:
    return conn.execute(
        """SELECT policy_outcome, COUNT(*) FROM maintenance_decisions
           WHERE created_at >= datetime('now', ?) GROUP BY policy_outcome""",
        (f"-{since_days} days",),
    ).fetchall()


def alerts_over_time(conn, since_days: int = 7) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT date(created_at) AS day,
                  SUM(policy_outcome LIKE '%review%' OR policy_outcome LIKE '%urgent%') AS alerts
           FROM maintenance_decisions
           WHERE created_at >= datetime('now', ?) GROUP BY day ORDER BY day""",
        (f"-{since_days} days",),
    ).fetchall()