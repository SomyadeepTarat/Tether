"""Application metadata alongside the authoritative engine Store.

Legacy full-stack tables are archived, never silently treated as engine-validated.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.inference import public_attempts
from engine.executor import Store
from engine.schemas import GoalContract


def now():
    return datetime.now(timezone.utc).isoformat()


def prepare_database(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        columns = {r[1] for r in con.execute('PRAGMA table_info(contracts)')}
        if 'project_id' not in columns:
            return
        backup_path = path.with_name(path.stem + '.pre-engine.sqlite3')
        if not backup_path.exists():
            backup = sqlite3.connect(backup_path)
            try:
                con.backup(backup)
            finally:
                backup.close()
        with con:
            # Preserve original contents and foreign-key relationships together.
            for name in ('projects', 'contracts', 'sessions', 'actions', 'artifacts', 'changes', 'events'):
                if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone():
                    con.execute(f'ALTER TABLE {name} RENAME TO legacy_{name}')
    finally:
        con.close()


class AppStore(Store):
    def __init__(self, path):
        super().__init__(path)
        self.db.execute('PRAGMA busy_timeout=10000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS app_projects(id TEXT PRIMARY KEY, name TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS app_sessions(id TEXT PRIMARY KEY, project TEXT, status TEXT,
            created_at TEXT, pending_action TEXT, mode TEXT NOT NULL DEFAULT 'single');
        CREATE TABLE IF NOT EXISTS app_resolutions(action_id TEXT PRIMARY KEY, disposition TEXT);
        CREATE TABLE IF NOT EXISTS app_requests(id TEXT PRIMARY KEY, session TEXT, mode TEXT);
        CREATE TABLE IF NOT EXISTS app_workflows(session TEXT PRIMARY KEY, project TEXT, state TEXT, message TEXT);
        CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY, value TEXT);
        ''')

    def _event(self, project, kind, body):
        super()._event(project, kind, {**body, '_recorded_at': now()})

    def record_inference(self, project, session_id, action_id, calls):
        # Reference client retains raw request/response internally. Persist only telemetry.
        super().record_inference(project, session_id, action_id, public_attempts(calls))

    def import_legacy(self):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_contracts'").fetchone():
            return
        if self.db.execute("SELECT 1 FROM app_meta WHERE key='legacy_imported'").fetchone():
            return
        with self._transaction():
            for project, version, body in self.db.execute('SELECT project_id,version,body FROM legacy_contracts ORDER BY version').fetchall():
                data = json.loads(body)
                # Old snapshots omitted execution status. Start pending work explicitly.
                if not any(m.get('status') == 'ACTIVE' for m in data['milestones']):
                    for i, milestone in enumerate(data['milestones']):
                        milestone['status'] = 'ACTIVE' if i == 0 else 'PENDING'
                goal = GoalContract.model_validate(data)
                self.db.execute('INSERT OR IGNORE INTO contracts VALUES(?,?,?)', (project, version, goal.model_dump_json()))
            for row in self.db.execute('SELECT id,name,created_at FROM legacy_projects').fetchall():
                self.db.execute('INSERT OR IGNORE INTO app_projects VALUES(?,?,?)', row)
                self._event(row[0], 'LEGACY_ARCHIVED', {'message': 'Previous dashboard data preserved in legacy tables and pre-engine backup. Legacy report content is archived, not reauthorized against the new fixture.'})
            for session, project, status, created in self.db.execute('SELECT id,project_id,status,created_at FROM legacy_sessions').fetchall():
                self.db.execute('INSERT OR IGNORE INTO sessions VALUES(?,?)', (session, project))
                self.db.execute('INSERT OR IGNORE INTO app_sessions VALUES(?,?,?,?,?,?)', (session, project, 'IDLE', created, None, 'single'))
                self.db.execute('INSERT OR IGNORE INTO checkpoints VALUES(?,?)', (session, json.dumps({'project_id': project, 'session_id': session, 'state': 'IDLE', 'contract_version': self.current_contract(project).version})))
            self.db.execute("INSERT INTO app_meta VALUES('legacy_imported','1')")

    def archive(self, project):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_contracts'").fetchone():
            return {'contracts': [], 'actions': [], 'artifacts': [], 'events': []}
        result = {}
        for table in ('contracts', 'actions', 'artifacts', 'events'):
            cursor = self.db.execute(f'SELECT * FROM legacy_{table} WHERE project_id=?', (project,))
            names = [column[0] for column in cursor.description]
            result[table] = [dict(zip(names, row)) for row in cursor.fetchall()]
        return result
