"""Functions for communicating with the Service Platform."""
import base64
import time
from pathlib import Path

from hvac import Client
from python_serviceplatformen.authentication import KombitAccess
from python_serviceplatformen import digital_post
from python_serviceplatformen.models import message
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from requests.exceptions import HTTPError, ConnectionError as RequestsConnectionError, Timeout

from robot_framework import config
from robot_framework.rykker_borgere import util


def get_kombit_access(orchestrator_connection: OrchestratorConnection):
    """Get Kombit access credentials."""
    # Access Keyvault
    certificate_path = "certificate.pem"
    vault_auth = orchestrator_connection.get_credential(config.KEYVAULT_CREDENTIALS)
    vault_uri = orchestrator_connection.get_constant(config.KEYVAULT_URI).value
    vault_client = Client(vault_uri)
    token = vault_client.auth.approle.login(role_id=vault_auth.username, secret_id=vault_auth.password)
    vault_client.token = token['auth']['client_token']

    # Get certificate
    read_response = vault_client.secrets.kv.v2.read_secret_version(mount_point='rpa', path=config.KEYVAULT_PATH,
                                                                   raise_on_deleted_version=True)
    certificate = read_response['data']['data']['cert']

    with open(certificate_path, 'w', encoding='utf-8') as cert_file:
        cert_file.write(certificate)

    # Prepare access to the service platform
    return KombitAccess(config.CVR, certificate_path)


def send_digital_post(kombit_access: KombitAccess, file_path: str, recipient_cpr: str):
    """Send digital post to recipient."""
    if not digital_post.is_registered(recipient_cpr, "digitalpost", kombit_access):
        return False

    sender = message.Sender(
        senderID=config.CVR, idType="CVR", label="Rykker", attentionData=None, contactPoint=None
    )
    recipient = message.Recipient(
        recipientID=recipient_cpr, idType="CPR", label="Rykker", attentionData=None, contactPoint=None
    )
    file_path = Path(file_path)
    with open(file_path, "rb") as file:
        file_content = base64.b64encode(file.read()).decode("utf-8")
        send_file = message.File(encodingFormat="UTF-8", filename=str(file_path.name), language="da", content=file_content)
        msg = message.create_digital_post_with_main_document("Rykker for adresseændring", sender, recipient, (send_file,))
        digital_post.send_message("Digital Post", msg, kombit_access)
    return True


def send_sms(kombit_access: KombitAccess, recipient_cpr: str, language: str = "da"):
    """Send SMS to recipient in specified language.

    Args:
        kombit_access: KombitAccess object for authentication.
        recipient_cpr: CPR number of the recipient.
        language: Language code ("da" or "en"). Defaults to "da".

    Returns:
        True if SMS was sent successfully, False if recipient is not registered for NemSMS.
    """
    if not digital_post.is_registered(recipient_cpr, "nemsms", kombit_access):
        return False
    recipient = message.Recipient(
        recipientID=recipient_cpr, idType="CPR"
    )
    sender = message.Sender(
        senderID=config.CVR, idType="CVR", label="Aarhus Kommune"
    )

    # Load appropriate SMS text based on language
    sms_file = util.TEMPLATES_DIR / ("sms_text_da.txt" if language == "da" else "sms_text_en.txt")
    with open(sms_file, "r", encoding="utf-8") as file:
        sms_text = file.read()

    msg = message.create_nemsms("Rykker for adresseændring", sms_text, sender, recipient)
    digital_post.send_message("NemSMS", msg, kombit_access)
    return True


def check_registration_status(cpr: str, kombit_access: KombitAccess) -> tuple[bool, bool]:
    """Check Digital Post and NemSMS registration status for a citizen.

    Makes up to `config.REGISTRATION_CHECK_ATTEMPTS` attempts on transient errors
    (5xx, ConnectionError, Timeout), with a fixed delay between attempts.
    4xx errors are NOT retried — they indicate auth/validation problems that won't
    resolve by waiting, so the HTTPError is re-raised immediately.

    Args:
        cpr: CPR number of the citizen.
        kombit_access: KombitAccess object for authentication.

    Returns:
        A tuple of (digital_post_registered, nemsms_registered).

    Raises:
        HTTPError: 4xx response, or persistent failure after retries are exhausted.
        RequestsConnectionError, Timeout: persistent network failure after retries.
    """
    attempts = config.REGISTRATION_CHECK_ATTEMPTS
    for attempt in range(attempts):
        try:
            return (
                digital_post.is_registered(cpr, "digitalpost", kombit_access),
                digital_post.is_registered(cpr, "nemsms", kombit_access),
            )
        except HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            client_error = status is not None and 400 <= status < 500
            if client_error or attempt == attempts - 1:
                raise  # 4xx won't resolve on retry; otherwise attempts are exhausted
        except (RequestsConnectionError, Timeout):
            if attempt == attempts - 1:
                raise
        time.sleep(config.REGISTRATION_CHECK_RETRY_DELAY)

    raise RuntimeError("check_registration_status: retry loop exhausted")
