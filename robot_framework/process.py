"""This module contains the main process of the robot."""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pyodbc
from requests.exceptions import HTTPError

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
from itk_dev_shared_components.smtp import smtp_util
import itk_dev_event_log

from robot_framework.rykker_borgere import nova_functions, service_platform_functions, util
from robot_framework import config
from robot_framework.sinks import DryRunSink, RealActionsSink


@dataclass
class BackofficeAlerts:
    """Aggregates citizens that require manual backoffice attention during a run.

    Entries are appended throughout the loop and a single summary email is sent at the
    end of process(). In dry-run mode the lists are rendered in print_report instead.
    """
    no_case: list[dict] = field(default_factory=list)      # {"fornavn", "cpr"}
    high_step: list[dict] = field(default_factory=list)    # {"case_number", "fornavn", "cpr", "step"}

    def is_empty(self) -> bool:
        """Return True when no citizens need backoffice attention this run."""
        return not self.no_case and not self.high_step


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

    # Optional batch cap from the OpenOrchestrator process arguments, e.g. {"limit": 5}.
    if orchestrator_connection.process_arguments:
        limit = json.loads(orchestrator_connection.process_arguments)["limit"]
        citizens_with_unknown_address = citizens_with_unknown_address[:limit]
        orchestrator_connection.log_info(f"Batch limit active: processing at most {limit} citizens this run.")

    sms_sent_count = 0
    reminders_sent_count = 0
    verbose = sink.verbose
    total = len(citizens_with_unknown_address)
    alerts = BackofficeAlerts()

    for index, citizen in enumerate(citizens_with_unknown_address, start=1):
        if verbose:
            print(
                f"\n[{index}/{total}] {citizen['Fornavn']} ({util.mask_cpr(citizen['CPR'])})",
                flush=True,
            )
        try:
            sms_sent, reminder_sent = handle_citizen(
                citizen=citizen,
                nova_access=nova_access,
                kombit_access=kombit_access,
                orchestrator_connection=orchestrator_connection,
                action_sink=sink,
                alerts=alerts,
            )
            sms_sent_count += sms_sent
            reminders_sent_count += reminder_sent
        except Exception as e:  # pylint: disable=broad-exception-caught
            orchestrator_connection.log_error(f"Error handling citizen {citizen['Fornavn']}: {str(e)}")
            continue

    if sink.is_dry_run:
        sink.backoffice_alerts = alerts
        sink.print_report(orchestrator_connection)
    else:
        itk_dev_event_log.emit(orchestrator_connection.process_name, "SMS sent", sms_sent_count)
        itk_dev_event_log.emit(orchestrator_connection.process_name, "Reminders sent", reminders_sent_count)
        orchestrator_connection.log_info(
            f"Process completed. SMS sent: {sms_sent_count}, Reminders sent: {reminders_sent_count}"
        )
        if not alerts.is_empty():
            try:
                _send_backoffice_alert_mail(alerts)
                orchestrator_connection.log_info(
                    f"Backoffice alert mail sent to {config.BACKOFFICE_RECIPIENT} "
                    f"(no_case: {len(alerts.no_case)}, high_step: {len(alerts.high_step)})"
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                orchestrator_connection.log_error(f"Failed to send backoffice alert mail: {str(e)}")


def _format_backoffice_body(alerts: BackofficeAlerts) -> str:
    """Render the backoffice alerts as a plain-text email body. CPR is masked (GDPR)."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"Robotten 'Rykker borgere - ukendt adresse' har kørt {today}.", ""]

    if alerts.no_case:
        lines.append(f"INGEN SAG FUNDET ({len(alerts.no_case)} borgere):")
        lines.append(f"  {'Fornavn':<20}  {'CPR':<15}")
        for entry in alerts.no_case:
            lines.append(f"  {entry['fornavn']:<20}  {entry['cpr']:<15}")
        lines.append("")

    if alerts.high_step:
        lines.append(
            f"STEP ≥ {config.HIGH_STEP_THRESHOLD} — borger har modtaget mange rykkere "
            f"({len(alerts.high_step)} borgere):"
        )
        lines.append(f"  {'Sagsnr':<14}  {'Fornavn':<20}  {'CPR':<15}  {'Step':>4}")
        for entry in alerts.high_step:
            lines.append(
                f"  {entry['case_number']:<14}  {entry['fornavn']:<20}  "
                f"{entry['cpr']:<15}  {entry['step']:>4}"
            )
        lines.append("")

    return "\n".join(lines)


def _send_backoffice_alert_mail(alerts: BackofficeAlerts) -> None:
    """Send the aggregated backoffice mail via the shared SMTP helper."""
    smtp_util.send_email(
        receiver=config.BACKOFFICE_RECIPIENT,
        sender=config.SCREENSHOT_SENDER,
        subject="Rykker-robot: borgere der kræver opmærksomhed",
        body=_format_backoffice_body(alerts),
        smtp_server=config.SMTP_SERVER,
        smtp_port=config.SMTP_PORT,
        html_body=False,
    )


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

    Applies dry-run mock overlays when relevant. No notes are created here — when
    step_sent == 0 the baseline is the case's own caseDate (Sagsdato), so robot
    activity is only journaled when an actual reminder is sent.
    """
    step_sent, baseline_date, interval_days = nova_functions.get_next_reminder_baseline(case, nova_access)

    if is_dry:
        mock = action_sink.mock_nova_reminders.get(case_uuid)
        if mock:
            step_sent = mock.get("latest_step", step_sent)
            baseline_date = mock.get("last_date", baseline_date)
            interval_days = (
                config.REMINDER_INITIAL_INTERVAL_DAYS if step_sent == 0
                else config.REMINDER_FOLLOWUP_INTERVAL_DAYS
            )

    if step_sent == 0 and not baseline_date:
        # caseDate was missing or unparseable; fall back to "now" so we wait the full
        # initial interval rather than crashing on datetime.fromisoformat(None).
        baseline_date = datetime.now().isoformat()
        orchestrator_connection.log_error(
            f"Manglende/ugyldig caseDate for sag {case['caseAttributes']['userFriendlyCaseNumber']}; "
            f"bruger nu som baseline (første rykker tidligst om {config.REMINDER_INITIAL_INTERVAL_DAYS} dage)."
        )

    return step_sent, baseline_date, interval_days


def handle_citizen(*, citizen: dict, nova_access: NovaAccess, kombit_access: KombitAccess,
                   orchestrator_connection: OrchestratorConnection,
                   action_sink: DryRunSink | RealActionsSink,
                   alerts: BackofficeAlerts | None = None) -> tuple[int, int]:
    """Handle a single citizen with unknown address.

    Args:
        citizen: Dictionary with CPR and Fornavn.
        nova_access: Nova API access.
        kombit_access: Kombit/Service Platform access.
        orchestrator_connection: Connection to OpenOrchestrator.
        action_sink: Sink used for side-effects (real or dry-run).
        alerts: Aggregator that gets appended-to when backoffice attention is needed.
            When None (typically in unit tests), aggregation is skipped silently.

    Returns:
        Tuple of (sms_sent_count, reminder_sent_count).
    """
    is_dry = action_sink.is_dry_run
    cpr = citizen["CPR"]
    first_name = citizen["Fornavn"]
    masked = util.mask_cpr(cpr)

    cases = nova_functions.get_cases_by_kle_and_cpr(nova_access, config.KLE_NUMBER, cpr)
    if not cases:
        orchestrator_connection.log_trace(f"No case found for {first_name} (CPR: {masked})")
        if alerts is not None:
            alerts.no_case.append({"fornavn": first_name, "cpr": cpr})
        return 0, 0

    case = cases[0]
    case_uuid = case["common"]["uuid"]

    # If a case is set to "Oplyst", do not act on the case. This is how caseworkers pause the robot.
    if case["state"]["progressState"] == "Oplyst":
        return 0, 0

    try:
        digital_post_registered, nemsms_registered = service_platform_functions.check_registration_status(cpr, kombit_access)
    except HTTPError as e:
        # check_registration_status has already retried internally up to
        # config.REGISTRATION_CHECK_ATTEMPTS attempts. Reaching here means the failure is
        # persistent — skip the citizen and try again on the next Monday run.
        orchestrator_connection.log_error(f"Failed to check registration status for {first_name}: {e.response.text}")
        return 0, 0

    encrypted_ref = util.encrypt_cpr(cpr, first_name)
    previous_status = util.get_queue_element(orchestrator_connection, config.QUEUE_NAME, encrypted_ref)

    if is_dry:
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

    if alerts is not None and step_sent >= config.HIGH_STEP_THRESHOLD:
        alerts.high_step.append({
            "case_number": case["caseAttributes"]["userFriendlyCaseNumber"],
            "fornavn": first_name,
            "cpr": masked,
            "step": step_sent,
        })

    baseline_dt = datetime.fromisoformat(baseline_date)
    time_until_next = timedelta(days=interval_days) - (datetime.now() - baseline_dt)
    sending_rykker_soon = time_until_next <= timedelta(days=config.SUPPRESS_SMS_WINDOW_DAYS)

    sms_sent = 0

    if (not sending_rykker_soon
            and previous_status
            and not previous_status.get("nemsms", False)
            and nemsms_registered):
        action_sink.send_sms(case, cpr, first_name, language="da", reason="NemSMS-status ændret fra ikke-tilmeldt til tilmeldt")
        action_sink.send_sms(case, cpr, first_name, language="en", reason="NemSMS-status ændret fra ikke-tilmeldt til tilmeldt")
        sms_sent = 2
        orchestrator_connection.log_info(f"SMS action registered for {first_name} due to NemSMS status change.")

    action_sink.update_queue(encrypted_ref, digital_post_registered, nemsms_registered, case_uuid)

    reminder_sent = handle_case(
        case=case,
        orchestrator_connection=orchestrator_connection,
        step_sent=step_sent,
        baseline_date=baseline_date,
        action_sink=action_sink,
        nemsms_registered=nemsms_registered,
    )

    return sms_sent, reminder_sent


def handle_case(*, case: dict, orchestrator_connection: OrchestratorConnection,
                step_sent: int, baseline_date: str,
                action_sink: DryRunSink | RealActionsSink,
                nemsms_registered: bool = False) -> int:
    """Handle reminder sending for a single case.

    Args:
        case: Nova case dictionary.
        orchestrator_connection: Connection to OpenOrchestrator.
        step_sent: Number of reminder steps already sent.
        baseline_date: ISO date that is the baseline for the waiting window.
        action_sink: Sink used for side-effects (real or dry-run).
        nemsms_registered: True if the citizen is NemSMS-subscribed. Used to trigger a
            confirmation SMS after successful digital post delivery.

    Returns:
        Number of reminders sent (0 or 1). An "Ikke sendt: Rykker X" note also counts
        as 1, because the step counter still advances (see RealActionsSink.send_reminder).
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
        action_sink.send_reminder(
            case, cpr, case_party.name, next_step,
            nemsms_registered=nemsms_registered,
        )
        itk_dev_event_log.emit(orchestrator_connection.process_name, f"Rykker {next_step} sendt")
        orchestrator_connection.log_info(f"Registered reminder {next_step} for case {case_number}")
        return 1
    except Exception as e:  # pylint: disable=broad-exception-caught
        orchestrator_connection.log_error(f"Failed to send reminder for case {case_number}: {str(e)}")
        return 0
