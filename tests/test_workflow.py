"""Transaction and authorization checks; no model or network required."""
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_root = Path(__file__).resolve().parents[1] / 'backend/data'
        test_root.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=test_root)
        os.environ['TETHER_DB'] = str(Path(cls.temp.name) / 'workflow.sqlite3')
        cls.api = importlib.import_module('backend.main')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.project = self.api.create_project(self.api.CreateProject())['id']
        self.session = self.api.start_session(self.project)['id']

    def action(self, decision='REVIEW', version=1):
        proposal = {'contract_version': version, 'milestone_id': 'M1', 'topic': 'COST', 'section_id': 'costs', 'content': 'SYNTHETIC_DEMONSTRATION', 'reference_ids_used': ['SNAPSHOT-AWS-COST'], 'rationale': 'Cost milestone'}
        action = self.api.uid('A')
        with self.api.database() as con:
            con.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?)', (action, self.project, self.session, json.dumps(proposal), decision, 'Test proposal', self.api.now()))
        return action

    def test_commit_persists_and_cannot_repeat(self):
        action = self.action()
        self.api.decide_action(action, self.api.Decision(decision='APPROVE'))
        state = self.api.get_project(self.project)
        self.assertEqual(len(state['artifacts']), 1)
        self.assertEqual(state['contract']['milestones'][0]['status'], 'COMPLETED')
        with self.assertRaises(self.api.HTTPException) as raised:
            self.api.decide_action(action, self.api.Decision(decision='APPROVE'))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(self.api.get_project(self.project)['artifacts']), 1)

    def test_hard_block_cannot_be_approved(self):
        with self.assertRaises(self.api.HTTPException):
            self.api.decide_action(self.action('BLOCK'), self.api.Decision(decision='APPROVE'))
        self.assertEqual(self.api.get_project(self.project)['artifacts'], [])

    def test_rejection_creates_no_artifact(self):
        self.api.decide_action(self.action(), self.api.Decision(decision='REJECT'))
        self.assertEqual(self.api.get_project(self.project)['artifacts'], [])

    def test_contract_change_preserves_version_one(self):
        change = self.api.propose_change(self.project, self.api.ChangeRequest())['id']
        self.api.decide_change(change, self.api.Decision(decision='APPROVE'))
        versions = self.api.contracts(self.project)
        self.assertEqual([c['version'] for c in versions], [2, 1])
        self.assertIn('SERVERLESS', versions[0]['approved_topics'])
        self.assertNotIn('SERVERLESS', versions[1]['approved_topics'])

    def test_stale_proposal_cannot_commit(self):
        action = self.action()
        change = self.api.propose_change(self.project, self.api.ChangeRequest())['id']
        self.api.decide_change(change, self.api.Decision(decision='APPROVE'))
        with self.assertRaises(self.api.HTTPException):
            self.api.decide_action(action, self.api.Decision(decision='APPROVE'))
        self.assertEqual(self.api.get_project(self.project)['artifacts'], [])

    def test_restart_reconciles_interrupted_session(self):
        with self.api.database() as con:
            con.execute("UPDATE sessions SET status='PLANNING' WHERE id=?", (self.session,))
        importlib.reload(self.api)
        self.assertEqual(self.api.get_session(self.session)['status'], 'FAILED')
        self.assertEqual(self.api.get_project(self.project)['contract']['version'], 1)

    def test_provider_attempts_persist_before_policy_block(self):
        api = self.api
        class Client:
            calls = [{'provider': 'ollama', 'model': 'qwen3:4b', 'attempt': 1, 'schema_valid': True, 'elapsed_seconds': .5, 'fallback_from': 'groq', 'fallback_reason': 'missing_key'}]
            def generate(self, schema, system, prompt):
                return schema(contract_version=1, milestone_id='M1', topic='SECURITY', section_id='security', content='SYNTHETIC_DEMONSTRATION', reference_ids_used=['SNAPSHOT-AWS-COST'], rationale='Off-scope model proposal')
        with patch.object(api, 'create_client', return_value=Client()) as factory:
            result = api.step(self.session)
        self.assertEqual(result['decision'], 'BLOCK')
        self.assertEqual(factory.call_count, 1)
        state = api.get_project(self.project)
        self.assertEqual(state['actions'][0]['inference']['attempts'][0]['provider'], 'ollama')
        timeline = list(reversed(api.timeline(self.project)))
        kinds = [e['kind'] for e in timeline]
        self.assertLess(kinds.index('INFERENCE_COMPLETED'), kinds.index('BLOCK'))
        importlib.reload(api)
        self.assertEqual(api.get_project(self.project)['actions'][0]['inference']['attempts'][0]['fallback_from'], 'groq')

    def test_inference_failure_is_failed_and_records_attempts(self):
        class Client:
            calls = [{'provider': 'groq', 'model': 'openai/gpt-oss-20b', 'error_kind': 'timeout', 'schema_valid': False}]
            def generate(self, *args):
                raise RuntimeError('Provider failed')
        with patch.object(self.api, 'create_client', return_value=Client()):
            with self.assertRaises(self.api.HTTPException) as raised:
                self.api.step(self.session)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(self.api.get_session(self.session)['status'], 'FAILED')
        self.assertEqual(self.api.get_project(self.project)['actions'], [])
        self.assertTrue(any(e['kind'] == 'INFERENCE_COMPLETED' for e in self.api.timeline(self.project)))

    def test_telemetry_excludes_secrets_and_prompts(self):
        from backend.inference import public_attempts
        with patch.dict(os.environ, {'GROQ_API_KEY': 'private-test-value'}):
            calls = public_attempts([{'provider': 'groq', 'api_key': 'private-test-value', 'prompt': 'sensitive objective', 'fallback_reason': 'private-test-value gsk_abcdef123'}])
        encoded = json.dumps(calls)
        self.assertNotIn('private-test-value', encoded)
        self.assertNotIn('gsk_abcdef123', encoded)
        self.assertNotIn('sensitive objective', encoded)

    def test_provider_configuration_defaults_and_offline(self):
        from backend.inference import configuration
        with patch.dict(os.environ, {'TETHER_PROVIDER': 'groq-only'}):
            self.assertFalse(configuration()['fallback_enabled'])
            self.assertTrue(configuration()['hosted_inputs'])
        with patch.dict(os.environ, {'TETHER_PROVIDER': 'ollama'}):
            self.assertFalse(configuration()['hosted_inputs'])


if __name__ == '__main__':
    unittest.main()
