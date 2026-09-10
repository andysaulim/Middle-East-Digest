"""
run.py — Iran War Update, orchestrator

Runs the full pipeline in order: collect -> digest -> render -> deliver.
This is the entry point the GitHub Actions cron calls once a day.

Local dry run (collect + render only, no API key needed):
    python run.py --no-digest
Full run:
    python run.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import collect
import render
import deliver

# One JSON line per run: tokens, cost, whether it delivered. Committed by the
# workflow, so the spend history outlives job logs, which expire.
METRICS_JSONL = Path(__file__).resolve().parent / "metrics.jsonl"


def _record_metrics(sent: bool) -> None:
    """Append this run's cost line. Never fatal — the brief has already gone."""
    try:
        import digest
        usage = digest.get_run_usage()
        row = {
            "date": datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d"),
            "run_at": datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds"),
            "sent": bool(sent),
            **usage,
        }
        with open(METRICS_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if usage["api_calls"]:
            print(f"  [cost] ${usage['est_cost_usd']:.2f} this run "
                  f"({usage['api_calls']} calls, {usage['input_tokens']:,} in / "
                  f"{usage['output_tokens']:,} out)")
    except Exception as e:                                      # noqa: BLE001
        print(f"  [cost] metrics not recorded (non-fatal): {e}")


def main():
    no_digest = "--no-digest" in sys.argv

    collect.collect()

    if no_digest:
        print("\n--no-digest: skipping the Claude formatting step.")
        return

    import digest  # imported here so a dry run needs no anthropic install
    delivered = False
    try:
        md_path = digest.build_brief()
        html_path = render.render(md_path)
        deliver.deliver(html_path)
        delivered = True
    finally:
        # In the finally block on purpose: a run that spent tokens and then
        # failed to deliver is exactly the run whose cost you want recorded.
        _record_metrics(delivered)


if __name__ == "__main__":
    main()
