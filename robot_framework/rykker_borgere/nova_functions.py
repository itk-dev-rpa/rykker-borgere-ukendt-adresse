"""Functions for interacting with Nova."""
import urllib
import uuid
from typing import Literal, Any

import requests
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
from itk_dev_shared_components.kmd_nova import nova_notes, nova_cases, nova_documents
from itk_dev_shared_components.kmd_nova.nova_objects import Caseworker, Document

from robot_framework import config


def get_cases(nova_access: NovaAccess):
    """Get all cases from Nova."""
    payload = {
        "common": {
            "transactionId": str(uuid.uuid4())
        },
        "caseworker": _build_caseworker_payload(config.CASEWORKER),
        "states": {
            "states": [
                {
                    "progressState": "Opstaaet"
                },
            ]
        },
        "caseGetOutput": {
            "caseAttributes": {
                "userFriendlyCaseNumber": True,
                "title": True,
                "caseDate": True,
            },
            "caseParty": {
                "identificationType": True,
                "identification": True,
                "participantRole": True,
                "name": True,
                "index": True
            },
            "state": {
                "progressState": True,
                "activeCode": True,
            },
            "numberOfDocuments": True,
            "numberOfJournalNotes": True
        },
        "paging": {
            "startRow": 1,
            "numberOfRows": 500,
            "calculateTotalNumberOfRows": True
        },
    }
    params = {"api-version": "2.0-Case"}
    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}

    cases = []
    more_cases = True
    url = urllib.parse.urljoin(nova_access.domain, "api/Case/GetList")
    start_row = 1
    row_batch = 500
    while more_cases:
        paging = {
                "startRow": start_row,
                "numberOfRows": row_batch,
                "calculateTotalNumberOfRows": True
        }
        payload["paging"] = paging
        response = requests.put(url, params=params, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        more_cases = response.json()["pagingInformation"]['hasMoreRows']
        cases.extend(response.json()["cases"])
        start_row += row_batch
    return cases


def get_test_case(nova_access: NovaAccess):
    """Get all cases from Nova as dictionaries."""
    params = {"api-version": "2.0-Case"}
    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}
    payload = nova_cases._create_payload(case_uuid="50f6b040-613d-47d9-8c5e-eccbbef3803c")  # pylint: disable=protected-access
    url = urllib.parse.urljoin(nova_access.domain, "api/Case/GetList")
    response = requests.put(url, params=params, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["cases"][0]


def get_notes(nova_access: NovaAccess, case_id: str, expected_notes: int = 0):
    """Get all notes from a case."""
    start_row = 0
    row_batch = 500
    all_notes = []
    while len(all_notes) < expected_notes:
        new_notes = nova_notes.get_notes(case_id, nova_access, start_row, row_batch)
        all_notes.extend(new_notes)
        start_row += row_batch
    return all_notes


def upload_document(nova_access: NovaAccess, document_path: str, document_title: str, case_id: str):
    """Upload a document to Nova and attach it to a case."""
    with open(document_path, 'rb') as file:
        document_id = nova_documents.upload_document(file,document_title, nova_access)
        nova_doc = Document(uuid=document_id, title=document_title, sensitivity="Følsomme", document_type="Udgående", description="Rykker sendt til borger omkring ukendt adresse.", approved=False)
        nova_documents.attach_document_to_case(case_id, nova_doc, nova_access)


def _import_document_to_case(nova_access: NovaAccess, case_id: str, document_id: str, document_title: str):
    """Set a document to a case."""
    payload = {
        "common": {
            "transactionId": str(uuid.uuid4()),
            "uuid": document_id
        },
        "caseUuid": case_id,
        "title": document_title,
        "description": "Rykker sendt til borger omkring ukendt adresse."
    }
    url = urllib.parse.urljoin(nova_access.domain, "api/Document/Import/")
    params = {"api-version": "2.0-Case"}
    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}
    response = requests.post(url, params=params, headers=headers, json=payload, timeout=60)
    response.raise_for_status()


def update_case(case_uuid: str, nova_access: NovaAccess,
                new_state: Literal["Opstaaet", "Oplyst", "Afgjort", "Bestilt", "Udfoert", "Afsluttet"] | None = None,
                new_caseworker: Caseworker | None = None,):
    """Set the state of an existing case.

    Args:
        case_uuid: The uuid of the case.
        nova_access: The NovaAccess object used to authenticate.
        new_state: The new state of the case. (Optional)
        new_caseworker: The new caseworker of the case. (Optional)
    """
    url = urllib.parse.urljoin(nova_access.domain, "api/Case/Update")
    params = {"api-version": "2.0-Case"}

    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}

    payload: dict[str, Any] = {
        "common": {
            "transactionId": str(uuid.uuid4()),
            "uuid": case_uuid
        },
    }
    if new_state:
        payload["state"] = new_state
    if new_caseworker:
        payload['caseworker'] = _build_caseworker_payload(new_caseworker)

    response = requests.patch(url, params=params, headers=headers, json=payload, timeout=60)
    response.raise_for_status()


