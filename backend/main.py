"""Local application API. Engine integration contract is documented in shared/ENGINE.md."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
import json
import os
import sqlite3
from backend.inference import configuration, create_client, public_attempts, EngineUnavailable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get('TETHER_DB', str(ROOT / 'backend/data/tether.sqlite3')))
if not DB.is_absolute():
    DB = ROOT / DB
DB.parent.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='Tether API', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000', 'http://127.0.0.1:3000'], allow_methods=['*'], allow_headers=['*'])


@contextmanager
def database():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA foreign_keys=ON')
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


with database() as con:
    con.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS contracts(project_id TEXT REFERENCES projects(id), version INTEGER, body TEXT, PRIMARY KEY(project_id,version));
    CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), status TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), session_id TEXT REFERENCES sessions(id), body TEXT, decision TEXT, reason TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS artifacts(action_id TEXT PRIMARY KEY REFERENCES actions(id), project_id TEXT REFERENCES projects(id), body TEXT);
    CREATE TABLE IF NOT EXISTS changes(id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), base_version INTEGER, topic TEXT, status TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT REFERENCES projects(id), kind TEXT, message TEXT, created_at TEXT);
    ''')
    if 'body' not in {r['name'] for r in con.execute('PRAGMA table_info(events)')}:
        con.execute('ALTER TABLE events ADD COLUMN body TEXT')
    # A restarted single-process backend cannot still own these in-flight calls.
    con.execute("UPDATE sessions SET status='FAILED' WHERE status IN ('PLANNING','VALIDATING')")


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return prefix + '-' + uuid4().hex[:12]


def event(con, project, kind, message, body=None):
    con.execute('INSERT INTO events(project_id,kind,message,created_at,body) VALUES(?,?,?,?,?)', (project, kind, message, now(), json.dumps(body) if body is not None else None))


def record_inference(project, session_id, action_id, calls):
    body = {'session_id': session_id, 'action_id': action_id, 'attempts': public_attempts(calls)}
    with database() as con:
        event(con, project, 'INFERENCE_COMPLETED', 'Inference attempts ended; validation and execution are separate outcomes', body)


def contract(con, project):
    row = con.execute('SELECT body FROM contracts WHERE project_id=? ORDER BY version DESC LIMIT 1', (project,)).fetchone()
    if not row:
        raise HTTPException(404, 'Project not found')
    return json.loads(row['body'])


class CreateProject(BaseModel):
    name: str = Field(default='Startup cloud comparison', min_length=1, max_length=120)
    objective: str = Field(default='Compare AWS, Azure, and Google Cloud for a startup. Prioritize cost and deployment simplicity.', min_length=10, max_length=2000)


class ChangeRequest(BaseModel):
    topic: Literal['SERVERLESS'] = 'SERVERLESS'


class Decision(BaseModel):
    decision: Literal['APPROVE', 'REJECT']


class Proposal(BaseModel):
    contract_version: int
    milestone_id: str
    topic: str
    section_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=15000)
    reference_ids_used: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=2000)


@app.get('/api/health')
def health():
    return {'status': 'ok', **configuration(), 'engine_available': (ROOT / 'engine/llm_client.py').exists()}


@app.get('/api/projects')
def projects():
    with database() as con:
        return [dict(r) for r in con.execute('SELECT * FROM projects ORDER BY created_at DESC')]


@app.post('/api/projects', status_code=201)
def create_project(body: CreateProject):
    project = uid('P')
    topics = ['COST', 'DEPLOYMENT', 'COMPARISON', 'RECOMMENDATION']
    titles = ['Research costs', 'Compare deployment simplicity', 'Create comparison table', 'Produce final recommendation']
    goal = {'project_id': project, 'version': 1, 'objective': body.objective,
            'constraints': [{'id': 'C1', 'type': 'SOURCE_RESTRICTION', 'value': 'provided_fixture_only', 'severity': 'HARD'}, {'id': 'C2', 'type': 'NO_UNAUTHORIZED_SCOPE', 'value': True, 'severity': 'HARD'}],
            'approved_topics': topics, 'milestones': [{'id': f'M{i+1}', 'title': title, 'allowed_topics': [topics[i]]} for i, title in enumerate(titles)]}
    with database() as con:
        con.execute('INSERT INTO projects VALUES(?,?,?)', (project, body.name, now()))
        con.execute('INSERT INTO contracts VALUES(?,?,?)', (project, 1, json.dumps(goal)))
        event(con, project, 'CONTRACT', 'Goal contract v1 approved and persisted')
    return {'id': project}


@app.get('/api/projects/{project}')
def get_project(project: str):
    with database() as con:
        goal = contract(con, project)
        meta = dict(con.execute('SELECT * FROM projects WHERE id=?', (project,)).fetchone())
        artifacts = [json.loads(r['body']) for r in con.execute('SELECT body FROM artifacts WHERE project_id=?', (project,))]
        completed = {a['milestone_id'] for a in artifacts}
        for m in goal['milestones']:
            m['status'] = 'COMPLETED' if m['id'] in completed else 'PENDING'
        pending = next((m for m in goal['milestones'] if m['status'] == 'PENDING'), None)
        if pending:
            pending['status'] = 'ACTIVE'
        inference = {}
        for r in con.execute("SELECT body FROM events WHERE project_id=? AND kind='INFERENCE_COMPLETED' ORDER BY id", (project,)):
            if r['body']:
                telemetry = json.loads(r['body'])
                inference[telemetry['action_id']] = telemetry
        return {**meta, 'contract': goal, 'inference': list(inference.values()), 'sessions': [dict(r) for r in con.execute('SELECT * FROM sessions WHERE project_id=? ORDER BY created_at DESC', (project,))],
                'actions': [{**dict(r), 'body': json.loads(r['body']), 'inference': inference.get(r['id'])} for r in con.execute('SELECT * FROM actions WHERE project_id=? ORDER BY created_at DESC', (project,))],
                'artifacts': artifacts, 'changes': [dict(r) for r in con.execute('SELECT * FROM changes WHERE project_id=? ORDER BY created_at DESC', (project,))]}


@app.get('/api/projects/{project}/contracts')
def contracts(project: str):
    with database() as con:
        contract(con, project)
        return [json.loads(r['body']) for r in con.execute('SELECT body FROM contracts WHERE project_id=? ORDER BY version DESC', (project,))]


@app.post('/api/projects/{project}/sessions', status_code=201)
def start_session(project: str):
    with database() as con:
        goal = contract(con, project)
        active = con.execute("SELECT id FROM sessions WHERE project_id=? AND status IN ('PLANNING','VALIDATING','AWAITING_REVIEW')", (project,)).fetchone()
        if active:
            raise HTTPException(409, 'A session is already active')
        session = uid('S')
        con.execute('INSERT INTO sessions VALUES(?,?,?,?)', (session, project, 'IDLE', now()))
        event(con, project, 'RECOVERY', f'Session restored from durable state using contract v{goal["version"]}')
        return {'id': session, 'status': 'IDLE'}


@app.get('/api/sessions/{session}')
def get_session(session: str):
    with database() as con:
        row = con.execute('SELECT * FROM sessions WHERE id=?', (session,)).fetchone()
        if not row:
            raise HTTPException(404, 'Session not found')
        return dict(row)


@app.post('/api/sessions/{session}/step')
def step(session: str):
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM sessions WHERE id=?', (session,)).fetchone()
        if not row:
            raise HTTPException(404, 'Session not found')
        project = row['project_id']
        if con.execute("SELECT 1 FROM sessions WHERE project_id=? AND status IN ('PLANNING','VALIDATING','AWAITING_REVIEW')", (project,)).fetchone():
            raise HTTPException(409, 'A step or review is already pending')
        goal = contract(con, project)
        done = {json.loads(r['body'])['milestone_id'] for r in con.execute('SELECT body FROM artifacts WHERE project_id=?', (project,))}
        milestone = next((m for m in goal['milestones'] if m['id'] not in done), None)
        if not milestone:
            con.execute('UPDATE sessions SET status=? WHERE id=?', ('COMPLETED', session))
            return {'status': 'COMPLETED'}
        con.execute('UPDATE sessions SET status=? WHERE id=?', ('PLANNING', session))
        event(con, project, 'PLANNING', f'Inference requested for {milestone["title"]}')
        feedback = [dict(r) for r in con.execute('SELECT decision,reason FROM actions WHERE project_id=? ORDER BY created_at DESC LIMIT 3', (project,))]
    snapshot = json.loads((ROOT / 'scenarios/cloud_snapshot.json').read_text())
    prompt = json.dumps({'contract': goal, 'active_milestone': milestone, 'snapshot': snapshot, 'previous_validation_feedback': feedback})
    action = uid('A')
    client = None
    try:
        client = create_client()
        proposal = client.generate(Proposal, 'Draft a report section supporting the active milestone. Use supplied synthetic evidence only. All numerical values must come from source records. Include SYNTHETIC_DEMONSTRATION in content.', prompt)
        proposal = Proposal.model_validate(proposal.model_dump())
    except Exception as exc:
        if client is not None:
            record_inference(project, session, action, client.calls)
        with database() as con:
            con.execute('UPDATE sessions SET status=? WHERE id=?', ('FAILED', session))
            event(con, project, 'FAILED', 'Inference failed; no report changes committed', {'session_id': session, 'action_id': action})
        detail = str(exc) if isinstance(exc, EngineUnavailable) else 'Inference failed. Inspect attempt telemetry and backend provider configuration. No report changes committed.'
        raise HTTPException(503, detail) from exc
    record_inference(project, session, action, client.calls)
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        latest = contract(con, project)
        reasons = []
        if proposal.contract_version != latest['version']:
            reasons.append('Stale contract version')
        if proposal.milestone_id != milestone['id'] or proposal.topic not in milestone['allowed_topics']:
            reasons.append('Milestone or topic is not authorized')
        if not set(proposal.reference_ids_used) <= {r['id'] for r in snapshot['records']}:
            reasons.append('Unknown source reference')
        if 'SYNTHETIC_DEMONSTRATION' not in proposal.content:
            reasons.append('Synthetic evidence label missing')
        decision = 'BLOCK' if reasons else 'REVIEW'
        reason = '; '.join(reasons) if reasons else 'Schema, version, milestone and reference checks passed. Human review required until content/evidence validation is integrated.'
        con.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?)', (action, project, session, proposal.model_dump_json(), decision, reason, now()))
        con.execute('UPDATE sessions SET status=? WHERE id=?', ('BLOCKED' if reasons else 'AWAITING_REVIEW', session))
        event(con, project, decision, reason)
        return {'action_id': action, 'decision': decision, 'reason': reason}


@app.post('/api/actions/{action}/decision')
def decide_action(action: str, body: Decision):
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM actions WHERE id=?', (action,)).fetchone()
        if not row:
            raise HTTPException(404, 'Action not found')
        if row['decision'] != 'REVIEW':
            raise HTTPException(409, 'Only pending review actions can be resolved')
        proposal = json.loads(row['body'])
        if proposal['contract_version'] != contract(con, row['project_id'])['version']:
            raise HTTPException(409, 'Contract changed; generate a new proposal')
        approved = body.decision == 'APPROVE'
        if approved:
            con.execute('INSERT INTO artifacts VALUES(?,?,?)', (action, row['project_id'], row['body']))
        con.execute('UPDATE actions SET decision=?,reason=? WHERE id=?', ('ALLOW' if approved else 'BLOCK', 'User ' + body.decision.lower(), action))
        con.execute('UPDATE sessions SET status=? WHERE id=?', ('IDLE', row['session_id']))
        event(con, row['project_id'], 'COMMIT' if approved else 'BLOCK', f'User {body.decision.lower()} action {action}')
        return {'status': 'COMMITTED' if approved else 'BLOCKED'}


@app.post('/api/projects/{project}/changes', status_code=201)
def propose_change(project: str, body: ChangeRequest):
    with database() as con:
        goal = contract(con, project)
        if body.topic in goal['approved_topics']:
            raise HTTPException(409, 'Topic already approved')
        if con.execute("SELECT 1 FROM changes WHERE project_id=? AND status='PENDING'", (project,)).fetchone():
            raise HTTPException(409, 'Resolve the pending change first')
        change = uid('C')
        con.execute('INSERT INTO changes VALUES(?,?,?,?,?,?)', (change, project, goal['version'], body.topic, 'PENDING', now()))
        event(con, project, 'CHANGE', 'Serverless scope extension proposed; approval required')
        return {'id': change}


@app.post('/api/changes/{change}/decision')
def decide_change(change: str, body: Decision):
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM changes WHERE id=?', (change,)).fetchone()
        if not row:
            raise HTTPException(404, 'Change not found')
        if row['status'] != 'PENDING':
            raise HTTPException(409, 'Change already resolved')
        goal = contract(con, row['project_id'])
        if goal['version'] != row['base_version']:
            raise HTTPException(409, 'Change is based on a stale contract')
        if con.execute("SELECT 1 FROM sessions WHERE project_id=? AND status IN ('PLANNING','VALIDATING','AWAITING_REVIEW')", (row['project_id'],)).fetchone():
            raise HTTPException(409, 'Finish the active step or review before changing the contract')
        if body.decision == 'APPROVE':
            goal['version'] += 1
            goal['approved_topics'].append(row['topic'])
            goal['milestones'].append({'id': 'M5', 'title': 'Compare serverless options', 'allowed_topics': ['SERVERLESS']})
            con.execute('INSERT INTO contracts VALUES(?,?,?)', (row['project_id'], goal['version'], json.dumps(goal)))
        con.execute('UPDATE changes SET status=? WHERE id=?', (body.decision, change))
        event(con, row['project_id'], 'CONTRACT', f'Goal change {body.decision.lower()}; active contract v{goal["version"]}')
        return {'version': goal['version']}


@app.get('/api/projects/{project}/timeline')
def timeline(project: str):
    with database() as con:
        contract(con, project)
        return [{**dict(r), 'body': json.loads(r['body']) if r['body'] else None} for r in con.execute('SELECT * FROM events WHERE project_id=? ORDER BY id DESC', (project,))]


@app.get('/api/projects/{project}/report')
def report(project: str):
    return {'sections': get_project(project)['artifacts'], 'label': 'SYNTHETIC_DEMONSTRATION'}


@app.get('/api/projects/{project}/metrics')
def metrics(project: str):
    get_project(project)
    return {'runs': [], 'message': 'No evaluation runs recorded. Engine evaluator integration pending.'}


@app.get('/api/sessions/{session}/handoffs')
def handoffs(session: str):
    get_session(session)
    return {'handoffs': [], 'mode': 'SINGLE_AGENT', 'message': 'Specialist handoff integration pending.'}


@app.post('/api/projects/{project}/recover')
def recover(project: str):
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        contract(con, project)
        if con.execute("SELECT 1 FROM sessions WHERE project_id=? AND status IN ('PLANNING','VALIDATING')", (project,)).fetchone():
            raise HTTPException(409, 'A model request is still running')
        event(con, project, 'RECOVERY', 'Durable project state restored; committed artifacts preserved')
    return get_project(project)
