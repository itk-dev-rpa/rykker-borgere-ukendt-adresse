# Rykkerforløb på borgere med ukendt adresse

This is an RPA built for use with [OpenOrchestrator](https://github.com/itk-dev-rpa/OpenOrchestrator).
The robot identifies citizens registered with an unknown address, sends NemSMS
notifications and reminder letters via Digital Post (Serviceplatformen), and
tracks each citizen's status across runs in an OpenOrchestrator queue and as
notes on the corresponding Nova case.

## How the process works

For every citizen returned by the SQL query in [config.SQL_QUERY](robot_framework/config.py):

1. Look up the citizen's case in Nova by KLE number and CPR.
2. Read Digital Post / NemSMS registration status from Serviceplatformen.
3. Compare against the previous status stored in the OpenOrchestrator queue.
   - If NemSMS went from **not registered → registered** (and we are not within
     the 7-day window before the next reminder), send 2 informational SMS
     (Danish + English).
4. Determine where the case is in the reminder schedule:
   - No reminder note yet → record a "Rykker 0" baseline note.
   - Otherwise → if 14 days have passed since baseline (or 30 days since the
     latest reminder), send the next reminder letter.
5. Persist the new status in the queue.

All side effects (SMS, queue updates, reminder letters, Nova notes) flow
through an **action sink** abstraction. In production, [`RealActionsSink`](robot_framework/sinks.py)
performs the real calls; in dry-run, [`DryRunSink`](robot_framework/sinks.py)
records what would have happened and prints a final report.

## Quick start

1. Assign a Nova RPA caseworker ID to this robot — see
   [config.CASEWORKER](robot_framework/config.py).
2. Provide credentials in OpenOrchestrator:
   - `Nova API` (credential)
   - `Keyvault` (credential, used by Service Platform)
   - `Keyvault URI` (constant)
   - `Event Log` (constant)
   - `Error Email` (constant)
3. Configure the SQL connection in [config.SQL_CONN_STRING](robot_framework/config.py)
   (defaults to `FaellesSQL` with ODBC Driver 17).
4. Set up the RPA process in OpenOrchestrator and watch the robot run.

## Configuration

Key constants live in [robot_framework/config.py](robot_framework/config.py):

| Constant | Purpose |
|---|---|
| `SQL_CONN_STRING` / `SQL_QUERY` | DWH connection + query for citizens with unknown address |
| `KLE_NUMBER` | Folkeregistrering KLE used to find Nova cases |
| `QUEUE_NAME` | OpenOrchestrator queue used to track per-citizen status |
| `REMINDER_INITIAL_INTERVAL_DAYS` (14) | Wait between Rykker 0 baseline and Rykker 1 |
| `REMINDER_FOLLOWUP_INTERVAL_DAYS` (30) | Wait between subsequent reminders |
| `SUPPRESS_SMS_WINDOW_DAYS` (7) | Don't send NemSMS-change SMS within N days of next reminder |
| `LETTER_DEADLINE_DAYS` (30) | Deadline written into the reminder letter |
| `DRY_RUN_STATE_FILE` | Optional path to a JSON file with simulated state for dry-run |

## Dry-run testing

The robot supports a dry-run mode that performs no side effects: no SMS, no
Digital Post, no queue updates, no Nova notes. Instead it logs what it *would*
have done and prints a summary report at the end.

### Enabling dry-run

Dry-run is activated in [linear_framework.main()](robot_framework/linear_framework.py)
via either of:

- **Environment variable** (highest priority): `DRY_RUN=true`
- **Code flag**: set `DRY_RUN = True` in [config.py](robot_framework/config.py)

When active, [`initialize.activate_dryrun()`](robot_framework/initialize.py)
loads a `.env` file (if present) and constructs a `DryRunSink`.

### Running a dry-run locally (recommended for dev)

For quick pre-deployment verification without going through the
OpenOrchestrator UI, run [tests/dryrun_local.py](tests/dryrun_local.py):

```
.venv\Scripts\python.exe tests\dryrun_local.py
```

The script:

- Loads `OpenOrchestratorConnString` and `OpenOrchestratorKey` from a `.env`
  file in the project root (or environment variables).
- Builds a `DryRunSink` via [`activate_dryrun`](robot_framework/initialize.py)
  (also loads `DRY_RUN_STATE_FILE` if set).
- Calls `process.process()` end-to-end against the real Nova / Kombit /
  OpenOrchestrator connections — only the *write* operations are skipped.

Optional: simulate previous state with `--state`:

```
.venv\Scripts\python.exe tests\dryrun_local.py --state mock_state.json
```

The script lives in `tests/` for proximity but is not collected by pytest
(only `test_*.py` is collected).

### Running a dry-run from OpenOrchestrator

For full end-to-end verification in the OpenOrchestrator environment:

1. In OpenOrchestrator, edit the trigger for this robot and add `DRY_RUN=true`
   to the environment, OR temporarily set `DRY_RUN = True` in `config.py`
   and deploy.
2. Trigger the robot manually.
3. Inspect the logs — you will see `DRY-RUN MODE AKTIVERET` followed by a
   detailed report ("DRY-RUN RAPPORT") listing every SMS, reminder, queue
   update, and Nova note that *would* have been performed.

> Note: dry-run still requires valid Nova and Kombit credentials, since
> the robot reads case data and registration status to decide what *would*
> happen. Only the write operations are skipped.

### Simulating previous state for dry-run

To dry-run scenarios where citizens have already been processed before
(e.g. "what happens 15 days after a Rykker 0 baseline?"), point
`DRY_RUN_STATE_FILE` at a JSON file:

```json
{
  "queue": {
    "<encrypted_ref>": {"digital_post": true, "nemsms": false, "case_uuid": "..."}
  },
  "nova_reminders": {
    "<case_uuid>": {"latest_step": 1, "last_date": "2026-03-31T09:00:00"}
  }
}
```

Set the path either via:

- Environment variable: `DRY_RUN_STATE_FILE=path/to/state.json`
- Or [config.DRY_RUN_STATE_FILE](robot_framework/config.py)

Relative paths are resolved against `robot_framework/`.

## Tests

Unit tests live in [tests/](tests) and use pytest with monkeypatched
external dependencies (Nova, Service Platform, queue, event log, datetime):

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

Coverage focuses on the per-citizen logic in `handle_citizen` and `handle_case`:
baseline establishment, reminder timing windows, NemSMS status-change SMS
(triggered, suppressed, and not-applicable cases), early-returns when no case
is found or when registration check fails, and the `mask_cpr` helper.

The outer `process()` orchestration (SQL fetch, citizen loop, batch hooks)
is not unit-tested — verify it via dry-run in OpenOrchestrator before
go-live.

## Project structure

```
robot_framework/
├── __main__.py              # Entry point: invokes linear_framework.main()
├── linear_framework.py      # Run-loop, retry, dry-run wiring
├── initialize.py            # Startup hooks + activate_dryrun()
├── reset.py                 # Cleanup between retries
├── config.py                # Constants
├── process.py               # process(), handle_citizen(), handle_case()
├── sinks.py                 # DryRunSink, RealActionsSink
├── exceptions.py
└── rykker_borgere/
    ├── nova_functions.py
    ├── service_platform_functions.py
    └── util.py              # encrypt_cpr, mask_cpr, fill_template, ...

tests/
├── conftest.py              # Fixtures: fixed_now, fake_case, mocks
├── test_process.py          # 13 tests covering reminder + SMS logic
└── dryrun_local.py          # Dev script for end-to-end dry-run (not a pytest)
```

## Requirements

- Python 3.11+
- OpenOrchestrator 2.x
- itk-dev-shared-components 2.x
- hvac 2.x
- itk_dev_event_log 1.x
- ODBC Driver 17 for SQL Server (or update `config.SQL_CONN_STRING`)

## Linting and Github Actions

This template is set up with flake8 and pylint linting in Github Actions.
The workflow triggers on push and is defined in
[.github/workflows/Linting.yml](.github/workflows/Linting.yml).
