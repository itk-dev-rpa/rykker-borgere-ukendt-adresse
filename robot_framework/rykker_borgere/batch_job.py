import os
import requests
import urllib
import uuid
import re

from robot_framework.rykker_borgere import nova_functions
from robot_framework import config
from itk_dev_shared_components.kmd_nova.authentication import  NovaAccess
from OpenOrchestrator.orchestrator_connection.connection import  OrchestratorConnection


def get_cases(nova_access: NovaAccess):
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
        cases.extend(response.json()["cases"])
        start_row += 500
    return cases


if __name__ == "__main__":
    oc_connection = os.environ.get("OpenOrchestratorConnString")
    oc_encryption = os.environ.get("OpenOrchestratorKey")
    oc = OrchestratorConnection("Rykke Batch Job", oc_connection, oc_encryption, "", "")
    nova_connection = oc.get_credential("Nova API")
    nova_ac = NovaAccess(nova_connection.username, nova_connection.password)
    cases = get_cases(nova_ac)

    regex_match = re.compile(r"^Kat[.\s]*[A-Z](?!\d)", re.IGNORECASE)
    filtered_cases = []
    for case in cases:
        case_title = case['caseAttributes']['title']
        if regex_match.match(case_title):
            filtered_cases.append(case)
    for case in filtered_cases:
        nova_functions.update_case(case, nova_ac, config.CASEWORKER)
    print("done")