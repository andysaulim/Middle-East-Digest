"""Assert this edition records what it spends.

Recording spend has three parts and any one can lapse without a symptom: a
per-call ledger, a write of that ledger into metrics.jsonl, and a workflow step
that commits the file. The Japan edition had none of the three for months; the
Korea edition had the first two while its file lived only in an Actions cache
that GitHub evicts after seven days, with .gitignore silently defeating the
commit step that named it. Neither surfaced as a failure, because a missing
cost record looks exactly like a cheap week.

Run: python test_cost_recording.py
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main() -> int:
    problems: list[str] = []

    import digest
    src = inspect.getsource(digest)
    if "TOKEN_LEDGER" not in src:
        problems.append("digest keeps no per-call token ledger")
    if "def get_run_usage" not in src:
        problems.append("digest exposes no per-run usage total")
    if "MODEL_PRICING" not in src:
        problems.append("no price table, so the ledger cannot be costed")

    run_src = (HERE / "run.py").read_text(encoding="utf-8")
    if "METRICS_JSONL" not in run_src:
        problems.append("run.py writes no metrics line")
    if "finally:" not in run_src:
        problems.append("the metrics write is not in a finally block; a run that "
                        "spent tokens and then failed would record nothing")

    wf = ROOT / ".github" / "workflows" / "iran-brief.yml"
    if wf.exists() and "metrics.jsonl" not in wf.read_text(encoding="utf-8"):
        problems.append("the workflow never commits metrics.jsonl, so it lives "
                        "only on the runner")

    gi = ROOT / ".gitignore"
    if gi.exists() and any(l.strip() == "metrics.jsonl"
                           for l in gi.read_text(encoding="utf-8").splitlines()):
        problems.append("metrics.jsonl is gitignored, which silently defeats the "
                        "commit step")

    # The ledger must actually price, not merely exist.
    try:
        digest.TOKEN_LEDGER.clear()
        digest.TOKEN_LEDGER.append({"model": "claude-opus-4-8", "input": 1_000_000,
                                    "output": 0, "cache_write": 0, "cache_read": 0})
        if abs(digest.run_cost() - 5.0) > 0.01:
            problems.append(f"pricing is wrong: 1M Opus input priced at {digest.run_cost()}")
        digest.TOKEN_LEDGER.clear()
    except Exception as e:                                      # noqa: BLE001
        problems.append(f"pricing could not be exercised: {e}")

    for p in problems:
        print(f"  FAIL  {p}")
    if not problems:
        print("  OK    API cost is recorded, priced and committed")
    print(f"\n{'FAILED' if problems else 'PASSED'}: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    raise SystemExit(main())
