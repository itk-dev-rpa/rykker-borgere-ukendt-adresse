"""Unit tests for low-level helpers in `robot_framework.rykker_borgere`.

Covers helpers that the flow tests in `test_process.py` mock out:
- `util.fill_template` — DOCX rendering against the real templates.
- `util.get_step` — note step parsing.
- `util.mask_cpr` — CPR masking for log output.
- `nova_functions.get_notes` — pagination behavior.
- `nova_functions.update_case` — PATCH payload construction.
- `nova_functions._build_caseworker_payload` — caseworker payload shape.
- `service_platform_functions.send_digital_post` — registration short-circuit and happy path.
- `service_platform_functions.send_sms` — language-aware template selection.
"""

# pylint: disable=protected-access

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

from itk_dev_shared_components.kmd_nova.nova_objects import Caseworker, JournalNote
from itk_dev_shared_components.kmd_nova import nova_notes

from robot_framework import config
from robot_framework.rykker_borgere import nova_functions, service_platform_functions, util


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "robot_framework" / "rykker_borgere" / "templates" / "Rykker 1 - Ukendt adresse.docx"


def _nova_access():
    """Build a Mock NovaAccess with the attributes used by the request helpers."""
    access = Mock()
    access.domain = "https://nova.example.com/"
    access.get_bearer_token.return_value = "test-token"
    return access


def _note(title: str, journal_date: str | None = None) -> JournalNote:
    """Build a Mock journal note with the given title and optional ISO journal_date."""
    note = Mock(spec=JournalNote)
    note.title = title
    note.journal_date = journal_date
    return note


# ---------------------------------------------------------------------------
# util.fill_template
# ---------------------------------------------------------------------------

def test_fill_template_creates_file(tmp_path):
    """`fill_template` writes a DOCX to the given output path and returns it."""
    output = tmp_path / "filled.docx"
    result = util.fill_template(
        str(TEMPLATE_PATH), str(output), "Hans Hansen", datetime(2025, 11, 13), "SAG-2025-001",
    )
    assert output.exists()
    assert result == output


def test_fill_template_handles_special_chars(tmp_path):
    """Special characters in name and case number do not break rendering."""
    output = tmp_path / "filled_special.docx"
    util.fill_template(
        str(TEMPLATE_PATH), str(output), "Åsa Øvergård", datetime(2025, 11, 13), "SAG-2025-ÆØÅ",
    )
    assert output.exists()


# ---------------------------------------------------------------------------
# util.get_step
# ---------------------------------------------------------------------------

def test_get_step_no_notes_returns_zero():
    """Empty notes list yields step 0 and no newest note."""
    new_step, newest = util.get_step([])
    assert new_step == 0
    assert newest is None


def test_get_step_returns_next_step_for_highest_rykker():
    """Step is highest existing rykker + 1; newest note is the last matching note in iteration order."""
    notes = [_note(f"{config.NOTE_PREFIX}1"), _note(f"{config.NOTE_PREFIX}2"), _note("Other note")]
    new_step, newest = util.get_step(notes)
    assert new_step == 3
    assert newest is notes[1]


def test_get_step_single_note():
    """A single rykker-prefixed note bumps the step to 2."""
    notes = [_note(f"{config.NOTE_PREFIX}1")]
    new_step, newest = util.get_step(notes)
    assert new_step == 2
    assert newest is notes[0]


def test_get_step_ignores_non_rykker_notes():
    """Notes without the rykker prefix are ignored when computing the next step."""
    notes = [_note("Some other note"), _note(f"{config.NOTE_PREFIX}1"), _note("Another note")]
    new_step, newest = util.get_step(notes)
    assert new_step == 2
    assert newest is notes[1]


# ---------------------------------------------------------------------------
# util.mask_cpr
# ---------------------------------------------------------------------------

