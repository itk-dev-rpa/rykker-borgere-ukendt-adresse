"""This module contains configuration constants used across the framework"""
from datetime import datetime
from pathlib import Path

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
SQL_QUERY = "SELECT * FROM [DWH].[Mart].[AdresseAktuel] WHERE Vejkode = 9901 AND Myndighed = 751 AND Alder > 17"

# Connection string for the DWH SQL Server.
# Driver and server can be overridden by drift without code change.
SQL_CONN_STRING = "Driver={ODBC Driver 17 for SQL Server};Server=FaellesSQL;Trusted_Connection=yes;"

# Reminder timing (in days)
REMINDER_INITIAL_INTERVAL_DAYS = 14   # From case creation date (caseDate) to Rykker 1
REMINDER_FOLLOWUP_INTERVAL_DAYS = 30  # Between subsequent reminders
SUPPRESS_SMS_WINDOW_DAYS = 7          # Suppress NemSMS-change SMS within N days of next reminder
LETTER_DEADLINE_DAYS = 30             # Deadline written into the reminder letter

# Reminder notes ("Rykker X sendt") dated before go-live are ignored by
# get_latest_reminder_info. During live testing, undeletable/unrenamable test notes
# ("Rykker 0/1 sendt") were created on real cases; this cutoff ensures they are not
# counted. No real reminders were sent before this date. Set to None to disable filtering.
REMINDER_NOTE_CUTOFF: datetime | None = datetime(2026, 7, 7)

# Retry strategy for transient Service Platform errors in check_registration_status.
# REGISTRATION_CHECK_ATTEMPTS counts the first try plus retries; a fixed delay
# is applied between attempts.
REGISTRATION_CHECK_ATTEMPTS = 3
REGISTRATION_CHECK_RETRY_DELAY = 2  # seconds between attempts

# Backoffice notifications: a single aggregated email per robot run when any citizen
# matches the alert criteria (no case found, or step >= HIGH_STEP_THRESHOLD).
BACKOFFICE_RECIPIENT = "kontroladresse@mkb.aarhus.dk"
HIGH_STEP_THRESHOLD = 24

KEYVAULT_CREDENTIALS = "Keyvault"
KEYVAULT_URI = "Keyvault URI"
KEYVAULT_PATH = "Digital_Post_Ukendt_Adresse"
EVENT_LOG_CONN = "Event Log"
NOTE_PREFIX = "Rykker Step "

# Optional path to a JSON file used in dry-run to simulate previous state
# Structure example:
# {
#   "queue": {"<encrypted_ref>": {"digital_post": true, "nemsms": false, "case_uuid": "..."}},
#   "nova_reminders": {"<case_uuid>": {"latest_step": 1, "last_date": "2026-03-31T09:00:00"}}
# }
DRY_RUN_STATE_FILE: str | None = None

CASEWORKER = Caseworker(
    name='AZRPA78 - Rpabruger Rpa78 - MÅ IKKE SLETTES RITM0283472',
    ident='AZRPA78',
    uuid='a577c0a2-a131-43a5-b4e6-b4f5bb75028f',
    type='user'
)

PATH_TO_LIBREOFFICE = "C:/Program Files/LibreOffice/program/soffice.exe"
LIBREOFFICE_TIMEOUT_SECONDS = 60

MAX_LETTER_TEMPLATE_STEP = 3

# Bundled assets are resolved against this file's location so paths work regardless
# of the process working directory (the same approach initialize.py uses for the
# dry-run state file). config.py lives in robot_framework/, so parent is that dir.
TEMPLATES_DIR = Path(__file__).resolve().parent / "rykker_borgere" / "templates"
TMP_DIR = Path(__file__).resolve().parent / "tmp"
