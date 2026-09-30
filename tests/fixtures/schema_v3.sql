CREATE TABLE schema_versions (version INTEGER NOT NULL);

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scenarios (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
                    progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total BETWEEN 0 AND 100),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS phases (
                    id INTEGER PRIMARY KEY,
                    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL CHECK (position >= 0),
                    name TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL CHECK (duration_seconds BETWEEN 1 AND 86400),
                    color_role TEXT NOT NULL DEFAULT 'custom',
                    repeat_policy TEXT NOT NULL DEFAULT 'every_cycle'
                        CHECK (repeat_policy IN ('once_at_start', 'every_cycle', 'disabled')),
                    sound_enabled INTEGER NOT NULL DEFAULT 1 CHECK (sound_enabled IN (0, 1)),
                    notification_enabled INTEGER NOT NULL DEFAULT 1 CHECK (notification_enabled IN (0, 1)),
                    note TEXT NOT NULL DEFAULT '',
                    progress_marker INTEGER NOT NULL DEFAULT 0 CHECK (progress_marker IN (0, 1)),
                    UNIQUE (scenario_id, position)
                );

                CREATE TABLE IF NOT EXISTS task_groups (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER REFERENCES task_groups(id) ON DELETE RESTRICT,
                    name TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1))
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    group_id INTEGER REFERENCES task_groups(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'archived')),
                    estimate_seconds INTEGER,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS timer_sessions (
                    id INTEGER PRIMARY KEY,
                    scenario_id INTEGER REFERENCES scenarios(id) ON DELETE SET NULL,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    mode TEXT NOT NULL CHECK (mode IN ('scenario', 'free', 'pomodoro')),
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'stopped'))
                );

                CREATE TABLE IF NOT EXISTS time_entries (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER REFERENCES timer_sessions(id) ON DELETE SET NULL,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    scenario_id INTEGER REFERENCES scenarios(id) ON DELETE SET NULL,
                    phase_id INTEGER REFERENCES phases(id) ON DELETE SET NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    elapsed_seconds INTEGER NOT NULL DEFAULT 0 CHECK (elapsed_seconds >= 0),
                    source TEXT NOT NULL DEFAULT 'timer'
                );

                CREATE TABLE IF NOT EXISTS legacy_journal_events (
                    id INTEGER PRIMARY KEY,
                    source_index INTEGER NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_phases_scenario_position
                    ON phases(scenario_id, position);
                CREATE INDEX IF NOT EXISTS idx_time_entries_task_started
                    ON time_entries(task_id, started_at);
                INSERT INTO schema_versions(version) VALUES(3);
                
