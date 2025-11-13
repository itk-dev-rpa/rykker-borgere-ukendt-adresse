from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from robot_framework import config
from hvac import Client
from python_serviceplatformen.authentication import KombitAccess

def get_kombit_access(orchestrator_connection: OrchestratorConnection):
    # Access Keyvault
    vault_auth = orchestrator_connection.get_credential(config.KEYVAULT_CREDENTIALS)
    vault_uri = orchestrator_connection.get_constant(config.KEYVAULT_URI).value
    vault_client = Client(vault_uri)
    token = vault_client.auth.approle.login(role_id=vault_auth.username, secret_id=vault_auth.password)
    vault_client.token = token['auth']['client_token']

    # Get certificate
    read_response = vault_client.secrets.kv.v2.read_secret_version(mount_point='rpa', path=config.KEYVAULT_PATH,
                                                                   raise_on_deleted_version=True)
    certificate = read_response['data']['data']['cert']

    # Because KombitAccess requires a file, we save and delete the certificate after we use it
    certificate_path = "certificate.pem"
    with open(certificate_path, 'w', encoding='utf-8') as cert_file:
        cert_file.write(certificate)

    # Prepare access to the service platform
    return KombitAccess(config.CVR, certificate_path)