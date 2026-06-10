"""Functions for interacting with Nova."""
import re
import urllib
import uuid
from typing import Literal, Any

import requests
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
from itk_dev_shared_components.kmd_nova import nova_notes, nova_cases, nova_documents
from itk_dev_shared_components.kmd_nova.nova_objects import Caseworker, Document, CaseParty

from robot_framework import config


def upload_document(nova_access: NovaAccess, document_path: str, document_title: str, case_id: str):
    """Upload a document to Nova and attach it to a case."""
    with open(document_path, 'rb') as file:
        document_id = nova_documents.upload_document(file, document_title, nova_access)
        nova_doc = Document(uuid=document_id, title=document_title, sensitivity="Følsomme", document_type="Udgående", description="Rykker sendt til borger omkring ukendt adresse.", approved=False)
        nova_documents.attach_document_to_case(case_id, nova_doc, nova_access)


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
            "participantRole": "Primær"
        },
        "caseClassification": {
            "kleNumber": {
                "code": kle_number
            }
        },
        "states": {
            "states": [
                {"progressState": "Opstaaet"},
                {"progressState": "Oplyst"},
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
        }
    }
    params = {"api-version": "2.0-Case"}
    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}
    url = urllib.parse.urljoin(nova_access.domain, "api/Case/GetList")

    response = requests.put(url, params=params, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    return response.json().get("cases", [])


def add_reminder_note(case_uuid: str, reminder_number: int, nova_access: NovaAccess,
                      caseworker: Caseworker = None, sent: bool = True) -> str:
    """Add a journal note to a case documenting a reminder letter.

    Args:
        case_uuid: The uuid of the case to add the note to.
        reminder_number: Which reminder this is (1, 2, 3, etc.).
        nova_access: The NovaAccess object used to authenticate.
        caseworker: The caseworker to attribute the note to. Defaults to config.CASEWORKER.
        sent: True if the letter was delivered via digital post; False if delivery was
              skipped because the citizen is not registered. When False, the note title is
              prefixed with "Ikke sendt: " and the body asks for manual follow-up.

    Returns:
        The uuid of the created journal note.
    """
    if caseworker is None:
        caseworker = config.CASEWORKER

    if sent:
        note_title = f"Rykker {reminder_number} sendt"
        note_text = f"Rykker {reminder_number} er blevet sendt til borgeren vedrørende ukendt adresse."
    else:
        note_title = f"Ikke sendt: Rykker {reminder_number}"
        note_text = (
            f"Rykker {reminder_number} blev IKKE sendt via digital post, da borgeren ikke er tilmeldt. "
            "Brevet er uploadet til sagen. Manuel opfølgning påkrævet."
        )

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
        note_text += f"\n\nÅrsag: {reason}"

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
    notes = nova_notes.get_notes(case_uuid, nova_access, 0, 500)

    latest_step = 0
    latest_date = None

    for note in notes:
        # Match both "Rykker X sendt" and "Ikke sendt: Rykker X sendt" — the latter is
        # added when the letter could not be delivered via digital post, but the step
        # counter must still advance so we don't retry the same reminder every run.
        match = re.match(r"^(?:Ikke sendt: )?Rykker (\d+) sendt$", note.title or "")
        if not match:
            continue
        step = int(match.group(1))
        if step > latest_step:
            latest_step = step
            latest_date = note.journal_date

    return (latest_step, latest_date)


def get_single_cpr_case_party(case: dict) -> CaseParty | None:
    """Return the single case party if exactly one exists and it's a CPR party; otherwise None."""
    parties = nova_cases._extract_case_parties(case)  # pylint: disable=protected-access
    if len(parties) != 1:
        return None
    party = parties[0]
    if getattr(party, "identification_type", None) != "CprNummer":
        return None
    return party


def get_latest_sms_info(case_uuid: str, nova_access: NovaAccess) -> str | None:
    """Return the ISO date of the latest "SMS sendt" note, or None if none found."""
    notes = nova_notes.get_notes(case_uuid, nova_access, 0, 500)
    latest_date = None
    for note in notes:
        if note.title and note.title.strip() == "SMS sendt":
            # Keep the latest by journal_date ordering (notes are typically returned newest first, but be safe)
            if latest_date is None or (note.journal_date and note.journal_date > latest_date):
                latest_date = note.journal_date
    return latest_date


def get_next_reminder_baseline(case: dict, nova_access: NovaAccess) -> tuple[int, str | None, int]:
    """Compute next reminder baseline and interval based on existing reminder notes.

    Returns a tuple of (step_sent, baseline_iso_date, interval_days) where:
    - step_sent: how many reminder letters have already been sent (>= 1 only). Parsed
      from journal notes titled "Rykker X sendt" or "Ikke sendt: Rykker X sendt" where
      X is an integer >= 1. The robot never creates a "Rykker 0" note — step 0 simply
      means no reminder has been sent yet.
    - baseline_iso_date: ISO date string to measure waiting time from for the NEXT step.
        * If step_sent == 0: the case's own caseDate (sagsdato) is used as anchor —
          first reminder is sent 14 days after the case was opened. Returns None if
          caseDate is missing from the payload (caller decides on a fallback).
        * If step_sent >= 1: the journal date of the latest "Rykker X" note.
    - interval_days: 14 when step_sent == 0; 30 for step_sent >= 1.
    """
    case_uuid = case["common"]["uuid"]
    step_sent, last_reminder_date = get_latest_reminder_info(case_uuid, nova_access)

    if step_sent == 0:
        case_date = case.get("caseAttributes", {}).get("caseDate")
        return step_sent, case_date, 14

    return step_sent, last_reminder_date, 30


def _build_caseworker_payload(caseworker: Caseworker) -> dict:
    """Helper function to build caseworker payload based on type."""
    return {
        "kspIdentity": {
            "fullName": caseworker.name,
            "racfId": caseworker.ident
        }
    }
