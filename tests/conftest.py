"""Pytest fixtures and helpers for testing `robot_framework.process`.

Notes
- Imports inside fixtures are intentional to keep patch scope local to tests.
- Fixtures provide deterministic time and in-memory mocks for external systems.
"""

# pylint: disable=import-outside-toplevel, redefined-outer-name, too-few-public-methods

import types
from datetime import datetime
import pytest


@pytest.fixture
def fixed_now():
    """Return a fixed timestamp used to make tests deterministic."""
    return datetime(2026, 4, 27, 12, 0, 0)


class FakeOrchestrator:
    """Minimal stand-in for `OrchestratorConnection` collecting log messages."""

    def __init__(self):
        self.infos = []
        self.errors = []
        self.traces = []
        self.process_name = "rykker-borgere-ukendt-adresse"

    def log_info(self, msg: str):
        """Record an info message."""
        self.infos.append(msg)

    def log_error(self, msg: str):
        """Record an error message."""
        self.errors.append(msg)

    def log_trace(self, msg: str):
        """Record a trace message."""
        self.traces.append(msg)


class FakeParty:
    """Simple CPR case party used by tests."""

    def __init__(self, identification: str = "0101011234", name: str = "Ada Lovelace"):
        self.identification = identification
        self.name = name
        # attribute checked in nova_functions.get_single_cpr_case_party
        self.identification_type = "CprNummer"


@pytest.fixture
def orchestrator():
    """Provide a fake orchestrator connection collecting logs."""
    return FakeOrchestrator()


@pytest.fixture
def fake_case():
    """Provide a minimal Nova case structure used by the process functions."""
    return {
        "common": {"uuid": "case-uuid-123"},
        "caseAttributes": {"userFriendlyCaseNumber": "CASE-0001"},
    }


@pytest.fixture
def fake_party():
    """Provide a CPR case party object."""
    return FakeParty()


@pytest.fixture
def tracker():
    """Return a fresh `DryRunSink` instance for each test."""
    from robot_framework.sinks import DryRunSink
    return DryRunSink(mock_state={})


@pytest.fixture(autouse=True)
def patch_datetime_now(monkeypatch, fixed_now):
    """Patch `datetime.now()` inside `robot_framework.process` to a fixed value."""
    from robot_framework import process

    # Monkeypatch the module attribute 'datetime' with a shim preserving fromisoformat
    class DTShim:
        """Minimal datetime shim exposing `now` and `fromisoformat` for monkeypatching in tests."""

        @staticmethod
        def now(tz=None):
            """Return fixed `datetime` for tests; respects optional timezone."""
            return fixed_now if tz is None else fixed_now.astimezone(tz)

        @staticmethod
        def fromisoformat(s):
            """Delegate to stdlib `datetime.fromisoformat`."""
            return datetime.fromisoformat(s)

    monkeypatch.setattr(process, "datetime", DTShim, raising=True)
    yield


@pytest.fixture(autouse=True)
def patch_external_functions(monkeypatch, fake_case, fake_party):
    """Patch external systems (Nova, Service Platform, Queue, Event log) used by process."""
    # Patch nova_functions used throughout process
    import robot_framework.rykker_borgere.nova_functions as nf
    import robot_framework.rykker_borgere.service_platform_functions as sp
    from robot_framework import config
    import robot_framework.rykker_borgere.util as util_mod

    # Stable encryption for queue key
    monkeypatch.setattr(util_mod, "encrypt_cpr", lambda cpr, first: f"enc:{cpr}")

    # Queue storage in-memory for the duration of each test
    queue_store = {}

    def get_queue_element(_orc, queue_name, key):
        assert queue_name == config.QUEUE_NAME
        return queue_store.get(key)

    def update_queue_element(_orc, queue_name, key, digital_post, nemsms, case_uuid):
        assert queue_name == config.QUEUE_NAME
        queue_store[key] = {"digital_post": digital_post, "nemsms": nemsms, "case_uuid": case_uuid}

    monkeypatch.setattr(util_mod, "get_queue_element", get_queue_element)
    monkeypatch.setattr(util_mod, "update_queue_element", update_queue_element)

    # Default nova patches (overridden per-test when needed)
    monkeypatch.setattr(nf, "get_cases_by_kle_and_cpr", lambda access, kle, cpr: [fake_case])
    monkeypatch.setattr(nf, "get_single_cpr_case_party", lambda case: fake_party)

    # Baseline helper default: no reminders yet
    monkeypatch.setattr(nf, "get_next_reminder_baseline", lambda case, access: (0, None, 14))

    # Avoid any network side effects; these won't be called in dry-run but patch anyway
    monkeypatch.setattr(nf, "upload_document", lambda *a, **k: None)
    monkeypatch.setattr(nf, "add_reminder_note", lambda *a, **k: None)
    monkeypatch.setattr(nf, "add_sms_note", lambda *a, **k: None)

    # Service platform mocks
    monkeypatch.setattr(sp, "check_registration_status", lambda cpr, acc: (False, False))
    monkeypatch.setattr(sp, "send_sms", lambda *a, **k: None)
    monkeypatch.setattr(sp, "send_digital_post", lambda *a, **k: None)

    # Avoid event log dependency noise
    from robot_framework import process

    def _noop_emit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(process, "itk_dev_event_log", types.SimpleNamespace(emit=_noop_emit))

    return {
        "queue_store": queue_store,
    }
