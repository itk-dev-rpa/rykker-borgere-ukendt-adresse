"""Run process.process() end-to-end against a real OpenOrchestrator
connection but with a DryRunSink, so no side effects (SMS, Digital Post,
Nova writes, queue updates) are performed.

Use this for local pre-deployment verification when you don't want to
trigger the robot through the OpenOrchestrator UI.

Usage:
    python tests/dryrun_local.py
    python tests/dryrun_local.py --state path/to/mock_state.json

Required environment variables (typically loaded from a local .env file):
    OpenOrchestratorConnString
    OpenOrchestratorKey

Note: dry-run still requires valid Nova and Kombit credentials in
OpenOrchestrator, since case lookups and registration checks are real.
Only the *write* operations are skipped.
"""
import argparse
import os

from local_oo import build_local_connection

from robot_framework import process
from robot_framework.initialize import activate_dryrun


def main() -> int:
    """Parse args, build a real OO connection + DryRunSink, and run process()."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        help="Path to a JSON file with simulated state (overrides DRY_RUN_STATE_FILE).",
    )
    args = parser.parse_args()

    oc = build_local_connection("Rykker borgere ukendt adresse (DRY-RUN)")
    if oc is None:
        return 1

    # Set after the connection is built (which loads .env) but before activate_dryrun
    # reads DRY_RUN_STATE_FILE, so an explicit --state wins over any .env value.
    if args.state:
        os.environ["DRY_RUN_STATE_FILE"] = args.state

    sink = activate_dryrun(oc)
    sink.verbose = True
    process.process(oc, action_sink=sink)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
