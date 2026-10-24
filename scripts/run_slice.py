"""Run a genuine provider-backed proposal; writes raw inference and persisted validation result."""
import argparse
import json
import os
import uuid
from pathlib import Path
from engine.executor import Store
from engine.llm_client import create_inference_client
from engine.orchestrator import run_step, run_specialist_step
from engine.schemas import GoalContract, Reference

ROOT = Path(__file__).resolve().parents[1]

def main():
    from engine.config import load_environment
    load_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["single", "specialists"], default="single")
    parser.add_argument("--provider", choices=["groq", "groq-only", "ollama"])
    parser.add_argument("--db", default=os.getenv("TETHER_DB", "runtime/tether.sqlite3"))
    parser.add_argument("--session", default="S-001")
    parser.add_argument("--action", default="A-001")
    args = parser.parse_args()
    contract = GoalContract.model_validate_json((ROOT / "scenarios/cloud_comparison.json").read_text())
    references = [Reference.model_validate(r) for r in json.loads((ROOT / "scenarios/cloud_snapshot.json").read_text())["references"]]
    store = Store(args.db)
    client = create_inference_client(args.provider)
    try:
        if not store.db.execute("SELECT 1 FROM contracts WHERE project=?", (contract.project_id,)).fetchone():
            store.create_goal_contract(contract)
        if not store.db.execute("SELECT 1 FROM sessions WHERE id=?", (args.session,)).fetchone():
            store.start_session(contract.project_id, args.session)
        runner = run_specialist_step if args.mode == "specialists" else run_step
        result = runner(store, client, contract.project_id, args.session, references, args.action)
        print(result.model_dump_json(indent=2))
    finally:
        Path("runtime").mkdir(exist_ok=True)
        if client.calls:
            log_path = Path("runtime") / f"inference-{uuid.uuid4().hex}.json"
            log_path.write_text(json.dumps(client.calls, indent=2))
            Path("runtime/inference.json").write_text(json.dumps(client.calls, indent=2))
        store.close()

if __name__ == "__main__":
    main()