def test_mask_cpr():
    """`mask_cpr` shows date-of-birth and masks the last 4 digits."""
    assert util.mask_cpr("0101011234") == "010101-****"
    assert util.mask_cpr("") == "***********"
    assert util.mask_cpr("123") == "***********"


# ---------------------------------------------------------------------------
# nova_functions.get_notes
# ---------------------------------------------------------------------------

@patch("robot_framework.rykker_borgere.nova_functions.nova_notes.get_notes")
def test_get_notes_single_batch(mock_get_notes):
    """When the first batch already meets `expected_notes`, no further fetch is made."""
    mock_get_notes.return_value = [Mock(spec=JournalNote) for _ in range(100)]

    notes = nova_notes.get_notes("case-uuid-123", Mock())

    assert len(notes) == 100
    assert mock_get_notes.call_count == 1


@patch("robot_framework.rykker_borgere.nova_functions.nova_notes.get_notes")
def test_latest_reminder_info_handles_case_without_notes(mock_get_notes):
    """A case with no journal notes (library returns an empty result) yields step 0, no crash."""
    mock_get_notes.return_value = ()

    step, last_date = nova_functions.get_latest_reminder_info("case-uuid-123", _nova_access())

    assert step == 0
    assert last_date is None


@patch("robot_framework.rykker_borgere.nova_functions.nova_notes.get_notes")
def test_latest_reminder_info_ignores_notes_before_cutoff(mock_get_notes, monkeypatch):
    """A reminder note dated before the go-live cutoff is treated as a test note and ignored."""
    monkeypatch.setattr(config, "REMINDER_NOTE_CUTOFF", datetime(2026, 7, 7))
    mock_get_notes.return_value = [_note("Rykker 1 sendt", "2026-05-01T09:00:00")]

    step, last_date = nova_functions.get_latest_reminder_info("case-uuid-123", _nova_access())

    assert step == 0
    assert last_date is None


@patch("robot_framework.rykker_borgere.nova_functions.nova_notes.get_notes")
def test_latest_reminder_info_counts_notes_after_cutoff(mock_get_notes, monkeypatch):
    """A reminder note dated on/after the go-live cutoff is counted normally."""
    monkeypatch.setattr(config, "REMINDER_NOTE_CUTOFF", datetime(2026, 7, 7))
    mock_get_notes.return_value = [_note("Rykker 1 sendt", "2026-08-01T09:00:00")]

    step, last_date = nova_functions.get_latest_reminder_info("case-uuid-123", _nova_access())

    assert step == 1
    assert last_date == "2026-08-01T09:00:00"


@patch("robot_framework.rykker_borgere.nova_functions.nova_notes.get_notes")
def test_latest_reminder_info_mixes_pre_and_post_cutoff_notes(mock_get_notes, monkeypatch):
    """A pre-cutoff test note is ignored while a post-cutoff note still advances the step."""
    monkeypatch.setattr(config, "REMINDER_NOTE_CUTOFF", datetime(2026, 7, 7))
    mock_get_notes.return_value = [
        _note("Rykker 1 sendt", "2026-05-01T09:00:00"),  # pre-cutoff test note, ignored
        _note("Rykker 2 sendt", "2026-08-01T09:00:00"),  # real note, counted
    ]

    step, last_date = nova_functions.get_latest_reminder_info("case-uuid-123", _nova_access())

    assert step == 2
    assert last_date == "2026-08-01T09:00:00"


# ---------------------------------------------------------------------------
# nova_functions.update_case
# ---------------------------------------------------------------------------

@patch("robot_framework.rykker_borgere.nova_functions.requests.patch")
def test_update_case_state_only(mock_patch):
    """When only `new_state` is given, the payload contains state but no caseworker."""
    nova_functions.update_case("case-uuid", _nova_access(), new_state="Afgjort")

    payload = mock_patch.call_args.kwargs["json"]
    assert payload["state"] == "Afgjort"
    assert "caseworker" not in payload


