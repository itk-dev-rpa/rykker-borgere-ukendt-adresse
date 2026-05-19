"""Utility functions for the Rykker Borgere project."""
from pathlib import Path
from datetime import datetime
import subprocess
import json
import hashlib

from docxtpl import DocxTemplate
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection

from itk_dev_shared_components.kmd_nova.nova_objects import JournalNote
from robot_framework import config


def fill_template(template_path: str, output_path: str, name: str, date: datetime, case_number: str) -> Path:
    """Fill a template with the given context."""
    context = {
        "Fornavn": name,
        "dato": date.strftime(format="%d/%m/%Y"),
        "Sagsnummer": case_number
    }
    doc = DocxTemplate(template_path)
    doc.render(context)
    doc.save(filename=output_path)
    return Path(output_path)


def convert_docx_to_pdf(path_to_docx: Path, tmpdir: str):
    """Convert a docx file to a PDF file."""
    subprocess.run(args=[config.PATH_TO_LIBREOFFICE, "--headless", "--convert-to", "pdf", "--outdir", tmpdir, str(path_to_docx)], check=True)
    return Path(tmpdir) / f"{path_to_docx.stem}.pdf"


def get_step(notes: list[JournalNote]) -> tuple[int, JournalNote]:
    """Get the next step number for a case."""
    highest_step = 0
    new_step = 0
    newest_note = None
    for note in notes:
        note_title = note.title
        if note_title.startswith(config.NOTE_PREFIX):
            highest_step = max(highest_step, int(note_title.split(config.NOTE_PREFIX)[1].strip()))
            new_step = highest_step + 1
            newest_note = note
    return new_step, newest_note


def mask_cpr(cpr: str) -> str:
    """Mask a CPR number for log output.

    Hides the date-of-birth (first 6 digits) and shows only the last 4 digits,
    e.g. "0101011234" -> "******-1234".
    """
    if not cpr or len(cpr) < 4:
        return "***********"
    return f"******-{cpr[-4:]}"


def encrypt_cpr(cpr: str, first_name: str) -> str:
    """Encrypt CPR and first name using SHA256 hashing.

    Args:
        cpr: CPR number of the citizen.
        first_name: First name of the citizen.

    Returns:
        Encrypted hash string to use as queue reference.
    """
    salted_data = f"{cpr}{first_name}"
    hash_obj = hashlib.sha256(salted_data.encode())
    return hash_obj.hexdigest()


def get_queue_element(  # pylint: disable=too-many-positional-arguments
        orchestrator_connection: OrchestratorConnection, queue_name: str, reference: str) -> dict | None:
    """Get a queue element by reference.

    Args:
        orchestrator_connection: Connection to OpenOrchestrator.
        queue_name: Name of the queue.
        reference: Reference key to look up.

    Returns:
        Queue element data as dict if found, None otherwise.
    """
    queue_elements = orchestrator_connection.get_queue_elements(queue_name, reference)
    if len(queue_elements) == 0:
        return None
    return json.loads(queue_elements[0].data) if queue_elements[0].data else None


def update_queue_element(  # pylint: disable=too-many-positional-arguments
        orchestrator_connection: OrchestratorConnection, queue_name: str, reference: str,
        digital_post: bool, nemsms: bool, case_uuid: str):
    """Update or create a queue element with registration status.

    Args:
        orchestrator_connection: Connection to OpenOrchestrator.
        queue_name: Name of the queue.
        reference: Reference key (encrypted CPR).
        digital_post: Digital Post registration status.
        nemsms: NemSMS registration status.
        case_uuid: UUID of the Nova case.
    """
    # Delete existing element if it exists
    queue_elements = orchestrator_connection.get_queue_elements(queue_name, reference)
    if len(queue_elements) > 0:
        orchestrator_connection.delete_queue_element(reference)

    # Create new element with updated data
    data = {
        "digital_post": digital_post,
        "nemsms": nemsms,
        "case_uuid": case_uuid
    }
    orchestrator_connection.create_queue_element(queue_name, reference=reference, data=json.dumps(data))
