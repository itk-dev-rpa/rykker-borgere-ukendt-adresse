"""This module contains the main process of the robot."""
import os
from datetime import datetime, timedelta
from pathlib import Path
import json
import pyodbc
from dotenv import load_dotenv
from requests.exceptions import HTTPError

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
import itk_dev_event_log

from robot_framework.rykker_borgere import nova_functions, service_platform_functions, util
from robot_framework import config
from robot_framework.dry_run_helpers import DryRunTracker


def process(orchestrator_connection: OrchestratorConnection, dry_run: bool = False) -> None:
    """Do the primary process of the robot."""
    if dry_run:
        tracker = activate_dryrun(orchestrator_connection)
    else:
        tracker = None

    orchestrator_connection.log_trace("Running process.")
    itk_dev_event_log.setup_logging(orchestrator_connection.get_constant(config.EVENT_LOG_CONN).value)

    # Get credentials for Nova and Service Platform
    nova_connection = orchestrator_connection.get_credential("Nova API")
    nova_access = NovaAccess(nova_connection.username, nova_connection.password)
    kombit_access = service_platform_functions.get_kombit_access(orchestrator_connection)

    # Get citizens with unknown address from SQL database
    db_driver = "Driver={ODBC Driver 17 for SQL Server};Server=FaellesSQL;Trusted_Connection=yes;"
    citizens_with_unknown_address = get_citizens_from_sql(db_driver, orchestrator_connection)

    orchestrator_connection.log_info(f"Found {len(citizens_with_unknown_address)} citizens with unknown address.")

    sms_sent_count = 0
    reminders_sent_count = 0

    # Process each citizen
    for citizen in citizens_with_unknown_address:
        try:
            result = handle_citizen(citizen=citizen, nova_access=nova_access, kombit_access=kombit_access, orchestrator_connection=orchestrator_connection, dry_run=dry_run, tracker=tracker)
            if result:
                sms_sent, reminder_sent = result
                sms_sent_count += sms_sent
                reminders_sent_count += reminder_sent
        except Exception as e:  # pylint: disable=broad-exception-caught
            orchestrator_connection.log_error(f"Error handling citizen {citizen['Fornavn']}: {str(e)}")
            continue

    # Print dry-run report or log final statistics
    if dry_run:
        tracker.print_report(orchestrator_connection)
    else:
        itk_dev_event_log.emit(orchestrator_connection.process_name, "SMS sent", sms_sent_count)
        itk_dev_event_log.emit(orchestrator_connection.process_name, "Reminders sent", reminders_sent_count)
        orchestrator_connection.log_info(f"Process completed. SMS sent: {sms_sent_count}, Reminders sent: {reminders_sent_count}")


def activate_dryrun(orchestrator_connection: OrchestratorConnection) -> DryRunTracker:
    """Activates dryrun my loading configuration and returning a tracker."""
    orchestrator_connection.log_info("🔍 DRY-RUN MODE AKTIVERET - Ingen ændringer vil blive foretaget")

    # Indlæs .env hvis den findes, og tillad lokal styring via miljøvariabel
    try:
        load_dotenv()  # no-op hvis .env ikke findes
    except Exception:  # pylint: disable=broad-exception-caught
        pass

    mock_state = None
    try:
        # Prioritet: miljøvariabel → config → ingen
        env_path = os.getenv("DRY_RUN_STATE_FILE")
        state_path = env_path or getattr(config, "DRY_RUN_STATE_FILE", None)

        if state_path:
            p = Path(state_path)
            if not p.is_absolute():
                # Fortolk relative stier i forhold til robot_framework-mappen
                base_dir = Path(__file__).parent
                p = base_dir / p
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    mock_state = json.load(f)
            else:
                orchestrator_connection.log_trace(f"Ingen dry-run state-fil fundet på: {p}")
    except Exception as e:  # pylint: disable=broad-exception-caught
        orchestrator_connection.log_error(f"Kunne ikke indlæse dry-run state-fil: {e}")
    return DryRunTracker(mock_state)


def get_citizens_from_sql(db_connection: str, _orchestrator_connection: OrchestratorConnection) -> list[dict]:
    """Get citizens with unknown address from SQL database.

    Args:
        db_connection: Database connection string.
        orchestrator_connection: Connection to OpenOrchestrator for logging.

    Returns:
        List of citizen dictionaries with CPR, first name, etc.
    """
    connection = pyodbc.connect(db_connection)
    cursor = connection.cursor()
    cursor.execute(config.SQL_QUERY)

    citizens = []
    for row in cursor:
        citizens.append({
            "CPR": row.CPR,
            "Fornavn": row.Fornavn
        })

    connection.close()
    return citizens

