"""Run process.process() LIVE against a real OpenOrchestrator connection.

UNLIKE tests/dryrun_local.py, this uses the real action sink (RealActionsSink):
it WILL perform real side effects for every citizen it processes — send SMS,
deliver Digital Post, upload documents and write notes to Nova, and update the
OpenOrchestrator queue. Use it to step through the real code path with a
debugger against live data.

For safety it processes a small batch by default (--limit 1) using the same
batch-limit mechanism the robot exposes via OpenOrchestrator process arguments.
Raise the limit deliberately. --limit 0 removes the cap (process everyone) —
be careful when paused on a breakpoint, as nothing else stops letters going out.

Usage:
    python tests/live_local.py                # process 1 citizen (default)
    python tests/live_local.py --limit 5      # process up to 5 citizens
    python tests/live_local.py --limit 0      # process ALL citizens (no cap)

Required environment variables (typically loaded from a local .env file):
    OpenOrchestratorConnString
    OpenOrchestratorKey
"""
# This dev harness intentionally mirrors dryrun_local.py; ignore cross-file duplication.
# pylint: disable=duplicate-code
import argparse
import json

from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
from local_oo import build_local_connection

from robot_framework import process
from robot_framework.rykker_borgere import service_platform_functions
from robot_framework.sinks import RealActionsSink


def main() -> int:
    """Parse args, build a real OO connection + RealActionsSink, and run process() live."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Max citizens to process. 0 = no cap (process all). Default: 1.",
    )
    args = parser.parse_args()

    oc = build_local_connection("Rykker borgere ukendt adresse (LIVE-LOCAL)")
    if oc is None:
        return 1

    # Feed the cap through the same process-arguments channel the robot uses live.
    if args.limit:
        oc.process_arguments = json.dumps({"limit": args.limit})
    print(
        f"LIVE run: real side effects WILL be performed for up to "
        f"{'ALL' if not args.limit else args.limit} citizen(s).",
        flush=True,
    )

    # Build the real sink explicitly (mirrors process() internals) so we can enable
    # verbose console output while stepping through with a debugger.
    nova_connection = oc.get_credential("Nova API")
    nova_access = NovaAccess(nova_connection.username, nova_connection.password)
    kombit_access = service_platform_functions.get_kombit_access(oc)
    sink = RealActionsSink(orchestrator=oc, nova_access=nova_access, kombit_access=kombit_access)
    sink.verbose = True

    process.process(oc, action_sink=sink)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
