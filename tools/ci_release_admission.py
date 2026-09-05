#!/usr/bin/env python3
"""Select exact-commit full CI evidence for the release workflow."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from typing import Any

FULL_EVENTS = {"push", "workflow_dispatch"}
REQUIRED_GATE = "Required CI"


def eligible_run(run: Mapping[str, Any], sha: str) -> bool:
    """Return whether a workflow run is valid release evidence for ``sha``."""

    return (
        run.get("head_sha") == sha
        and run.get("head_branch") == "main"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("event") in FULL_EVENTS
    )


def select_run_id(runs: Iterable[Mapping[str, Any]], sha: str) -> int | None:
    """Select the newest eligible run, independently of API response ordering."""

    eligible = [run for run in runs if eligible_run(run, sha)]
    if not eligible:
        return None
    selected = max(
        eligible,
        key=lambda run: (int(run.get("run_number") or 0), int(run.get("id") or 0)),
    )
    run_id = selected.get("id")
    return int(run_id) if run_id is not None else None


def required_gate_succeeded(jobs: Iterable[Mapping[str, Any]]) -> bool:
    """Require the newest attempt of the stable aggregate gate to succeed."""

    gates = [job for job in jobs if job.get("name") == REQUIRED_GATE]
    if not gates:
        return False
    latest = max(
        gates,
        key=lambda job: (int(job.get("run_attempt") or 0), int(job.get("id") or 0)),
    )
    return latest.get("status") == "completed" and latest.get("conclusion") == "success"


def _object_list(payload: Any, key: str) -> list[Mapping[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ValueError(f"GitHub response does not contain a {key} list")
    values = payload[key]
    if not all(isinstance(value, dict) for value in values):
        raise ValueError(f"GitHub response contains a non-object in {key}")
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    select_parser = subparsers.add_parser("select-run")
    select_parser.add_argument("--sha", required=True)
    subparsers.add_parser("check-jobs")
    args = parser.parse_args()

    try:
        payload = json.load(sys.stdin)
        if args.command == "select-run":
            run_id = select_run_id(_object_list(payload, "workflow_runs"), args.sha)
            if run_id is None:
                print(f"No successful full main CI run exists for {args.sha}", file=sys.stderr)
                return 1
            print(run_id)
            return 0

        if not required_gate_succeeded(_object_list(payload, "jobs")):
            print("The newest Required CI aggregate attempt did not succeed", file=sys.stderr)
            return 1
        print("Required CI aggregate succeeded")
        return 0
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"Invalid GitHub Actions evidence: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
