"""Shared bootstrap for the local dev run harnesses (dryrun_local.py, live_local.py).

Builds a real OpenOrchestrator connection from environment variables / a local
.env file. Kept out of the shipped robot_framework package because it is only
used for local debugging. Not collected by pytest (only test_*.py is).
"""
import os
import sys
from uuid import uuid4

from dotenv import load_dotenv

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection


def build_local_connection(process_name: str) -> OrchestratorConnection | None:
    """Load OO credentials from env/.env and build an OrchestratorConnection.

    Returns None (after printing guidance to stderr) when the required
    environment variables are missing, so callers can `return 1`.
    """
    load_dotenv()

    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    if not conn_string or not crypto_key:
        print(
            "ERROR: Set OpenOrchestratorConnString and OpenOrchestratorKey "
            "in the environment or a .env file in the project root.",
            file=sys.stderr,
        )
        return None

    return OrchestratorConnection(process_name, conn_string, crypto_key, "", "", uuid4())
