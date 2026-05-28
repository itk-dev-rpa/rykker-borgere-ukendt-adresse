"""Script for setting correct user for batch of NOVA cases. Used only once, saved for documentation."""
import os
import urllib
import uuid
import re

import requests
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection

from robot_framework.rykker_borgere import nova_functions
from robot_framework import config


# pylint: disable=duplicate-code
def get_cases(nova_access: NovaAccess, states: list[str] | None = None, start_date: str | None = None, end_date: str | None = None):
    """Get cases from Nova and return those matching the regex."""
    payload = {
        "common": {
            "transactionId": str(uuid.uuid4())
        },
        "caseAttributes": {
            "title": "Kat A",
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
    if states:
        payload["states"] = {}
        if start_date:
            payload["states"]["startFromDate"] = start_date
        if end_date:
            payload["states"]["endFromDate"] = end_date
        payload["states"]["states"] = [{"progressState": state} for state in states]
    params = {"api-version": "2.0-Case"}
    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}

    matching_cases = []
    more_cases = True
    url = urllib.parse.urljoin(nova_access.domain, "api/Case/GetList")
    start_row = 1
    while more_cases:
        paging = {
                "startRow": start_row,
                "numberOfRows": 500,
                "calculateTotalNumberOfRows": True
        }
        payload["paging"] = paging
        response = requests.put(url, params=params, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        more_cases = response.json()["pagingInformation"]['hasMoreRows']
        matching_cases.extend(response.json()["cases"])
        start_row += 500
    return matching_cases


if __name__ == "__main__":
    oc_connection = os.environ.get("OpenOrchestratorConnString")
    oc_encryption = os.environ.get("OpenOrchestratorKey")
    oc = OrchestratorConnection("Rykke Batch Job", oc_connection, oc_encryption, "", "")
    nova_connection = oc.get_credential("Nova API")
    nova_ac = NovaAccess(nova_connection.username, nova_connection.password)
    cases = get_cases(nova_ac, ["Opstaaet", "Oplyst", "Afgjort", "Bestilt", "Udfoert"])

    regex_match = re.compile(r"^Kat[.\s]*[A-Za-z](?!\d)", re.IGNORECASE)
    filtered_cases = [case for case in cases if regex_match.match(case['caseAttributes']['title'])]
    for case in filtered_cases:
        nova_functions.update_case(case["common"]["uuid"], nova_ac, new_caseworker=config.CASEWORKER)
        print(f"Updated case {case['caseAttributes']['title']}")
    print("done")
