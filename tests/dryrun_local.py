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
import sys
from dotenv import load_dotenv

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection  # noqa: E402

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

    load_dotenv()

    if args.state:
        os.environ["DRY_RUN_STATE_FILE"] = args.state

    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    if not conn_string or not crypto_key:
        print(
            "ERROR: Set OpenOrchestratorConnString and OpenOrchestratorKey "
            "in the environment or a .env file in the project root.",
            file=sys.stderr,
        )
        return 1

    oc = OrchestratorConnection(
        "Rykker borgere ukendt adresse (DRY-RUN)",
        conn_string,
        crypto_key,
        "",
        "",
    )
    sink = activate_dryrun(oc)
    sink.verbose = True
    process.process(oc, action_sink=sink)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
