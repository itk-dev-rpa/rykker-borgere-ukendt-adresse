"""This module contains the main process of the robot."""
import os
from datetime import datetime, timedelta

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
import itk_dev_event_log

from robot_framework.rykker_borgere import nova_functions, service_platform_functions, util
from robot_framework import config


def process(orchestrator_connection: OrchestratorConnection) -> None:
    """Do the primary process of the robot."""
    orchestrator_connection.log_trace("Running process.")
    itk_dev_event_log.setup_logging(orchestrator_connection.get_constant(config.EVENT_LOG_CONN).value)
    # Get credentials for Nova
    nova_connection = orchestrator_connection.get_credential("Nova API")
    nova_access = NovaAccess(nova_connection.username, nova_connection.password)

    kombit_access = service_platform_functions.get_kombit_access(orchestrator_connection)

    cases = nova_functions.get_cases(nova_access)
    for case in cases:
        handle_case(case, nova_access, kombit_access, orchestrator_connection)


def handle_case(case: dict, nova_access: NovaAccess, kombit_access: KombitAccess, orchestrator_connection: OrchestratorConnection) -> None:
    """Handle a single case."""
    notes = nova_functions.get_notes(nova_access, case["id"])
    new_step, newest_note = util.get_step(notes)

    message_interval = 30 if new_step > 1 else 14
    if newest_note is not None:
        note_date = datetime.strptime(newest_note.journal_date, "%Y-%m-%dT%H:%M:%S.%f")
        if datetime.now() - note_date < timedelta(days=message_interval):
            return

    # Only send digital post if we have already sent a letter
    if new_step > 0:
        template_to_use = f"Rykker {new_step} - Ukendt adresse.docx"
        letter_name = "Adresse rykker.docx"
        deadline_date = datetime.now() + timedelta(days=30)
        letter_to_send = util.fill_template(template_to_use, letter_name, "testnavn", deadline_date, case["id"])
        letter_to_send = util.convert_docx_to_pdf(letter_to_send, "tmp/")
        service_platform_functions.send_digital_post(kombit_access, case['cpr'], letter_to_send)
        nova_functions.upload_document(nova_access, case["id"], letter_name, letter_to_send)

    service_platform_functions.send_sms(kombit_access, case['cpr'])
    itk_dev_event_log.emit(orchestrator_connection.process_name, f"Rykker {new_step} sendt af robot.")

    nova_functions.nova_notes.add_text_note(
        case_uuid=case["id"],
        note_title=f"{config.NOTE_PREFIX}{new_step}",
        note_text=f"Rykker {new_step} sendt af robot.",
        caseworker=config.CASEWORKER,
        approved=False,
        nova_access=nova_access)


if __name__ == "__main__":
    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    oc = OrchestratorConnection("Udtræk Tilmelding Digital Post", conn_string, crypto_key, "","")
    process(oc)
