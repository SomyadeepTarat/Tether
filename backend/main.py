"""Local product API backed by the merged engine and its authoritative store."""
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4
import json
import os
import secrets
import sqlite3

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from backend.inference import configuration, create_client, inference_failure_message
from backend.config import load_backend_environment
from backend.store import AppStore, now, prepare_database
from engine.orchestrator import run_step, run_specialist_step
from engine.schemas import GoalChange, GoalContract, Milestone, Reference

ROOT = Path(__file__).resolve().parents[1]
load_backend_environment(ROOT)
OPERATOR_TOKEN = secrets.token_urlsafe(32)
ORIGINS = {'http://localhost:3000', 'http://127.0.0.1:3000', 'http://localhost:8000', 'http://127.0.0.1:8000', 'http://testserver'}


def db_path():
    path = Path(os.environ.get('TETHER_DB', str(ROOT / 'backend/data/tether.sqlite3')))
    return path if path.is_absolute() else ROOT / path


@contextmanager
def store():
    current = AppStore(db_path())
    try:
        yield current
    finally:
        current.close()


@asynccontextmanager
async def lifespan(app):
    prepare_database(db_path())
    with store() as current:
        current.import_legacy()
        with current._transaction():
            current.db.execute("UPDATE app_sessions SET status='FAILED' WHERE status IN ('PLANNING','VALIDATING','HANDOFF')")
    yield


app = FastAPI(title='Tether API', version='0.2.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(ORIGINS - {'http://testserver'}), allow_credentials=True, allow_methods=['GET','POST'], allow_headers=['Content-Type'])


@app.middleware('http')
async def local_operator(request: Request, call_next):
    # Loopback application: the backend grants a same-site HttpOnly operator session.
    # Actor identity is never supplied by agent output or request JSON.
    if request.method == 'POST':
        token = request.cookies.get('tether_operator', '')
        if not secrets.compare_digest(token, OPERATOR_TOKEN) or request.headers.get('origin') not in ORIGINS:
            return JSONResponse(status_code=403, content={'detail': 'Open or refresh the local workspace before making changes.'})
    return await call_next(request)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class CreateProject(Input):
    name: str = Field(default='Startup cloud comparison', min_length=1, max_length=120)
    objective: str = Field(default='Compare AWS, Azure, and Google Cloud for a startup. Prioritize cost and deployment simplicity.', min_length=10, max_length=2000)


class StartSession(Input):
    mode: Literal['single', 'specialists'] = 'single'


class StepRequest(Input):
    action_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,100}$')


class ChangeRequest(Input):
    topic: Literal['SERVERLESS'] = 'SERVERLESS'


class Decision(Input):
    decision: Literal['APPROVE', 'REJECT']


def uid(prefix):
    return prefix + '-' + uuid4().hex[:12]


def references():
    return [Reference.model_validate(r) for r in json.loads((ROOT / 'scenarios/cloud_snapshot.json').read_text(encoding='utf-8'))['references']]


def require_project(current, project):
    try:
        return current.effective_contract(project)
    except ValueError as exc:
        raise HTTPException(404, 'Project not found') from exc


def require_session(current, session):
    row = current.db.execute('SELECT id,project,status,created_at,pending_action,mode FROM app_sessions WHERE id=?', (session,)).fetchone()
    if not row:
        raise HTTPException(404, 'Session not found')
    return dict(zip(('id','project_id','status','created_at','pending_action','mode'), row))


def conflict(exc):
    raise HTTPException(409, str(exc)) from exc


def active_work(current, project):
    return current.db.execute("SELECT 1 FROM app_sessions WHERE project=? AND status IN ('PLANNING','VALIDATING','HANDOFF')", (project,)).fetchone()


def proposal_view(action):
    return {'contract_version': action.contract_version, 'milestone_id': action.milestone_id,
            'topic': action.topic, 'section_id': action.arguments.section_id, 'content': action.arguments.content,
            'reference_ids_used': action.declared_effects.reference_ids_used, 'rationale': action.rationale}