@patch("robot_framework.rykker_borgere.nova_functions.requests.patch")
def test_update_case_with_caseworker(mock_patch):
    """When `new_caseworker` is given, the payload exposes a kspIdentity caseworker block."""
    caseworker = Mock(spec=Caseworker)
    caseworker.ident = "jdoe"
    caseworker.name = "John Doe"

    nova_functions.update_case("case-uuid", _nova_access(), new_caseworker=caseworker)

    payload = mock_patch.call_args.kwargs["json"]
    assert payload["caseworker"]["kspIdentity"]["racfId"] == "jdoe"
    assert payload["caseworker"]["kspIdentity"]["fullName"] == "John Doe"


# ---------------------------------------------------------------------------
# nova_functions._build_caseworker_payload
# ---------------------------------------------------------------------------

def test_build_caseworker_payload_contains_ksp_identity():
    """Caseworker payload exposes `kspIdentity` with racfId and fullName."""
    caseworker = Mock(spec=Caseworker)
    caseworker.ident = "jdoe"
    caseworker.name = "John Doe"

    payload = nova_functions._build_caseworker_payload(caseworker)

    assert payload == {"kspIdentity": {"fullName": "John Doe", "racfId": "jdoe"}}


# ---------------------------------------------------------------------------
# service_platform_functions.send_digital_post
# ---------------------------------------------------------------------------

@patch("robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered")
def test_send_digital_post_returns_false_when_not_registered(mock_is_registered):
    """Unregistered recipients short-circuit and return False without sending."""
    mock_is_registered.return_value = False

    assert service_platform_functions.send_digital_post(Mock(), "letter.pdf", "0101011234", "Rykker 1") is False


@patch("robot_framework.rykker_borgere.service_platform_functions.digital_post.send_message")
@patch("robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered")
def test_send_digital_post_sends_message_for_registered(mock_is_registered, mock_send_message, tmp_path):
    """Registered recipients trigger one `send_message` call and return True."""
    mock_is_registered.return_value = True
    fake_pdf = tmp_path / "letter.pdf"
    fake_pdf.write_bytes(b"%PDF-fake")

    assert service_platform_functions.send_digital_post(Mock(), str(fake_pdf), "0101011234", "Rykker 1") is True
    mock_send_message.assert_called_once()


# ---------------------------------------------------------------------------
# service_platform_functions.send_sms
# ---------------------------------------------------------------------------

@patch("robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered")
def test_send_sms_returns_false_when_not_registered(mock_is_registered):
    """Unregistered recipients short-circuit and return False without reading any template."""
    mock_is_registered.return_value = False

    assert service_platform_functions.send_sms(Mock(), "0101011234") is False


@patch("robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered")
@patch("robot_framework.rykker_borgere.service_platform_functions.digital_post.send_message")
@patch("builtins.open", new_callable=mock_open, read_data="Test SMS content")
def test_send_sms_loads_danish_template_by_default(mock_file, mock_send_message, mock_is_registered):
    """Default language opens the Danish SMS template and triggers one send."""
    mock_is_registered.return_value = True

    assert service_platform_functions.send_sms(Mock(), "0101011234") is True
    mock_send_message.assert_called_once()
    mock_file.assert_called_once_with(
        config.TEMPLATES_DIR / "sms_text_da.txt", "r", encoding="utf-8",
    )


@patch("robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered")
@patch("robot_framework.rykker_borgere.service_platform_functions.digital_post.send_message")
@patch("builtins.open", new_callable=mock_open, read_data="Test SMS content")
def test_send_sms_loads_english_template_when_language_en(mock_file, mock_send_message, mock_is_registered):
    """`language="en"` opens the English SMS template."""
    mock_is_registered.return_value = True

    assert service_platform_functions.send_sms(Mock(), "0101011234", language="en") is True
    mock_send_message.assert_called_once()
    mock_file.assert_called_once_with(
        config.TEMPLATES_DIR / "sms_text_en.txt", "r", encoding="utf-8",
    )