# pylint: disable=too-many-branches, too-many-statements
def handle_citizen(*, citizen: dict, nova_access: NovaAccess, kombit_access: KombitAccess,
                   orchestrator_connection: OrchestratorConnection, dry_run: bool = False,
                   tracker: DryRunTracker = None) -> tuple[int, int]:
    """Handle a single citizen with unknown address.

    Args:
        citizen: Dictionary with CPR and Fornavn.
        nova_access: Nova API access.
        kombit_access: Kombit/Service Platform access.
        orchestrator_connection: Connection to OpenOrchestrator.
        dry_run: If True, only log what would happen without making changes.
        tracker: DryRunTracker instance for collecting dry-run statistics.

    Returns:
        Tuple of (sms_sent_count, reminder_sent_count).
    """

    cpr = citizen["CPR"]
    first_name = citizen["Fornavn"]

    # Find Nova case for this citizen
    cases = nova_functions.get_cases_by_kle_and_cpr(nova_access, config.KLE_NUMBER, cpr)

    if not cases:
        orchestrator_connection.log_trace(f"No case found for {first_name} (CPR: {cpr[:6]}****)")
        return 0, 0

    # Use the first case if multiple exist
    case = cases[0]
    case_uuid = case["common"]["uuid"]

    # Check Digital Post and NemSMS registration status
    try:
        digital_post_registered, nemsms_registered = service_platform_functions.check_registration_status(cpr, kombit_access)
    except HTTPError as e:
        orchestrator_connection.log_error(f"Failed to check registration status for {first_name}: {e.response.text}")
        return 0, 0

    # Get previous registration status from queue
    encrypted_ref = util.encrypt_cpr(cpr, first_name)
    previous_status = util.get_queue_element(orchestrator_connection, config.QUEUE_NAME, encrypted_ref)

    # In dry-run we may overlay a simulated previous queue state from tracker
    if dry_run and tracker and hasattr(tracker, "mock_queue_state"):
        simulated_prev = tracker.mock_queue_state.get(encrypted_ref)
        if simulated_prev is not None:
            previous_status = simulated_prev

    # Compute baseline and interval for next reminder based on steps already sent
    step_sent, baseline_date, interval_days = nova_functions.get_next_reminder_baseline(case, nova_access)

    # In dry-run overlay reminder state if provided
    if dry_run and tracker and hasattr(tracker, "mock_nova_reminders"):
        mock = tracker.mock_nova_reminders.get(case_uuid)
        if mock:
            step_sent = mock.get("latest_step", step_sent)
            baseline_date = mock.get("last_date", baseline_date)
            # interval still derived from step count
            interval_days = 14 if step_sent == 0 else 30

    # If no reminder notes exist at all (step_sent == 0 and no baseline date), establish step 0 now (non-dry-run)
    if step_sent == 0 and not baseline_date:
        baseline_date = datetime.now().isoformat()
        if not dry_run:
            try:
                nova_functions.add_reminder_note(case_uuid, 0, nova_access)
                interval_days = 14
                orchestrator_connection.log_info(f"Etablerede baseline i Nova: 'Rykker 0 sendt' for sag {case['caseAttributes']['userFriendlyCaseNumber']}. Første rykker tidligst om 14 dage.")
            except Exception as e:  # pylint: disable=broad-exception-caught
                orchestrator_connection.log_error(f"Kunne ikke oprette 'Rykker 0 sendt' baseline-note: {str(e)}")
        else:
            # In dry-run, do not write to Nova; just track that we would establish baseline now
            if tracker:
                tracker.log_nova_note(case_uuid, "Rykker note", "Rykker 0 (baseline)")
            # Simulate baseline creation in dry-run so downstream logic can test reminder timing
            interval_days = 14

    # Determine if a reminder will be sent within 7 days (used to suppress SMS around reminder time)
    baseline_dt = datetime.fromisoformat(baseline_date)
    time_until_next = timedelta(days=interval_days) - (datetime.now() - baseline_dt)
    sending_rykker_soon = time_until_next <= timedelta(days=7)

    sms_sent = 0
    reminder_sent = 0

    # Check if NemSMS status changed from not registered to registered
    if not sending_rykker_soon and previous_status and not previous_status.get("nemsms", False) and nemsms_registered:
        # Send SMS in both Danish and English
        if not dry_run:
            service_platform_functions.send_sms(kombit_access, cpr, "da")
            service_platform_functions.send_sms(kombit_access, cpr, "en")
            nova_functions.add_sms_note(case_uuid, nova_access, "NemSMS-status ændret fra ikke-tilmeldt til tilmeldt", config.CASEWORKER)
        else:
            if tracker:
                tracker.log_sms(cpr, first_name, "da", "NemSMS-status ændret fra ikke-tilmeldt til tilmeldt")
                tracker.log_sms(cpr, first_name, "en", "NemSMS-status ændret fra ikke-tilmeldt til tilmeldt")
                tracker.log_nova_note(case_uuid, "SMS note", "NemSMS-status ændret fra ikke-tilmeldt til tilmeldt")
        sms_sent = 2
        if dry_run:
            orchestrator_connection.log_info(f"(dry-run) Ville sende SMS (da+en) til {first_name} pga. NemSMS statusændring.")
        else:
            orchestrator_connection.log_info(f"SMS sent to {first_name} due to NemSMS status change.")

    # Update queue with current status
    util.update_queue_element(orchestrator_connection, config.QUEUE_NAME, encrypted_ref, digital_post_registered, nemsms_registered, case_uuid)
    if dry_run and tracker:
        tracker.log_queue_update(encrypted_ref, digital_post_registered, nemsms_registered, case_uuid)

    # Handle reminder sending logic
    reminder_result = handle_case(case, nova_access, kombit_access, orchestrator_connection, dry_run, tracker, step_sent, baseline_date)
    if reminder_result:
        reminder_sent = reminder_result

    return sms_sent, reminder_sent

