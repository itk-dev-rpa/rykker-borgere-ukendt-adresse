"""Unit tests for `robot_framework.process` reminder and SMS logic.

Covers:
- Baseline establishment (Rykker 0) on first processing without baseline.
- Reminder timing from step 0 -> 1 (14 days) and 1 -> 2 (30 days).
- SMS behavior on NemSMS status change with and without suppression window.
- Queue tracking updates.
- Direct `handle_case` behavior when time window is met.
"""

# pylint: disable=import-outside-toplevel

from datetime import timedelta

from robot_framework.process import handle_citizen, handle_case
from robot_framework.sinks import DryRunSink


def _build_tracker_with_state(case_uuid: str, latest_step: int, last_date_iso: str):
    """Helper to create a `DryRunSink` with simulated Nova reminder state."""
    return DryRunSink(mock_state={
        "queue": {},
        "nova_reminders": {
            case_uuid: {"latest_step": latest_step, "last_date": last_date_iso}
        }
    })


def test_new_case_without_baseline_establishes_rykker0(monkeypatch, orchestrator, fixed_now, fake_case):
    """When no baseline exists, establish Rykker 0 (dry-run note), no reminder yet."""
    # Silence unused fixtures in this test
    _ = fixed_now, fake_case
    # Arrange: no baseline from nova_functions (set in conftest default)
    from robot_framework.rykker_borgere import service_platform_functions as sp
    # Ensure registration status doesn't trigger SMS
    monkeypatch.setattr(sp, "check_registration_status", lambda cpr, acc: (False, False))

    tracker = DryRunSink(mock_state={})
    citizen = {"CPR": "0101011234", "Fornavn": "Ada"}

    # Act
    sms_sent, reminder_sent = handle_citizen(
        citizen=citizen,
        nova_access=None,
        kombit_access=None,
        orchestrator_connection=orchestrator,
        action_sink=tracker,
    )

    # Assert: baseline note is simulated in dry-run, but no reminder yet
    assert sms_sent == 0
    assert reminder_sent == 0
    assert any("Rykker 0 (baseline)" in n["details"] for n in tracker.nova_notes)
    # Queue updated once
    assert len(tracker.queue_updates) == 1


def test_14_days_since_rykker0_sends_rykker1(orchestrator, fixed_now, fake_case):
    """14+ days since baseline triggers sending Rykker 1."""
    # Arrange
    case_uuid = fake_case["common"]["uuid"]
    baseline = (fixed_now - timedelta(days=15)).isoformat()
    tracker = _build_tracker_with_state(case_uuid, latest_step=0, last_date_iso=baseline)
    citizen = {"CPR": "0101011234", "Fornavn": "Ada"}

    # Act
    sms_sent, reminder_sent = handle_citizen(
        citizen=citizen,
        nova_access=None,
        kombit_access=None,
        orchestrator_connection=orchestrator,
        action_sink=tracker,
    )

    # Assert
    assert sms_sent == 0
    assert reminder_sent == 1
    assert tracker.reminder_actions, "Expected a reminder action to be logged"
    assert tracker.reminder_actions[0]["step"] == 1


def test_30_days_since_rykker1_sends_rykker2(orchestrator, fixed_now, fake_case):
    """30+ days since Rykker 1 triggers sending Rykker 2."""
    # Arrange
    case_uuid = fake_case["common"]["uuid"]
    baseline = (fixed_now - timedelta(days=31)).isoformat()
    tracker = _build_tracker_with_state(case_uuid, latest_step=1, last_date_iso=baseline)
    citizen = {"CPR": "0101011234", "Fornavn": "Ada"}

    # Act
    sms_sent, reminder_sent = handle_citizen(
        citizen=citizen,
        nova_access=None,
        kombit_access=None,
        orchestrator_connection=orchestrator,
        action_sink=tracker,
    )

    # Assert
    assert sms_sent == 0
    assert reminder_sent == 1
    assert tracker.reminder_actions[0]["step"] == 2


