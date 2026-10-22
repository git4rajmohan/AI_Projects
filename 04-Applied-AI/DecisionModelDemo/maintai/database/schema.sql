-- MaintAI schema (spec1 §11). Limit rows are append-only versions:
-- a new version sets the previous one's effective_to.
CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY,
    machine_id TEXT NOT NULL UNIQUE,
    machine_name TEXT NOT NULL DEFAULT '',
    machine_type TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    team TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY,
    machine_id TEXT NOT NULL REFERENCES machines(machine_id),
    timestamp TEXT NOT NULL,
    temperature_c REAL,
    vibration_mm_s REAL,
    motor_load_percent REAL,
    rpm REAL,
    operating_hours REAL,
    data_source TEXT NOT NULL DEFAULT '',
    validation_status TEXT NOT NULL DEFAULT 'valid',
    UNIQUE (machine_id, timestamp)
);

CREATE TABLE IF NOT EXISTS machine_limits (
    id INTEGER PRIMARY KEY,
    machine_id TEXT NOT NULL REFERENCES machines(machine_id),
    temperature_warning REAL NOT NULL,
    temperature_critical REAL NOT NULL,
    vibration_warning REAL NOT NULL,
    vibration_critical REAL NOT NULL,
    motor_load_warning REAL NOT NULL,
    motor_load_critical REAL NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,              -- NULL = currently active
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS maintenance_decisions (
    id INTEGER PRIMARY KEY,
    machine_id TEXT NOT NULL REFERENCES machines(machine_id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    input_snapshot TEXT NOT NULL,   -- JSON: validated reading + limits used
    rule_alerts TEXT NOT NULL,      -- JSON list
    tev1_action TEXT,
    tev1_probabilities TEXT,        -- JSON, only when Tev1 returned them
    tev1_confidence REAL,           -- NULL when Tev1 didn't return one
    policy_outcome TEXT NOT NULL,
    llm_explanation TEXT,           -- JSON of the explanation payload
    model_name TEXT,
    policy_version TEXT,
    latency_ms REAL,
    error_status TEXT
);

CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY,
    machine_id TEXT NOT NULL REFERENCES machines(machine_id),
    inspection_date TEXT NOT NULL,
    inspector TEXT NOT NULL DEFAULT '',
    findings TEXT NOT NULL DEFAULT '',
    component_condition TEXT NOT NULL DEFAULT '',
    action_taken TEXT NOT NULL DEFAULT '',
    resolution_status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    user_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '' -- JSON
);

CREATE INDEX IF NOT EXISTS idx_readings_machine_ts
    ON sensor_readings (machine_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_machine
    ON maintenance_decisions (machine_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_limits_machine
    ON machine_limits (machine_id, effective_from DESC);