@app.get('/api/health')
def health(response: Response):
    response.set_cookie('tether_operator', OPERATOR_TOKEN, httponly=True, samesite='strict', path='/', max_age=86400)
    return {'status':'ok', **configuration(), 'engine_available':True, 'review_approval_available':False}


@app.get('/api/projects')
def projects():
    with store() as current:
        return [dict(zip(('id','name','created_at'), r)) for r in current.db.execute('SELECT id,name,created_at FROM app_projects ORDER BY created_at DESC')]


@app.post('/api/projects', status_code=201)
def create_project(body: CreateProject):
    project = uid('P')
    template = json.loads((ROOT / 'scenarios/cloud_comparison.json').read_text(encoding='utf-8'))
    goal = GoalContract.model_validate({**template, 'project_id':project, 'objective':body.objective})
    with store() as current:
        # Both approved goal and product metadata are persisted in one transaction.
        with current._transaction():
            current.db.execute('INSERT INTO contracts VALUES(?,?,?)', (project,1,goal.model_dump_json()))
            current.db.execute('INSERT INTO app_projects VALUES(?,?,?)', (project,body.name,now()))
            current._event(project,'CONTRACT_CREATED',goal.model_dump(mode='json'))
    return {'id':project}


def project_view(current, project):
    goal = require_project(current, project)
    meta = current.db.execute('SELECT name,created_at FROM app_projects WHERE id=?', (project,)).fetchone()
    timeline = current.timeline(project)
    inference = {}
    times = {}
    for e in timeline:
        if e['kind'] == 'INFERENCE_COMPLETED':
            body = e['body']
            key = body['action_id']
            if key not in inference:
                inference[key] = {'session_id':body['session_id'], 'action_id':key, 'attempts':[]}
            inference[key]['attempts'].extend(body['attempts'])
        body_action = e['body'].get('action')
        if body_action:
            times[body_action['action_id']] = e['body'].get('_recorded_at','')
    actions = []
    artifacts = []
    for (key,) in current.db.execute('SELECT id FROM actions WHERE project=? ORDER BY rowid DESC', (project,)):
        result = current.action_result(key)
        action = result.action
        resolution = current.db.execute('SELECT disposition FROM app_resolutions WHERE action_id=?', (key,)).fetchone()
        actions.append({'id':key, 'session_id':action.session_id, 'body':proposal_view(action), 'action':action.model_dump(mode='json'),
                        'validation':result.validation.model_dump(mode='json'), 'committed':result.committed,
                        'decision':result.validation.decision, 'reason':'; '.join(result.validation.reasons) or 'All mandatory checks passed',
                        'created_at':times.get(key,''), 'inference':inference.get(key), 'resolution':resolution[0] if resolution else None})
    for (key,) in current.db.execute('SELECT action_id FROM artifacts WHERE project=? ORDER BY section', (project,)):
        result = current.action_result(key)
        artifacts.append(proposal_view(result.action))
    sessions = [dict(zip(('id','project_id','status','created_at','pending_action','mode'), row)) for row in current.db.execute('SELECT id,project,status,created_at,pending_action,mode FROM app_sessions WHERE project=? ORDER BY created_at DESC', (project,))]
    changes = []
    for (key,) in current.db.execute('SELECT id FROM changes WHERE project=? ORDER BY rowid DESC', (project,)):
        saved = current.goal_change(key)
        change = saved['change']
        changes.append({'id':key,'topic':', '.join(change['added_topics']),'status':saved['status'], 'base_version':change['base_version']})
    return {'id':project, 'name':meta[0] if meta else project, 'created_at':meta[1] if meta else '',
            'contract':goal.model_dump(mode='json'), 'sessions':sessions,'actions':actions,'artifacts':artifacts,
            'changes':changes,'inference':list(inference.values()), 'legacy_archive_available':bool(current.archive(project)['contracts'])}


