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

# The name of the job queue for tracking registration status
QUEUE_NAME = "RykkerBorgereUkendtAdresse"

# The limit on how many queue elements to process
MAX_TASK_COUNT = 100

# ----------------------
CVR = "55133018"

# KLE number for "Folkeregistrering i almindelighed"
KLE_NUMBER = "23.05.00"

# SQL query for finding citizens with unknown address
SQL_QUERY = "SELECT * FROM [DWH].[Mart].[AdresseAktuel] WHERE Vejkode = 9901 AND Myndighed = 751"

KEYVAULT_CREDENTIALS = "Keyvault"
KEYVAULT_URI = "Keyvault URI"
KEYVAULT_PATH = "Digital_Post_Ukendt_Adresse"
EVENT_LOG_CONN = "Event Log"
NOTE_PREFIX = "Rykker Step "

CASEWORKER = Caseworker(
    name='Rpabruger Rpa94 - MÅ IKKE SLETTES RITM0',
    ident='AZRPA94',
    uuid='a577c0a2-a131-43a5-b4e6-b4f5bb75028f',
    type='group'
)

PATH_TO_LIBREOFFICE = "C:/Program Files/LibreOffice/program/soffice.exe"
