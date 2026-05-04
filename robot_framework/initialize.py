"""This module defines any initial processes to run when the robot starts."""
import os
import json
from pathlib import Path

from dotenv import load_dotenv
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection

from robot_framework import config
from robot_framework.sinks import DryRunSink


def initialize(orchestrator_connection: OrchestratorConnection) -> None:
    """Do all custom startup initializations of the robot."""
    orchestrator_connection.log_trace("Initializing.")


def activate_dryrun(orchestrator_connection: OrchestratorConnection) -> DryRunSink:
    """Activate dry-run mode by loading optional simulated state and returning a DryRunSink."""
    orchestrator_connection.log_info("DRY-RUN MODE AKTIVERET - Ingen ændringer vil blive foretaget")

    try:
        load_dotenv()
    except Exception as e:  # pylint: disable=broad-exception-caught
        orchestrator_connection.log_error(f"load_dotenv() failed: {e}")

    mock_state = None
    try:
        env_path = os.getenv("DRY_RUN_STATE_FILE")
        state_path = env_path or getattr(config, "DRY_RUN_STATE_FILE", None)

        if state_path:
            p = Path(state_path)
            if not p.is_absolute():
                p = Path(__file__).parent / p
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    mock_state = json.load(f)
            else:
                orchestrator_connection.log_trace(f"Ingen dry-run state-fil fundet på: {p}")
    except Exception as e:  # pylint: disable=broad-exception-caught
        orchestrator_connection.log_error(f"Kunne ikke indlæse dry-run state-fil: {e}")
    return DryRunSink(mock_state)