@app.get('/api/projects/{project}')
def get_project(project: str):
    with store() as current:
        return project_view(current,project)


@app.get('/api/projects/{project}/contracts')
def contracts(project: str):
    with store() as current:
        require_project(current,project)
        return [c.model_dump(mode='json') for c in reversed(current.contracts(project))]


@app.post('/api/projects/{project}/sessions', status_code=201)
def start_session(project: str, body: StartSession):
    with store() as current:
        require_project(current,project)
        if active_work(current,project):
            raise HTTPException(409,'A step is already running')
        session = uid('S')
        with current._transaction():
            current.db.execute('INSERT INTO sessions VALUES(?,?)',(session,project))
            current.db.execute('INSERT INTO checkpoints VALUES(?,?)',(session,json.dumps({'project_id':project,'session_id':session,'contract_version':current.current_contract(project).version,'state':'IDLE'})))
            current.db.execute('INSERT INTO app_sessions VALUES(?,?,?,?,?,?)',(session,project,'IDLE',now(),None,body.mode))
            current._event(project,'SESSION_STARTED',{'session_id':session,'mode':body.mode})
        return {'id':session,'status':'IDLE','mode':body.mode}


@app.get('/api/sessions/{session}')
def get_session(session: str):
    with store() as current:
        return {**require_session(current,session), 'checkpoint':current.restore_checkpoint(session)}


@app.post('/api/sessions/{session}/step')
def step(session: str, body: StepRequest):
    with store() as current:
        # Serialize project execution before opening any model request. No write
        # transaction remains open during network I/O. Run one API worker locally.
        with current._transaction():
            info = require_session(current,session)
            project = info['project_id']
            action_id = body.action_id or info['pending_action'] or uid('A')
            prior = current.action_result(action_id)
            if prior:
                if prior.action.session_id != session or prior.action.project_id != project:
                    raise HTTPException(409,'Action key belongs to another session')
                return {**prior.model_dump(mode='json'),'replayed':True}
            if active_work(current,project):
                raise HTTPException(409,'A step is already running')
            claim = current.db.execute('SELECT session,mode FROM app_requests WHERE id=?',(action_id,)).fetchone()
            if claim and claim != (session,info['mode']):
                raise HTTPException(409,'Action key belongs to another session or mode')
            current.db.execute('INSERT OR IGNORE INTO app_requests VALUES(?,?,?)',(action_id,session,info['mode']))
            if any(m.status == 'ACTIVE' for m in current.effective_contract(project).milestones) is False:
                raise HTTPException(409,'All milestones are complete')
            current.db.execute("UPDATE app_sessions SET status='PLANNING',pending_action=? WHERE id=?",(action_id,session))
            current._event(project,'PLANNING',{'session_id':session,'action_id':action_id,'mode':info['mode']})
        try:
            # Hosted research/handoff export has not been authorized for this UI.
            client = create_client('ollama' if info['mode'] == 'specialists' else None)
            runner = run_specialist_step if info['mode'] == 'specialists' else run_step
            result = runner(current,client,project,session,references(),action_id)
            final = result.step if info['mode'] == 'specialists' else result
            state = result.state if info['mode'] == 'specialists' else ('COMPLETED' if final.committed else 'BLOCKED' if final.validation.decision == 'BLOCK' else 'AWAITING_REVIEW')
            with current._transaction():
                current.db.execute('UPDATE app_sessions SET status=?,pending_action=? WHERE id=?',(state,None if final else action_id,session))
            return result.model_dump(mode='json')
        except Exception as exc:
            with current._transaction():
                current.db.execute("UPDATE app_sessions SET status='FAILED' WHERE id=?",(session,))
                current._event(project,'FAILED',{'session_id':session,'action_id':action_id,'message':'Inference or engine execution failed; no unvalidated artifact was committed'})
            raise HTTPException(503,inference_failure_message(exc,client if 'client' in locals() else None)) from exc