def test_nemsms_status_change_triggers_sms_when_not_sending_soon(monkeypatch, orchestrator, fixed_now, fake_case, patch_external_functions):
    """NemSMS false->true sends 2 SMS when not within 7-day suppression window."""
    # Arrange: previous queue had nemsms=False, now registration returns True
    queue_store = patch_external_functions["queue_store"]
    enc_key = "enc:0101011234"
    queue_store[enc_key] = {"digital_post": False, "nemsms": False, "case_uuid": fake_case["common"]["uuid"]}

    from robot_framework.rykker_borgere import service_platform_functions as sp
    monkeypatch.setattr(sp, "check_registration_status", lambda cpr, acc: (False, True))

    case_uuid = fake_case["common"]["uuid"]
    # Baseline too far in future to be 'sending soon' (13 days left > 7)
    baseline = (fixed_now - timedelta(days=1)).isoformat()
    tracker = _build_tracker_with_state(case_uuid, latest_step=0, last_date_iso=baseline)

    citizen = {"CPR": "0101011234", "Fornavn": "Ada"}

    # Act
    sms_sent, reminder_sent = handle_citizen(
        citizen=citizen,
        nova_access=None,
        kombit_access=None,
        orchestrator_connection=orchestrator,
        action_sink=tracker,
    )

    # Assert: two SMS (da+en), no reminder
    assert sms_sent == 2
    assert reminder_sent == 0
    langs = [s["language"] for s in tracker.sms_actions]
    assert set(langs) == {"da", "en"}


def test_nemsms_status_change_suppressed_when_sending_soon(monkeypatch, orchestrator, fixed_now, fake_case):
    """NemSMS false->true is suppressed if within 7 days of next reminder."""
    # Arrange: within 7 days window until next reminder
    from robot_framework.rykker_borgere import service_platform_functions as sp
    monkeypatch.setattr(sp, "check_registration_status", lambda cpr, acc: (False, True))

    case_uuid = fake_case["common"]["uuid"]
    baseline = (fixed_now - timedelta(days=10)).isoformat()  # 4 days left to 14
    tracker = _build_tracker_with_state(case_uuid, latest_step=0, last_date_iso=baseline)

    citizen = {"CPR": "0101011234", "Fornavn": "Ada"}

    # Act
    sms_sent, reminder_sent = handle_citizen(
        citizen=citizen,
        nova_access=None,
        kombit_access=None,
        orchestrator_connection=orchestrator,
        action_sink=tracker,
    )

    # Assert: SMS suppressed due to sending_rykker_soon
    assert sms_sent == 0
    assert reminder_sent == 0


def test_too_early_for_next_reminder_no_action(orchestrator, fixed_now, fake_case):
    """If too early relative to baseline, neither SMS nor reminder is sent."""
    # Arrange: baseline only 5 days ago
    case_uuid = fake_case["common"]["uuid"]
    baseline = (fixed_now - timedelta(days=5)).isoformat()
    tracker = _build_tracker_with_state(case_uuid, latest_step=0, last_date_iso=baseline)
    citizen = {"CPR": "0101011234", "Fornavn": "Ada"}

    # Act
    sms_sent, reminder_sent = handle_citizen(
        citizen=citizen,
        nova_access=None,
        kombit_access=None,
        orchestrator_connection=orchestrator,
        action_sink=tracker,
    )

    # Assert
    assert sms_sent == 0
    assert reminder_sent == 0


def test_queue_tracking_logged(orchestrator, fixed_now, fake_case):
    """Queue tracking is logged in the dry-run tracker."""
    # Arrange
    case_uuid = fake_case["common"]["uuid"]
    baseline = (fixed_now - timedelta(days=1)).isoformat()
    tracker = _build_tracker_with_state(case_uuid, latest_step=0, last_date_iso=baseline)
    citizen = {"CPR": "0101011234", "Fornavn": "Ada"}

    # Act
    handle_citizen(
        citizen=citizen,
        nova_access=None,
        kombit_access=None,
        orchestrator_connection=orchestrator,
        action_sink=tracker,
    )

    # Assert: queue updated once per citizen handled
    assert len(tracker.queue_updates) == 1
    upd = tracker.queue_updates[0]
    assert upd["case_uuid"] == case_uuid


def test_handle_case_direct_send_when_window_met(orchestrator, fixed_now, fake_case):
    """`handle_case` sends Rykker 1 when >14 days since baseline for step 0."""
    # Arrange: direct unit test of handle_case
    baseline = (fixed_now - timedelta(days=20)).isoformat()  # >14 days since step 0
    tracker = DryRunSink(mock_state={})

    # Act
    sent = handle_case(
        case=fake_case,
        orchestrator_connection=orchestrator,
        step_sent=0,
        baseline_date=baseline,
        action_sink=tracker,
    )

    # Assert
    assert sent == 1
    assert tracker.reminder_actions[0]["step"] == 1
