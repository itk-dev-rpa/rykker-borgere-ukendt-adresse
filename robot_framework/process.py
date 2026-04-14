"""This module contains the main process of the robot."""
import os
from datetime import datetime, timedelta
import pyodbc
from requests.exceptions import HTTPError

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
from itk_dev_shared_components.kmd_nova import nova_cases
import itk_dev_event_log

from robot_framework.rykker_borgere import nova_functions, service_platform_functions, util
from robot_framework import config


def process(orchestrator_connection: OrchestratorConnection) -> None:
    """Do the primary process of the robot."""
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
            result = handle_citizen(citizen, nova_access, kombit_access, orchestrator_connection)
            if result:
                sms_sent, reminder_sent = result
                sms_sent_count += sms_sent
                reminders_sent_count += reminder_sent
        except Exception as e:  # pylint: disable=broad-exception-caught
            orchestrator_connection.log_error(f"Error handling citizen {citizen['Fornavn']}: {str(e)}")
            continue

    # Log final statistics
    itk_dev_event_log.emit(orchestrator_connection.process_name, "SMS sent", sms_sent_count)
    itk_dev_event_log.emit(orchestrator_connection.process_name, "Reminders sent", reminders_sent_count)
    orchestrator_connection.log_info(f"Process completed. SMS sent: {sms_sent_count}, Reminders sent: {reminders_sent_count}")


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


def handle_citizen(citizen: dict, nova_access: NovaAccess, kombit_access: KombitAccess,
                   orchestrator_connection: OrchestratorConnection) -> tuple[int, int]:
    """Handle a single citizen with unknown address.

    Args:
        citizen: Dictionary with CPR and Fornavn.
        nova_access: Nova API access.
        kombit_access: Kombit/Service Platform access.
        orchestrator_connection: Connection to OpenOrchestrator.

    Returns:
        Tuple of (sms_sent_count, reminder_sent_count).
    """
    cpr = citizen["CPR"]
    first_name = citizen["Fornavn"]

    # Find Nova case for this citizen
    cases = nova_functions.get_cases_by_kle_and_cpr(nova_access, config.KLE_NUMBER, cpr)

    if not cases:
        orchestrator_connection.log_trace(f"No case found for {first_name} (CPR: {cpr[:6]}****)")
        return (0, 0)

    # Use the first case if multiple exist
    case = cases[0]
    case_uuid = case["common"]["uuid"]

    # Check Digital Post and NemSMS registration status
    try:
        digital_post_registered, nemsms_registered = service_platform_functions.check_registration_status(cpr, kombit_access)
    except HTTPError as e:
        orchestrator_connection.log_error(f"Failed to check registration status for {first_name}: {e.response.text}")
        return (0, 0)

    # Get previous registration status from queue
    encrypted_ref = util.encrypt_cpr(cpr, first_name)
    previous_status = util.get_queue_element(orchestrator_connection, config.QUEUE_NAME, encrypted_ref)

    sms_sent = 0
    reminder_sent = 0

    # Check if NemSMS status changed from not registered to registered
    if previous_status and not previous_status.get("nemsms", False) and nemsms_registered:
        # Send SMS in both Danish and English
        service_platform_functions.send_sms(kombit_access, cpr, "da")
        service_platform_functions.send_sms(kombit_access, cpr, "en")
        nova_functions.add_sms_note(case_uuid, nova_access, reason="NemSMS-status ændret fra ikke-tilmeldt til tilmeldt")
        sms_sent = 2
        orchestrator_connection.log_info(f"SMS sent to {first_name} due to NemSMS status change.")

    # Update queue with current status
    util.update_queue_element(orchestrator_connection, config.QUEUE_NAME, encrypted_ref,
                              digital_post_registered, nemsms_registered, case_uuid)

    # Handle reminder sending logic
    reminder_result = handle_case(case, nova_access, kombit_access, orchestrator_connection)
    if reminder_result:
        reminder_sent = reminder_result

    return (sms_sent, reminder_sent)


def handle_case(case: dict, nova_access: NovaAccess, kombit_access: KombitAccess, orchestrator_connection: OrchestratorConnection) -> int:
    """Handle reminder sending for a single case.

    Args:
        case: Nova case dictionary.
        nova_access: Nova API access.
        kombit_access: Kombit/Service Platform access.
        orchestrator_connection: Connection to OpenOrchestrator.

    Returns:
        Number of reminders sent (0 or 1).
    """
    case_uuid = case["common"]["uuid"]
    case_number = case["caseAttributes"]["userFriendlyCaseNumber"]

    # Extract case party
    case_parties = nova_cases._extract_case_parties(case)  # pylint: disable=protected-access
    if len(case_parties) != 1:
        orchestrator_connection.log_error(f"Case {case_number} has {len(case_parties)} parties, expected 1.")
        return 0

    case_party = case_parties[0]
    if case_party.identification_type != "CprNummer":
        orchestrator_connection.log_error(f"Case {case_number} has invalid party type {case_party.identification_type}.")
        return 0

    cpr = case_party.identification

    # Get latest reminder info from Nova notes
    latest_step, last_reminder_date = nova_functions.get_latest_reminder_info(case_uuid, nova_access)

    # Calculate next step
    next_step = latest_step + 1

    # Check if enough time has passed since last reminder
    if last_reminder_date:
        note_date = datetime.fromisoformat(last_reminder_date)
        message_interval = 14 if latest_step == 0 else 30  # 14 days for first reminder, 30 for subsequent
        if datetime.now() - note_date < timedelta(days=message_interval):
            return 0  # Not enough time has passed

    # Send reminder letter if this is not the first contact (step > 0)
    if next_step > 0:
        template_to_use = f"rykker_borgere/templates/Rykker {next_step} - Ukendt adresse.docx"
        letter_name = f"Rykker {next_step} - Adresse.docx"
        deadline_date = datetime.now() + timedelta(days=30)

        try:
            letter_path = util.fill_template(template_to_use, f"tmp/{letter_name}", case_party.name, deadline_date, case_number)
            pdf_path = util.convert_docx_to_pdf(letter_path, "tmp/")

            # Upload to Nova and send via Digital Post
            nova_functions.upload_document(nova_access, str(pdf_path), letter_name, case_uuid)
            service_platform_functions.send_digital_post(kombit_access, str(pdf_path), cpr)

            # Add journal note for reminder
            nova_functions.add_reminder_note(case_uuid, next_step, nova_access)

            itk_dev_event_log.emit(orchestrator_connection.process_name, f"Rykker {next_step} sendt")
            orchestrator_connection.log_info(f"Sent reminder {next_step} for case {case_number}")

            return 1

        except Exception as e:  # pylint: disable=broad-exception-caught
            orchestrator_connection.log_error(f"Failed to send reminder for case {case_number}: {str(e)}")
            return 0

    return 0


if __name__ == "__main__":
    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    oc = OrchestratorConnection("Udtræk Tilmelding Digital Post", conn_string, crypto_key, "", "")
    process(oc)
