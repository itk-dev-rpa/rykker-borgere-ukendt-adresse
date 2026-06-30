"""This module is the primary module of the robot framework. It collects the functionality of the rest of the framework."""

# This module is not meant to exist next to queue_framework.py in production:
# pylint: disable=duplicate-code

import json
import sys
import os

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection

from robot_framework import initialize
from robot_framework import reset
from robot_framework.exceptions import BusinessError, handle_error, log_exception
from robot_framework import process
from robot_framework import config


def _parse_limit(process_arguments: str | None, orchestrator_connection: OrchestratorConnection) -> int | None:
    """Read an optional positive 'limit' from the OO process arguments JSON.

    The process arguments are a free-form string from OpenOrchestrator. When they contain
    a JSON object with a positive integer "limit", that caps how many citizens are processed
    this run. Empty, missing, or invalid input returns None (process all) and is logged.
    """
    if not process_arguments or not process_arguments.strip():
        return None
    try:
        limit = json.loads(process_arguments).get("limit")
    except (ValueError, AttributeError):
        orchestrator_connection.log_info(f"Could not parse process arguments as JSON: {process_arguments!r}")
        return None
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        return limit
    if limit is not None:
        orchestrator_connection.log_info(f"Invalid 'limit' in process arguments: {limit!r} (ignored)")
    return None


def main():
    """The entry point for the framework. Should be called as the first thing when running the robot."""
    orchestrator_connection = OrchestratorConnection.create_connection_from_args()
    sys.excepthook = log_exception(orchestrator_connection)

    orchestrator_connection.log_trace("Robot Framework started.")
    initialize.initialize(orchestrator_connection)

    limit = _parse_limit(orchestrator_connection.process_arguments, orchestrator_connection)

    # Determine sink for this run based on env/config (env has priority)
    dry_run_env = os.getenv("DRY_RUN")
    dry_run = (dry_run_env.lower() == "true") if isinstance(dry_run_env, str) else bool(getattr(config, "DRY_RUN", False))

    # Build an action sink when in dry-run; None (process builds RealActionsSink) otherwise
    action_sink = initialize.activate_dryrun(orchestrator_connection) if dry_run else None

    error_count = 0
    for _ in range(config.MAX_RETRY_COUNT):
        try:
            reset.reset(orchestrator_connection)
            process.process(orchestrator_connection, action_sink=action_sink, limit=limit)
            break

        # If any business rules are broken the robot should stop entirely.
        except BusinessError as error:
            handle_error("Business Error", error, None, orchestrator_connection)
            break

        # We actually want to catch all exceptions possible here.
        # pylint: disable-next = broad-exception-caught
        except Exception as error:
            error_count += 1
            handle_error(f"Process Error #{error_count}", error, None, orchestrator_connection)

    reset.clean_up(orchestrator_connection)
    reset.close_all(orchestrator_connection)
    reset.kill_all(orchestrator_connection)

    if config.FAIL_ROBOT_ON_TOO_MANY_ERRORS and error_count == config.MAX_RETRY_COUNT:
        raise RuntimeError("Process failed too many times.")
