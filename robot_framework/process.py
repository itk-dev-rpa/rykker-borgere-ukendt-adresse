"""This module contains the main process of the robot."""
from datetime import datetime, timedelta

import pyodbc
from requests.exceptions import HTTPError

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
import itk_dev_event_log

from robot_framework.rykker_borgere import nova_functions, service_platform_functions, util
from robot_framework import config
from robot_framework.sinks import DryRunSink, RealActionsSink


def process(orchestrator_connection: OrchestratorConnection, action_sink: DryRunSink | None = None) -> None:
    """Do the primary process of the robot.

    Args:
        orchestrator_connection: OpenOrchestrator connection.
        action_sink: Sink used to collect/log actions during run. When None, a RealActionsSink
                     is constructed and the run performs real side-effects.
    """
    orchestrator_connection.log_trace("Running process.")
    itk_dev_event_log.setup_logging(orchestrator_connection.get_constant(config.EVENT_LOG_CONN).value)

    nova_connection = orchestrator_connection.get_credential("Nova API")
    nova_access = NovaAccess(nova_connection.username, nova_connection.password)
    kombit_access = service_platform_functions.get_kombit_access(orchestrator_connection)

    sink = action_sink or RealActionsSink(
        orchestrator=orchestrator_connection,
        nova_access=nova_access,
        kombit_access=kombit_access,
    )

    citizens_with_unknown_address = get_citizens_from_sql(config.SQL_CONN_STRING)
    orchestrator_connection.log_info(f"Found {len(citizens_with_unknown_address)} citizens with unknown address.")

    sms_sent_count = 0
    reminders_sent_count = 0

    try:
        for citizen in citizens_with_unknown_address:
            try:
                sms_sent, reminder_sent = handle_citizen(
                    citizen=citizen,
                    nova_access=nova_access,
                    kombit_access=kombit_access,
                    orchestrator_connection=orchestrator_connection,
                    action_sink=sink,
                )
                sms_sent_count += sms_sent
                reminders_sent_count += reminder_sent
            except Exception as e:  # pylint: disable=broad-exception-caught
                orchestrator_connection.log_error(f"Error handling citizen {citizen['Fornavn']}: {str(e)}")
                continue

        is_dry = bool(getattr(sink, "is_dry_run", False))
        if is_dry and hasattr(sink, "print_report"):
            sink.print_report(orchestrator_connection)
        else:
            itk_dev_event_log.emit(orchestrator_connection.process_name, "SMS sent", sms_sent_count)
            itk_dev_event_log.emit(orchestrator_connection.process_name, "Reminders sent", reminders_sent_count)
            orchestrator_connection.log_info(
                f"Process completed. SMS sent: {sms_sent_count}, Reminders sent: {reminders_sent_count}"
            )
    finally:
        if hasattr(sink, "end_batch"):
            try:
                sink.end_batch()
            except Exception as e:  # pylint: disable=broad-exception-caught
                orchestrator_connection.log_error(f"end_batch() raised: {e}")


def get_citizens_from_sql(db_connection: str) -> list[dict]:
    """Get citizens with unknown address from SQL database.

    Args:
        db_connection: Database connection string.

    Returns:
        List of citizen dictionaries with CPR and Fornavn.
    """
    with pyodbc.connect(db_connection) as connection:
        with connection.cursor() as cursor:
            cursor.execute(config.SQL_QUERY)
            return [{"CPR": row.CPR, "Fornavn": row.Fornavn} for row in cursor]