@app.post('/api/actions/{action}/decision')
def decide_action(action: str, body: Decision):
    with store() as current:
        result = current.action_result(action)
        if not result:
            raise HTTPException(404,'Action not found')
        if result.validation.decision != 'REVIEW':
            raise HTTPException(409,'Only pending REVIEW actions can be resolved')
        if body.decision == 'APPROVE':
            raise HTTPException(409,'Semantic review approval is not implemented in the current engine. No artifact was committed.')
        with current._transaction():
            current.db.execute("INSERT OR IGNORE INTO app_resolutions VALUES(?,'REJECTED')",(action,))
            current.db.execute("UPDATE app_sessions SET status='IDLE' WHERE id=?",(result.action.session_id,))
            current._event(result.action.project_id,'USER_REJECTED',{'action_id':action,'actor':'local-operator'})
        return {'status':'REJECTED'}


@app.post('/api/projects/{project}/milestones/{milestone}/complete')
def complete_milestone(project: str, milestone: str):
    with store() as current:
        require_project(current,project)
        if active_work(current,project):
            raise HTTPException(409,'Finish the running step first')
        try:
            return current.complete_milestone(project,milestone,actor='local-operator').model_dump(mode='json')
        except ValueError as exc:
            conflict(exc)


@app.post('/api/projects/{project}/changes', status_code=201)
def propose_change(project: str, body: ChangeRequest):
    with store() as current:
        goal = require_project(current,project)
        change = GoalChange(change_id=uid('C'),project_id=project,base_version=goal.version,added_topics=[body.topic],
                            added_milestones=[Milestone(id='M5',title='Compare serverless options',allowed_topics=[body.topic])],
                            rationale='User requested a serverless comparison')
        try:
            current.propose_goal_change(change)
        except ValueError as exc:
            conflict(exc)
        return {'id':change.change_id}


@app.post('/api/changes/{change}/decision')
def decide_change(change: str, body: Decision):
    with store() as current:
        try:
            saved = current.goal_change(change)
        except ValueError as exc:
            raise HTTPException(404,'Change not found') from exc
        if active_work(current,saved['change']['project_id']):
            raise HTTPException(409,'Finish the running step first')
        try:
            current.decide_goal_change(change,approve=body.decision == 'APPROVE',actor='local-operator')
        except ValueError as exc:
            conflict(exc)
        return {'version':current.current_contract(saved['change']['project_id']).version}


@app.get('/api/projects/{project}/timeline')
def timeline(project: str):
    with store() as current:
        require_project(current,project)
        return [{**e,'message':e['body'].get('message') or e['kind'].replace('_',' ').capitalize(), 'created_at':e['body'].get('_recorded_at','')} for e in reversed(current.timeline(project))]


@app.get('/api/projects/{project}/report')
def report(project: str):
    return {'sections':get_project(project)['artifacts'],'label':'SYNTHETIC_DEMONSTRATION'}


@app.get('/api/projects/{project}/metrics')
def metrics(project: str):
    get_project(project)
    return {'runs':[], 'message':'No independent evaluation runs recorded.'}


@app.get('/api/sessions/{session}/handoffs')
def handoffs(session: str):
    with store() as current:
        info = require_session(current,session)
        return {'handoffs':[h.model_dump(mode='json') for h in current.handoffs(session)],'mode':info['mode']}


@app.post('/api/projects/{project}/recover')
def recover(project: str):
    with store() as current:
        require_project(current,project)
        if active_work(current,project):
            raise HTTPException(409,'A model request is still running')
        with current._transaction():
            current._event(project,'RECOVERY',{'message':'Current contract, report and checkpoints restored without inference'})
        return project_view(current,project)


@app.get('/api/projects/{project}/archive')
def archive(project: str):
    with store() as current:
        require_project(current,project)
        return current.archive(project)
