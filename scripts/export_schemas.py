"""Regenerate candidate wire contracts after an agreed schema change."""
import json
from pathlib import Path
from engine.schemas import GoalContract, AgentAction, AgentHandoff, ValidationResult, StepResult, GoalChange, HandoffResult, WorkflowResult

def main():
    target = Path(__file__).resolve().parents[1] / 'shared/contracts'
    target.mkdir(parents=True, exist_ok=True)
    for schema in (GoalContract, AgentAction, AgentHandoff, ValidationResult, StepResult, GoalChange, HandoffResult, WorkflowResult):
        (target / f'{schema.__name__}.schema.json').write_text(
            json.dumps(schema.model_json_schema(), indent=2) + '\n')

if __name__ == '__main__':
    main()