def _resolve_baseline_state(*, case: dict, case_uuid: str, nova_access: NovaAccess,
                            action_sink: DryRunSink | RealActionsSink,
                            orchestrator_connection: OrchestratorConnection,
                            is_dry: bool) -> tuple[int, str, int]:
    """Resolve (step_sent, baseline_date, interval_days) for a case.

    Applies dry-run mock overlays when relevant, and establishes a Rykker 0
    baseline note via the sink if none exists yet.
    """
    step_sent, baseline_date, interval_days = nova_functions.get_next_reminder_baseline(case, nova_access)

    if is_dry and hasattr(action_sink, "mock_nova_reminders"):
        mock = action_sink.mock_nova_reminders.get(case_uuid)
        if mock:
            step_sent = mock.get("latest_step", step_sent)
            baseline_date = mock.get("last_date", baseline_date)
            interval_days = (
                config.REMINDER_INITIAL_INTERVAL_DAYS if step_sent == 0
                else config.REMINDER_FOLLOWUP_INTERVAL_DAYS
            )

    if step_sent == 0 and not baseline_date:
        baseline_date = datetime.now().isoformat()
        try:
            if hasattr(action_sink, "establish_baseline"):
                action_sink.establish_baseline(case_uuid=case_uuid, step=0)
            orchestrator_connection.log_info(
                f"Etablerede baseline: 'Rykker 0 sendt' for sag {case['caseAttributes']['userFriendlyCaseNumber']}. "
                f"Første rykker tidligst om {config.REMINDER_INITIAL_INTERVAL_DAYS} dage."
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            orchestrator_connection.log_error(f"Kunne ikke oprette 'Rykker 0 sendt' baseline-note: {str(e)}")

    return step_sent, baseline_date, interval_days


def handle_citizen(*, citizen: dict, nova_access: NovaAccess, kombit_access: KombitAccess,
                   orchestrator_connection: OrchestratorConnection,
                   action_sink: DryRunSink | RealActionsSink) -> tuple[int, int]:
    """Handle a single citizen with unknown address.

    Args:
        citizen: Dictionary with CPR and Fornavn.
        nova_access: Nova API access.
        kombit_access: Kombit/Service Platform access.
        orchestrator_connection: Connection to OpenOrchestrator.
        action_sink: Sink used for side-effects (real or dry-run).

    Returns:
        Tuple of (sms_sent_count, reminder_sent_count).
    """
    is_dry = bool(getattr(action_sink, "is_dry_run", False))
    cpr = citizen["CPR"]
    first_name = citizen["Fornavn"]
    masked = util.mask_cpr(cpr)

    cases = nova_functions.get_cases_by_kle_and_cpr(nova_access, config.KLE_NUMBER, cpr)
    if not cases:
        orchestrator_connection.log_trace(f"No case found for {first_name} (CPR: {masked})")
        return 0, 0

    case = cases[0]
    case_uuid = case["common"]["uuid"]

    if hasattr(action_sink, "set_current_case_context"):
        try:
            action_sink.set_current_case_context(case)
        except Exception as e:  # pylint: disable=broad-exception-caught
            orchestrator_connection.log_error(f"set_current_case_context failed for {first_name}: {e}")

    try:
        digital_post_registered, nemsms_registered = service_platform_functions.check_registration_status(cpr, kombit_access)
    except HTTPError as e:
        orchestrator_connection.log_error(f"Failed to check registration status for {first_name}: {e.response.text}")
        return 0, 0

    encrypted_ref = util.encrypt_cpr(cpr, first_name)
    previous_status = util.get_queue_element(orchestrator_connection, config.QUEUE_NAME, encrypted_ref)

    if is_dry and hasattr(action_sink, "mock_queue_state"):
        simulated_prev = action_sink.mock_queue_state.get(encrypted_ref)
        if simulated_prev is not None:
            previous_status = simulated_prev

    step_sent, baseline_date, interval_days = _resolve_baseline_state(
        case=case,
        case_uuid=case_uuid,
        nova_access=nova_access,
        action_sink=action_sink,
        orchestrator_connection=orchestrator_connection,
        is_dry=is_dry,
    )

    baseline_dt = datetime.fromisoformat(baseline_date)
    time_until_next = timedelta(days=interval_days) - (datetime.now() - baseline_dt)
    sending_rykker_soon = time_until_next <= timedelta(days=config.SUPPRESS_SMS_WINDOW_DAYS)

    sms_sent = 0

    if (not sending_rykker_soon
            and previous_status
            and not previous_status.get("nemsms", False)
            and nemsms_registered):
        action_sink.log_sms(cpr, first_name, "da", "NemSMS-status ændret fra ikke-tilmeldt til tilmeldt")
        action_sink.log_sms(cpr, first_name, "en", "NemSMS-status ændret fra ikke-tilmeldt til tilmeldt")
        sms_sent = 2
        orchestrator_connection.log_info(f"SMS action registered for {first_name} due to NemSMS status change.")

    action_sink.log_queue_update(encrypted_ref, digital_post_registered, nemsms_registered, case_uuid)

    reminder_sent = handle_case(
        case=case,
        orchestrator_connection=orchestrator_connection,
        step_sent=step_sent,
        baseline_date=baseline_date,
        action_sink=action_sink,
    )

    return sms_sent, reminder_sent


def handle_case(*, case: dict, orchestrator_connection: OrchestratorConnection,
                step_sent: int, baseline_date: str,
                action_sink: DryRunSink | RealActionsSink) -> int:
    """Handle reminder sending for a single case.

    Args:
        case: Nova case dictionary.
        orchestrator_connection: Connection to OpenOrchestrator.
        step_sent: Number of reminder steps already sent.
        baseline_date: ISO date that is the baseline for the waiting window.
        action_sink: Sink used for side-effects (real or dry-run).

    Returns:
        Number of reminders sent (0 or 1).
    """
    case_number = case["caseAttributes"]["userFriendlyCaseNumber"]

    case_party = nova_functions.get_single_cpr_case_party(case)
    if not case_party:
        orchestrator_connection.log_error(
            f"Case {case_number} has invalid or unexpected parties (expecting exactly 1 CPR party)."
        )
        return 0

    cpr = case_party.identification
    next_step = step_sent + 1
    interval_days = (
        config.REMINDER_INITIAL_INTERVAL_DAYS if step_sent == 0
        else config.REMINDER_FOLLOWUP_INTERVAL_DAYS
    )

    baseline_dt = datetime.fromisoformat(baseline_date)
    if datetime.now() - baseline_dt < timedelta(days=interval_days):
        return 0

    try:
        action_sink.log_reminder(cpr, case_party.name, case_number, next_step)
        itk_dev_event_log.emit(orchestrator_connection.process_name, f"Rykker {next_step} sendt")
        orchestrator_connection.log_info(f"Registered reminder {next_step} for case {case_number}")
        return 1
    except Exception as e:  # pylint: disable=broad-exception-caught
        orchestrator_connection.log_error(f"Failed to send reminder for case {case_number}: {str(e)}")
        return 0
