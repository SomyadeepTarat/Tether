"""Lifecycle persistence shared by the reference executor and future backend adapter."""
import json
from engine.goal_evolution import evolve_contract
from engine.handoff import validate_handoff
from engine.schemas import GoalChange, GoalContract, AgentHandoff, HandoffResult


class LifecycleStore:
    def effective_contract(self, project):
        """Approved snapshot plus mutable execution status; history stays immutable."""
        contract = self.current_contract(project)
        statuses = dict(self.db.execute('SELECT milestone,status FROM milestone_state WHERE project=?', (project,)))
        return GoalContract.model_validate({**contract.model_dump(mode='json'), 'milestones': [
            {**m.model_dump(mode='json'), 'status': statuses.get(m.id, m.status)} for m in contract.milestones]})

    def contracts(self, project):
        return [GoalContract.model_validate_json(r[0]) for r in self.db.execute(
            'SELECT body FROM contracts WHERE project=? ORDER BY version', (project,))]

    def propose_goal_change(self, change: GoalChange):
        with self._transaction():
            row = self.db.execute('SELECT body FROM changes WHERE id=?', (change.change_id,)).fetchone()
            if row:
                if GoalChange.model_validate_json(row[0]) != change:
                    raise ValueError('Change key reused for different content')
                return self.goal_change(change.change_id)
            evolve_contract(self.current_contract(change.project_id), change)
            self.db.execute('INSERT INTO changes VALUES(?,?,?,?,?)',
                            (change.change_id, change.project_id, change.model_dump_json(), 'PENDING', None))
            self._event(change.project_id, 'GOAL_CHANGE_PROPOSED', change.model_dump(mode='json'))
            return self.goal_change(change.change_id)

    def goal_change(self, change_id):
        row = self.db.execute('SELECT body,status,actor FROM changes WHERE id=?', (change_id,)).fetchone()
        if not row:
            raise ValueError('Unknown goal change')
        return {'change': json.loads(row[0]), 'status': row[1], 'decided_by': row[2]}

    def decide_goal_change(self, change_id, *, approve: bool, actor: str):
        """Only the trusted backend calls this after authenticating a user decision."""
        if not actor.strip():
            raise ValueError('Authenticated decision actor is required')
        with self._transaction():
            saved = self.goal_change(change_id)
            target = 'APPROVED' if approve else 'REJECTED'
            if saved['status'] != 'PENDING':
                if saved['status'] != target:
                    raise ValueError('Goal change decision is final')
                return saved
            change = GoalChange.model_validate(saved['change'])
            if approve:
                # Recheck base version under the write lock: competing approvals
                # cannot both create the same successor or overwrite constraints.
                updated = evolve_contract(self.current_contract(change.project_id), change)
                self.db.execute('INSERT INTO contracts VALUES(?,?,?)',
                                (updated.project_id, updated.version, updated.model_dump_json()))
                prior = self.effective_contract(change.project_id)
                has_active = any(m.status == 'ACTIVE' for m in prior.milestones)
                for milestone in change.added_milestones:
                    status = 'PENDING' if has_active else 'ACTIVE'
                    has_active = True
                    self.db.execute('INSERT INTO milestone_state VALUES(?,?,?)',
                                    (change.project_id, milestone.id, status))
            self.db.execute('UPDATE changes SET status=?,actor=? WHERE id=?', (target, actor, change_id))
            self._event(change.project_id, 'GOAL_CHANGE_' + target,
                        {'change_id': change_id, 'actor': actor, 'base_version': change.base_version,
                         'approved_version': change.base_version + 1 if approve else None})
            return self.goal_change(change_id)

    def complete_milestone(self, project, milestone_id, *, actor: str):
        """Explicit application/user confirmation, never a model's completion claim."""
        if not actor.strip():
            raise ValueError('Authenticated completion actor is required')
        with self._transaction():
            contract = self.effective_contract(project)
            milestone = next((m for m in contract.milestones if m.id == milestone_id), None)
            if not milestone:
                raise ValueError('Unknown milestone')
            if milestone.status == 'COMPLETED':
                return contract
            if milestone.status != 'ACTIVE':
                raise ValueError('Only the active milestone can complete')
            rows = self.db.execute('SELECT a.body,a.result FROM actions a JOIN artifacts f ON f.action_id=a.id AND f.project=a.project WHERE a.project=?', (project,)).fetchall()
            linked = [json.loads(body)['action_id'] for body, result in rows
                      if json.loads(body)['milestone_id'] == milestone_id and json.loads(result)['committed']]
            if not linked:
                raise ValueError('Milestone has no committed supporting artifact')
            self.db.execute('INSERT INTO milestone_state VALUES(?,?,?) ON CONFLICT(project,milestone) DO UPDATE SET status=excluded.status',
                            (project, milestone_id, 'COMPLETED'))
            next_milestone = next((m for m in contract.milestones if m.status == 'PENDING'), None)
            if next_milestone:
                self.db.execute('INSERT INTO milestone_state VALUES(?,?,?) ON CONFLICT(project,milestone) DO UPDATE SET status=excluded.status',
                                (project, next_milestone.id, 'ACTIVE'))
            self._event(project, 'MILESTONE_COMPLETED', {'milestone_id': milestone_id,
                        'actor': actor, 'supporting_actions': linked,
                        'next_milestone_id': next_milestone.id if next_milestone else None})
            return self.effective_contract(project)

    def handoff_result(self, handoff_id):
        row = self.db.execute('SELECT result FROM handoffs WHERE id=?', (handoff_id,)).fetchone()
        return HandoffResult.model_validate_json(row[0]) if row else None

    def save_handoff(self, handoff: AgentHandoff, references, *, action_id):
        with self._transaction():
            prior = self.handoff_result(handoff.handoff_id)
            if prior:
                if prior.handoff != handoff:
                    raise ValueError('Handoff key reused for different content')
                # Resumption must check the current approved version/progress.
                validation = validate_handoff(handoff, self.effective_contract(handoff.project_id),
                                               handoff.session_id, references)
                result = HandoffResult(handoff=handoff, validation=validation, replayed=True)
                if validation != prior.validation:
                    self.db.execute('UPDATE handoffs SET result=? WHERE id=?',
                                    (result.model_dump_json(), handoff.handoff_id))
                    row = self.db.execute('SELECT body FROM checkpoints WHERE session=?', (handoff.session_id,)).fetchone()
                    if row:
                        checkpoint = json.loads(row[0])
                        if checkpoint.get('pending_action_id') == action_id:
                            checkpoint['state'] = ('BLOCKED' if validation.decision == 'BLOCK' else
                                                   'AWAITING_REVIEW' if validation.decision == 'REVIEW' else 'HANDOFF')
                            self.db.execute('UPDATE checkpoints SET body=? WHERE session=?',
                                            (json.dumps(checkpoint), handoff.session_id))
                    self._event(handoff.project_id, 'HANDOFF_REVALIDATED', result.model_dump(mode='json'))
                return result
            session = self.db.execute('SELECT project FROM sessions WHERE id=?', (handoff.session_id,)).fetchone()
            if not session or session[0] != handoff.project_id:
                raise ValueError('Unknown handoff session or project mismatch')
            validation = validate_handoff(handoff, self.effective_contract(handoff.project_id),
                                           handoff.session_id, references)
            result = HandoffResult(handoff=handoff, validation=validation)
            self.db.execute('INSERT INTO handoffs VALUES(?,?,?,?)',
                            (handoff.handoff_id, handoff.project_id, handoff.session_id, result.model_dump_json()))
            checkpoint = {'project_id': handoff.project_id, 'session_id': handoff.session_id,
                          'contract_version': handoff.contract_version, 'handoff_id': handoff.handoff_id,
                          'pending_action_id': action_id,
                          'state': 'HANDOFF' if validation.decision == 'ALLOW' else
                                   'BLOCKED' if validation.decision == 'BLOCK' else 'AWAITING_REVIEW'}
            self.db.execute('INSERT INTO checkpoints VALUES(?,?) ON CONFLICT(session) DO UPDATE SET body=excluded.body',
                            (handoff.session_id, json.dumps(checkpoint)))
            self._event(handoff.project_id, 'HANDOFF_' + validation.decision, result.model_dump(mode='json'))
            return result

    def handoffs(self, session_id):
        return [HandoffResult.model_validate_json(row[0]) for row in self.db.execute(
            'SELECT result FROM handoffs WHERE session=? ORDER BY rowid', (session_id,))]
