"""Functions for interacting with Nova."""
import urllib
import uuid
from typing import Literal, Any

import requests
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
from itk_dev_shared_components.kmd_nova import nova_notes
from itk_dev_shared_components.kmd_nova.nova_objects import Caseworker

from robot_framework import config


def get_cases(nova_access: NovaAccess):
    """Get all cases from Nova."""
    payload = {
        "common": {
            "transactionId": str(uuid.uuid4())
        },
        "caseworker": config.CASEWORKER,
        "states": {
            "states": [
                {
                    "progressState": "Opstaaet"
                },
            ]
        },
        "caseGetOutput": {
            "caseAttributes": {
                "title": True,
                "caseDate": True,
            },
            "state": {
                "progressState": True,
                "activeCode": True,
            },
            "numberOfDocuments": True,
        },
        "paging": {
            "startRow": 1,
            "numberOfRows": 500,
            "calculateTotalNumberOfRows": True
        }
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


def get_notes(nova_access: NovaAccess, case_id: str):
    """Get all notes from a case."""
    start_row = 0
    row_batch = 500
    new_notes = nova_notes.get_notes(case_id, nova_access, start_row, row_batch)
    all_notes = list(new_notes)
    while len(new_notes) > 0:
        start_row += row_batch
        new_notes = nova_notes.get_notes(case_id, nova_access, start_row, row_batch)
        all_notes.extend(new_notes)
    return all_notes


def upload_document(nova_access: NovaAccess, document_path: str, document_title: str, case_id: str):
    """Upload a document to Nova and attach it to a case."""
    document_id = _upload_document_file(nova_access, document_path)
    _import_document_to_case(nova_access, case_id, document_id, document_title)


def _upload_document_file(nova_access: NovaAccess, document_path: str):
    """Put a document in the bucket of Nova."""
    with open(document_path, 'rb') as file:
        transaction_id = str(uuid.uuid4())
        document_id = str(uuid.uuid4())
        url = urllib.parse.urljoin(nova_access.domain, f"api/Document/UploadFile/{transaction_id}/{document_id}")
        params = {"api-version": "2.0-Case"}
        headers = {'Content-Type': 'application/octet-stream', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}
        response = requests.put(url, params=params, headers=headers, data=file, timeout=60)
        response.raise_for_status()
        return document_id


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
    headers = {'Content-Type': 'application/octet-stream', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}
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

def _build_caseworker_payload(caseworker: Caseworker) -> dict:
    """Helper function to build caseworker payload based on type."""
    return {
        "kspIdentity": {
            "fullName": caseworker.name,
            "racfId": caseworker.ident
        }
    }
