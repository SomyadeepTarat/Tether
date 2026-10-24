"""Reference SQLite engine adapter; full-stack can replace it behind the same methods.

Authorization is rechecked inside the write transaction. Contracts are append-only;
checkpoint state and artifacts commit atomically. No caller-supplied ALLOW is accepted.
"""
import json
import sqlite3
from pathlib import Path
from engine.schemas import AgentAction, GoalContract, StepResult
from engine.validator import validate_action
from engine.state import LifecycleStore

class Store(LifecycleStore):
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS milestone_state(project TEXT, milestone TEXT, status TEXT,
            PRIMARY KEY(project,milestone));
        CREATE TABLE IF NOT EXISTS changes(id TEXT PRIMARY KEY, project TEXT, body TEXT, status TEXT, actor TEXT);
        CREATE TABLE IF NOT EXISTS handoffs(id TEXT PRIMARY KEY, project TEXT, session TEXT, result TEXT);

        CREATE TABLE IF NOT EXISTS contracts(project TEXT, version INTEGER, body TEXT NOT NULL,
            PRIMARY KEY(project,version));
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, project TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, project TEXT, body TEXT NOT NULL,
            result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS artifacts(project TEXT, section TEXT, content TEXT NOT NULL,
            action_id TEXT NOT NULL, PRIMARY KEY(project,section));
        CREATE TABLE IF NOT EXISTS checkpoints(session TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, project TEXT, kind TEXT, body TEXT);
        ''')

    def close(self):
        self.db.close()

    def create_goal_contract(self, contract: GoalContract):
        if contract.version != 1:
            raise ValueError("Initial contract must be version 1")
        with self._transaction():
            if self.db.execute("SELECT 1 FROM contracts WHERE project=?", (contract.project_id,)).fetchone():
                raise ValueError("Project already exists")
            self.db.execute("INSERT INTO contracts VALUES(?,?,?)",
                            (contract.project_id, contract.version, contract.model_dump_json()))
            self._event(contract.project_id, "CONTRACT_CREATED", contract.model_dump(mode="json"))

    def current_contract(self, project):
        row = self.db.execute("SELECT body FROM contracts WHERE project=? ORDER BY version DESC LIMIT 1", (project,)).fetchone()
        if row is None:
            raise ValueError("Unknown project")
        return GoalContract.model_validate_json(row[0])

    def start_session(self, project, session_id):
        with self._transaction():
            contract = self.effective_contract(project)
            self.db.execute("INSERT INTO sessions VALUES(?,?)", (session_id, project))
            self.db.execute("INSERT INTO checkpoints VALUES(?,?)", (session_id, json.dumps({
                "project_id": project, "session_id": session_id, "contract_version": contract.version, "state": "IDLE"})))
            self._event(project, "SESSION_STARTED", {"session_id": session_id})

    def sections(self, project):
        return dict(self.db.execute("SELECT section,content FROM artifacts WHERE project=?", (project,)))

    def action_result(self, action_id):
        row = self.db.execute("SELECT result FROM actions WHERE id=?", (action_id,)).fetchone()
        return StepResult.model_validate_json(row[0]) if row else None

    def commit_action(self, action: AgentAction, references):
        with self._transaction():
            row = self.db.execute("SELECT body,result FROM actions WHERE id=?", (action.action_id,)).fetchone()
            if row:
                if AgentAction.model_validate_json(row[0]) != action:
                    raise ValueError("Idempotency key reused for different action")
                return StepResult.model_validate_json(row[1]).model_copy(update={"replayed": True})
            session = self.db.execute("SELECT project FROM sessions WHERE id=?", (action.session_id,)).fetchone()
            if session is None or session[0] != action.project_id:
                raise ValueError("Unknown session or project mismatch")
            contract = self.effective_contract(action.project_id)
            validation = validate_action(action, contract, action.session_id, references,
                                         set(self.sections(action.project_id)))
            committed = validation.decision == "ALLOW"
            result = StepResult(action=action, validation=validation, committed=committed)
            self.db.execute("INSERT INTO actions VALUES(?,?,?,?)", (
                action.action_id, action.project_id, action.model_dump_json(), result.model_dump_json()))
            if committed:
                self.db.execute("INSERT INTO artifacts VALUES(?,?,?,?) ON CONFLICT(project,section) DO UPDATE SET content=excluded.content, action_id=excluded.action_id",
                                (action.project_id, action.arguments.section_id, action.arguments.content, action.action_id))
            checkpoint = {"project_id": action.project_id, "session_id": action.session_id,
                          "contract_version": contract.version, "last_action_id": action.action_id,
                          "state": "COMPLETED" if committed else "BLOCKED" if validation.decision == "BLOCK" else "AWAITING_REVIEW"}
            self.db.execute("INSERT INTO checkpoints VALUES(?,?) ON CONFLICT(session) DO UPDATE SET body=excluded.body",
                            (action.session_id, json.dumps(checkpoint)))
            self._event(action.project_id, "ACTION_COMMITTED" if committed else "ACTION_" + validation.decision,
                        result.model_dump(mode="json"))
            return result

    def restore_checkpoint(self, session_id):
        row = self.db.execute("SELECT body FROM checkpoints WHERE session=?", (session_id,)).fetchone()
        if not row:
            raise ValueError("No checkpoint")
        state = json.loads(row[0])
        contract = self.effective_contract(state["project_id"])
        return {**state, "contract_version": contract.version,
                "contract": contract.model_dump(mode="json"), "artifacts": self.sections(contract.project_id),
                "handoffs": [h.model_dump(mode="json") for h in self.handoffs(session_id)]}

    def record_inference(self, project, session_id, action_id, calls):
        """Persist provider attribution without credentials or raw prompt/output."""
        fields = ("provider", "model", "agent", "started_at", "attempt", "schema_valid",
                  "elapsed_seconds", "error_kind", "http_status", "fallback_from", "fallback_reason")
        with self._transaction():
            self._event(project, "INFERENCE_COMPLETED", {
                "session_id": session_id, "action_id": action_id,
                "attempts": [{key: call[key] for key in fields if key in call} for call in calls]})

    def timeline(self, project):
        return [{"id": i, "kind": kind, "body": json.loads(body)} for i, kind, body in
                self.db.execute("SELECT id,kind,body FROM events WHERE project=? ORDER BY id", (project,))]

    def _event(self, project, kind, body):
        self.db.execute("INSERT INTO events(project,kind,body) VALUES(?,?,?)", (project,kind,json.dumps(body)))

    def _transaction(self):
        from contextlib import contextmanager
        @contextmanager
        def transaction():
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        return transaction()
