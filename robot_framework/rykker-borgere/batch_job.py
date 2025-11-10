import os
import requests
import urllib
import uuid

from itk_dev_shared_components.kmd_nova import nova_cases, nova_documents
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

    url = urllib.parse.urljoin(nova_access.domain, "api/Case/GetList")
    params = {"api-version": "2.0-Case"}

    headers = {'Content-Type': 'application/json', 'Authorization': f"Bearer {nova_access.get_bearer_token()}"}

    response = requests.put(url, params=params, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    print(response.json()["pagingInformation"]['totalNumberOfRows'])
    return response.json()["cases"]


if __name__ == "__main__":
    oc_connection = os.environ.get("OpenOrchestratorConnString")
    oc_encryption = os.environ.get("OpenOrchestratorKey")
    oc = OrchestratorConnection("Rykke Batch Job", oc_connection, oc_encryption, "", "")
    nova_connection = oc.get_credential("Nova API")
    nova_ac = NovaAccess(nova_connection.username, nova_connection.password)
    cases = get_cases(nova_ac)