# pylint: disable=too-many-positional-arguments
def handle_case(case: dict, nova_access: NovaAccess, kombit_access: KombitAccess,
                orchestrator_connection: OrchestratorConnection, dry_run: bool = False,
                tracker: DryRunTracker = None, step_sent: int = 0, baseline_date: str | None = None) -> int:
    """Handle reminder sending for a single case.

    Args:
        case: Nova case dictionary.
        nova_access: Nova API access.
        kombit_access: Kombit/Service Platform access.
        orchestrator_connection: Connection to OpenOrchestrator.
        dry_run: If True, only log what would happen without making changes.
        tracker: DryRunTracker instance for collecting dry-run statistics.

    Returns:
        Number of reminders sent (0 or 1).
    """

    case_uuid = case["common"]["uuid"]
    case_number = case["caseAttributes"]["userFriendlyCaseNumber"]

    # Extract single CPR case party via helper
    case_party = nova_functions.get_single_cpr_case_party(case)
    if not case_party:
        orchestrator_connection.log_error(f"Case {case_number} has invalid or unexpected parties (expecting exactly 1 CPR party).")
        return 0

    cpr = case_party.identification

    # Use provided step/baseline to decide if we can send the next reminder
    next_step = step_sent + 1
    interval_days = 14 if step_sent == 0 else 30

    baseline_dt = datetime.fromisoformat(baseline_date)
    if datetime.now() - baseline_dt < timedelta(days=interval_days):
        return 0  # Not enough time has passed

    # Time window satisfied → send reminder letter for next_step
    template_to_use = f"rykker_borgere/templates/Rykker {next_step} - Ukendt adresse.docx"
    letter_name = f"Rykker {next_step} - Adresse.docx"
    deadline_date = datetime.now() + timedelta(days=30)

    try:
        # Only create documents if not dry run
        if not dry_run:
            letter_path = util.fill_template(template_to_use, f"tmp/{letter_name}", case_party.name, deadline_date, case_number)
            pdf_path = util.convert_docx_to_pdf(letter_path, "tmp/")
            # Upload to Nova and send via Digital Post
            nova_functions.upload_document(nova_access, str(pdf_path), letter_name, case_uuid)
            service_platform_functions.send_digital_post(kombit_access, str(pdf_path), cpr)
            nova_functions.add_reminder_note(case_uuid, next_step, nova_access)

        # Track reminder in dry-run tracker
        if dry_run and tracker:
            tracker.log_reminder(cpr, case_party.name, case_number, next_step)
            tracker.log_nova_note(case_uuid, "Rykker note", f"Rykker {next_step}")

        if not dry_run:
            itk_dev_event_log.emit(orchestrator_connection.process_name, f"Rykker {next_step} sendt")
            orchestrator_connection.log_info(f"Sent reminder {next_step} for case {case_number}")

        return 1

    except Exception as e:  # pylint: disable=broad-exception-caught
        orchestrator_connection.log_error(f"Failed to send reminder for case {case_number}: {str(e)}")
        return 0


if __name__ == "__main__":
    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    oc = OrchestratorConnection("Udtræk Tilmelding Digital Post", conn_string, crypto_key, "", "")
    process(oc, dry_run=True)
