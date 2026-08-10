"""
run.py — Iran War Update, orchestrator

Runs the full pipeline in order: collect -> digest -> render -> deliver.
This is the entry point the GitHub Actions cron calls once a day.

Local dry run (collect + render only, no API key needed):
    python run.py --no-digest
Full run:
    python run.py
"""

import sys

import collect
import render
import deliver


def main():
    no_digest = "--no-digest" in sys.argv

    collect.collect()

    if no_digest:
        print("\n--no-digest: skipping the Claude formatting step.")
        return

    import digest  # imported here so a dry run needs no anthropic install
    md_path = digest.build_brief()
    html_path = render.render(md_path)
    deliver.deliver(html_path)


if __name__ == "__main__":
    main()
