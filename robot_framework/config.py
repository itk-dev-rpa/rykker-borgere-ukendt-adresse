"""This module contains configuration constants used across the framework"""
from itk_dev_shared_components.kmd_nova.nova_objects import Caseworker

# The number of times the robot retries on an error before terminating.
MAX_RETRY_COUNT = 3

# Whether the robot should be marked as failed if MAX_RETRY_COUNT is reached.
FAIL_ROBOT_ON_TOO_MANY_ERRORS = True

# Error screenshot config
SMTP_SERVER = "smtp.adm.aarhuskommune.dk"
SMTP_PORT = 25
SCREENSHOT_SENDER = "robot@friend.dk"

# Constant/Credential names
ERROR_EMAIL = "Error Email"


# Queue specific configs
# ----------------------

# The name of the job queue (if any)
QUEUE_NAME = None

# The limit on how many queue elements to process
MAX_TASK_COUNT = 100

# ----------------------
CVR = "55133018"

KEYVAULT_CREDENTIALS = "Keyvault"
KEYVAULT_URI = "Keyvault URI"
KEYVAULT_PATH = "NOT_ORDERED_YET" # TODO: Get this
EVENT_LOG_CONN = "Event Log"
NOTE_PREFIX = "Rykker Step "

CASEWORKER = Caseworker(
    name='Rpabruger Rpa75 - MÅ IKKE SLETTES RITM0283472',
    ident='azrpa75',
    uuid='2382680f-58cd-4f6d-90fd-23e4ce0180ae',
    type='group'
)

PATH_TO_LIBREOFFICE = "C:/Program Files/LibreOffice/program/soffice.exe"
