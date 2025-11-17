"""Contains functions for interacting with Nova."""
import urllib
import uuid
from typing import Literal, Any

import requests

from itk_dev_shared_components.kmd_nova.nova_objects import Caseworker
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
from itk_dev_shared_components.kmd_nova import nova_notes


def get_cases(nova_access: NovaAccess):
    """Get a list of cases from Nova."""
    payload = {
        "common": {
            "transactionId": str(uuid.uuid4())
        },
        "caseAttributes": {
            "title": "Kat A",
        },
        "states": {
            "states": [
                {
                    "progressState": "Opstaaet"
                },
                {
                    "progressState": "Oplyst"
                },
                {
                    "progressState": "Afgjort"
                },
                {
                    "progressState": "Bestilt"
                },
                {
                    "progressState": "Udfoert"
                }
            ]
        },
        "caseGetOutput": {
            "caseAttributes": {
                "title": True,
            },
            "state": {
                "progressState": True,
                "activeCode": True
            },
            "numberOfDocuments": True
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
    """Get notes for a case."""
    start_row = 0
    row_batch = 500
    new_notes = nova_notes.get_notes(case_id, nova_access, start_row, row_batch)
    all_notes = list(new_notes)
    while len(new_notes) > 0:
        start_row += row_batch
        new_notes = nova_notes.get_notes(case_id, nova_access, start_row, row_batch)
        all_notes.extend(new_notes)
    return all_notes


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
    if caseworker.type == 'user':
        return {
            "kspIdentity": {
                "racfId": caseworker.ident,
                "fullName": caseworker.name
            }
        }
    if caseworker.type == 'group':
        return {
            "losIdentity": {
                "administrativeUnitId": caseworker.ident,
                "fullName": caseworker.name
            }
        }
    raise ValueError(f"Unknown caseworker type: {caseworker.type}")