def get_cases_by_kle_and_cpr(nova_access: NovaAccess, kle_number: str, cpr: str):
    """Get open cases for a specific CPR with a specific KLE number.

    Args:
        nova_access: The NovaAccess object used to authenticate.
        kle_number: The KLE number to filter on (e.g., "23.05.00").
        cpr: The CPR number of the citizen.

    Returns:
        List of case dictionaries matching the criteria.
    """
    payload = {
        "common": {
            "transactionId": str(uuid.uuid4())
        },
        "caseParty": {
            "identificationType": "CprNummer",
            "identification": cpr,
            "participantRole": "Primaer"
        },
        "kle": {
            "number": kle_number
        },
        "states": {
            "states": [
                {"progressState": "Opstaaet"},
                {"progressState": "Oplyst"},
                {"progressState": "Afgjort"},
                {"progressState": "Bestilt"},
                {"progressState": "Udfoert"}
            ]
        },
        "caseGetOutput": {
            "caseAttributes": {
                "userFriendlyCaseNumber": True,
                "title": True,
                "caseDate": True,
            },
            "caseParty": {
                "identificationType": True,
                "identification": True,
                "participantRole": True,
                "name": True,
                "index": True
            },
            "state": {
                "progressState": True,
                "activeCode": True,
            },
            "numberOfDocuments": True,
            "numberOfJournalNotes": True
        },
        "paging": {
            "startRow": 1,
            "numberOfRows": 100,
            "calculateTotalNumberOfRows": True
        },
    }
    params = {"api-version": "2.0-Case"}
    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}
    url = urllib.parse.urljoin(nova_access.domain, "api/Case/GetList")

    response = requests.put(url, params=params, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    return response.json().get("cases", [])


def add_reminder_note(case_uuid: str, reminder_number: int, nova_access: NovaAccess, caseworker: Caseworker = None) -> str:
    """Add a journal note to a case documenting that a reminder letter has been sent.

    Args:
        case_uuid: The uuid of the case to add the note to.
        reminder_number: Which reminder this is (1, 2, 3, etc.).
        nova_access: The NovaAccess object used to authenticate.
        caseworker: The caseworker to attribute the note to. Defaults to config.CASEWORKER.

    Returns:
        The uuid of the created journal note.
    """
    if caseworker is None:
        caseworker = config.CASEWORKER

    note_title = f"Rykker {reminder_number} sendt"
    note_text = f"Rykker {reminder_number} er blevet sendt til borgeren vedrørende ukendt adresse."

    return nova_notes.add_text_note(case_uuid, note_title, note_text, caseworker, approved=False, nova_access=nova_access)


def add_sms_note(case_uuid: str, nova_access: NovaAccess, reason: str = None, caseworker: Caseworker = None) -> str:
    """Add a journal note to a case documenting that SMS has been sent.

    Args:
        case_uuid: The uuid of the case to add the note to.
        nova_access: The NovaAccess object used to authenticate.
        reason: Optional reason for sending the SMS (e.g., "NemSMS-status aendret fra ikke-tilmeldt til tilmeldt").
        caseworker: The caseworker to attribute the note to. Defaults to config.CASEWORKER.

    Returns:
        The uuid of the created journal note.
    """
    if caseworker is None:
        caseworker = config.CASEWORKER

    note_title = "SMS sendt"
    note_text = "SMS er blevet sendt til borgeren vedrørende ukendt adresse."
    if reason:
        note_text += f"\n\nAarsag: {reason}"

    return nova_notes.add_text_note(case_uuid, note_title, note_text, caseworker, approved=False, nova_access=nova_access)


def get_latest_reminder_info(case_uuid: str, nova_access: NovaAccess) -> tuple[int, str | None]:
    """Get information about the latest reminder sent for a case.

    Parses journal notes to find the most recent reminder note created by the robot.
    Looks for notes with titles matching "Rykker X sendt".

    Args:
        case_uuid: The uuid of the case to check.
        nova_access: The NovaAccess object used to authenticate.

    Returns:
        A tuple of (step_number, last_reminder_date) where:
        - step_number is 0 if no reminders have been sent, otherwise the number from the latest reminder
        - last_reminder_date is None if no reminders sent, otherwise ISO format date string
    """
    notes = get_notes(nova_access, case_uuid, expected_notes=0)

    latest_step = 0
    latest_date = None

    for note in notes:
        # Look for notes with title pattern "Rykker X sendt"
        if note.title and note.title.startswith("Rykker ") and note.title.endswith(" sendt"):
            try:
                # Extract the step number from the title
                step_str = note.title.replace("Rykker ", "").replace(" sendt", "")
                step = int(step_str)

                # Keep track of the highest step number found
                if step > latest_step:
                    latest_step = step
                    latest_date = note.journal_date
            except ValueError:
                # Skip notes that don't match the expected format
                continue

    return (latest_step, latest_date)


def _build_caseworker_payload(caseworker: Caseworker) -> dict:
    """Helper function to build caseworker payload based on type."""
    return {
        "kspIdentity": {
            "fullName": caseworker.name,
            "racfId": caseworker.ident
        }
    }
