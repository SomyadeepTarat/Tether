"""Benchmark real inference; use groq-only/ollama to compare providers fairly."""
import argparse
import json
import uuid
from pathlib import Path
from engine.llm_client import create_inference_client
from engine.schemas import Model

class Probe(Model):
    label: str
    value: int

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--provider", choices=["groq", "groq-only", "ollama"])
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    client = create_inference_client(args.provider)
    failures, runs = [], []
    import time
    for index in range(args.runs):
        start = time.perf_counter()
        call_start = len(client.calls)
        success = False
        try:
            answer = client.generate(Probe, "Return the requested JSON object exactly.",
                                     'Return label="SYNTHETIC_DEMONSTRATION", value=42.')
            success = answer.label == "SYNTHETIC_DEMONSTRATION" and answer.value == 42
            if not success:
                failures.append({"run": index, "error": "Incorrect probe content"})
        except Exception as exc:
            failures.append({"run": index, "error": str(exc)})
        calls = client.calls[call_start:]
        final = next((c for c in reversed(calls) if c["schema_valid"]), {})
        runs.append({"run": index, "success": success,
                     "elapsed_seconds": time.perf_counter() - start,
                     "actual_provider": final.get("provider"), "actual_model": final.get("model"),
                     "used_fallback": any("fallback_from" in c for c in calls)})
    running_models = None
    memory_probe_error = None
    if client.provider == "ollama":
        try:
            from urllib.request import urlopen
            with urlopen(client.base_url + "/api/ps", timeout=10) as response:
                running_models = json.load(response)
        except Exception as exc:
            memory_probe_error = str(exc)
    report = {"configured_provider": client.provider, "configured_model": client.model,
              "requested_runs": args.runs, "runs": runs, "calls": client.calls,
              "failures": failures, "running_models": running_models,
              "memory_probe_error": memory_probe_error,
              "limitations": "Short structured-output smoke benchmark, not an agent evaluation. Fallback runs are not Groq performance. Ollama allocation is not peak system RSS."}
    Path("runtime").mkdir(exist_ok=True)
    path = Path("runtime") / f"benchmark-{uuid.uuid4().hex}.json"
    path.write_text(json.dumps(report, indent=2))
    Path("runtime/benchmark-latest.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "calls"}, indent=2))
    if failures:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
