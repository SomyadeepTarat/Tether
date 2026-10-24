"""Explicit human resolution of semantic uncertainty, never deterministic violations."""
import json
from engine.schemas import ValidationResult
from engine.validator import validate_action


class ReviewStore:
    def validate_current_action(self, action, references):
        owners = {}
        for section, body in self.db.execute(
            'SELECT f.section,a.body FROM artifacts f JOIN actions a ON a.id=f.action_id WHERE f.project=?',
            (action.project_id,)):
            owners[section] = json.loads(body)['milestone_id']
        validation = validate_action(action, self.effective_contract(action.project_id), action.session_id,
                                     references, set(self.sections(action.project_id)))
        if action.arguments.section_id in owners and owners[action.arguments.section_id] != action.milestone_id:
            return ValidationResult(decision='BLOCK', reasons=[*validation.reasons,
                'Section belongs to a different milestone'])
        return validation

    def action_review(self, action_id):
        row = self.db.execute('SELECT decision,actor,reason FROM action_reviews WHERE action_id=?', (action_id,)).fetchone()
        return dict(zip(('decision','actor','reason'),row)) if row else None

    def resolve_action(self, action_id, references, *, approve: bool, actor: str, reason: str = ''):
        """Trusted backend only: authenticate the human before invoking this method."""
        if not actor.strip():
            raise ValueError('Authenticated review actor is required')
        if approve and len(reason.strip()) < 10:
            raise ValueError('Explain why the claims and evidence are acceptable (at least 10 characters)')
        decision = 'APPROVED' if approve else 'REJECTED'
        with self._transaction():
            previous = self.action_review(action_id)
            if previous:
                if previous['decision'] != decision:
                    raise ValueError('Review decision is final')
                return previous
            result = self.action_result(action_id)
            if not result:
                raise ValueError('Unknown action')
            if result.validation.decision != 'REVIEW' or result.committed:
                raise ValueError('Only uncommitted REVIEW actions can be resolved')
            action = result.action
            if approve:
                validation = self.validate_current_action(action, references)
                if validation.decision == 'BLOCK':
                    raise ValueError('Current mandatory checks failed: ' + '; '.join(validation.reasons))
                base = self.db.execute('SELECT prior_action FROM action_bases WHERE action_id=?', (action_id,)).fetchone()
                current = self.db.execute('SELECT action_id FROM artifacts WHERE project=? AND section=?',
                                          (action.project_id,action.arguments.section_id)).fetchone()
                if base is None or base[0] != (current[0] if current else None):
                    raise ValueError('Report changed after this proposal; generate a fresh proposal')
                self.db.execute('INSERT INTO artifacts VALUES(?,?,?,?) ON CONFLICT(project,section) DO UPDATE SET content=excluded.content,action_id=excluded.action_id',
                                (action.project_id,action.arguments.section_id,action.arguments.content,action_id))
                # Preserve the original gateway REVIEW; the separate human decision
                # explains why this artifact was authorized, rather than rewriting history.
                self.db.execute('UPDATE actions SET result=? WHERE id=?',
                                (result.model_copy(update={'committed':True}).model_dump_json(),action_id))
            self.db.execute('INSERT INTO action_reviews VALUES(?,?,?,?)', (action_id,decision,actor,reason.strip()))
            row = self.db.execute('SELECT body FROM checkpoints WHERE session=?', (action.session_id,)).fetchone()
            if row:
                checkpoint = json.loads(row[0])
                if checkpoint.get('last_action_id') == action_id:
                    checkpoint['state'] = 'COMPLETED' if approve else 'IDLE'
                    self.db.execute('UPDATE checkpoints SET body=? WHERE session=?',
                                    (json.dumps(checkpoint),action.session_id))
            self._event(action.project_id,'USER_' + decision,{'action_id':action_id,'actor':actor,
                        'reason':reason.strip(),'contract_version':action.contract_version})
            return self.action_review(action_id)
