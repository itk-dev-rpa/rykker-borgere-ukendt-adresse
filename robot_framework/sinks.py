"""Action sinks for the robot processing flow.

This module defines concrete sink implementations used to either record actions
(dry-run) or perform real side-effects (production).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess

from robot_framework.rykker_borgere import nova_functions, service_platform_functions, util
from robot_framework import config


class RealActionsSink:
    """Production sink that performs real side-effects.

    Methods mirror the ActionSink contract used in `process`.
    """

    # Marker so generic code can detect this is NOT a dry-run sink
    is_dry_run: bool = False

    def __init__(self, *, orchestrator: OrchestratorConnection | None = None,
                 nova_access: NovaAccess | None = None,
                 kombit_access: KombitAccess | None = None) -> None:
        """Initialize sink with optional service connections."""
        self._orc = orchestrator
        self._nova = nova_access
        self._kombit = kombit_access
        # Initialize current case context holder
        self._case: dict | None = None

    # Lifecycle hooks (optional)
    def begin_batch(self, *, _correlation_id: str | None = None, _metadata: dict[str, Any] | None = None) -> None:
        """Optional lifecycle hook at the beginning of a batch (no-op in prod)."""
        return None

    def end_batch(self) -> None:
        """Optional lifecycle hook at the end of a batch (no-op in prod)."""
        return None

    def print_report(self, _orchestrator_connection: OrchestratorConnection) -> None:
        """No report in production mode."""
        return None

    # Domain actions
    def establish_baseline(self, *, case_uuid: str, step: int = 0) -> None:
        """Create a Nova reminder baseline (Rykker 0) in production."""
        if self._nova is None:
            raise RuntimeError("RealActionsSink requires NovaAccess for baseline establishment")
        nova_functions.add_reminder_note(case_uuid, step, self._nova)

    def log_sms(self, cpr: str, _first_name: str, language: str, reason: str = "") -> None:
        """Send an SMS via Serviceplatformen and optionally add a Nova note."""
        if self._kombit is None:
            raise RuntimeError("RealActionsSink requires KombitAccess to send SMS")
        service_platform_functions.send_sms(self._kombit, cpr, language)
        # Also add a Nova note documenting SMS
        if self._nova is not None:
            nova_functions.add_sms_note(
                case_uuid=self._current_case_uuid_or_raise(),
                nova_access=self._nova,
                reason=reason,
            )

    def log_queue_update(self, encrypted_ref: str, digital_post: bool, nemsms: bool, case_uuid: str) -> None:
        """Persist the citizen comms status in the orchestrator queue."""
        if self._orc is None:
            raise RuntimeError("RealActionsSink requires OrchestratorConnection for queue updates")
        util.update_queue_element(self._orc, config.QUEUE_NAME, encrypted_ref, digital_post, nemsms, case_uuid)

    def log_nova_note(self, case_uuid: str, note_type: str, details: str) -> None:
        """Add a generic text note to the Nova case (if Nova access is available)."""
        if self._nova is None:
            # If no Nova access is available we silently ignore (or raise, depending on policy)
            return
        # Map common note types used by the robot.
        title = note_type
        text = details
        nova_functions.nova_notes.add_text_note(case_uuid, title, text, nova_functions.config.CASEWORKER, approved=False, nova_access=self._nova)

    def log_reminder(self, cpr: str, first_name: str, case_number: str, step: int) -> None:
        """Send reminder letter and add Nova note in production.

        This mirrors the logic in `handle_case` for document creation and delivery.
        The sink assumes that deadline/baseline etc. are computed by the caller.
        """
        if self._nova is None or self._kombit is None:
            raise RuntimeError("RealActionsSink requires NovaAccess and KombitAccess to send reminders")

        case = self._current_case_or_raise()
        case_uuid = case["common"]["uuid"]
        # Build assets
        template_to_use = f"rykker_borgere/templates/Rykker {step} - Ukendt adresse.docx"
        letter_name = f"Rykker {step} - Adresse.docx"
        deadline_date = datetime.now() + timedelta(days=30)
        letter_path = util.fill_template(template_to_use, f"tmp/{letter_name}", first_name, deadline_date, case_number)
        pdf_path = util.convert_docx_to_pdf(letter_path, "tmp/")
        # Upload and send
        nova_functions.upload_document(self._nova, str(pdf_path), letter_name, case_uuid)
        service_platform_functions.send_digital_post(self._kombit, str(pdf_path), cpr)
        nova_functions.add_reminder_note(case_uuid, step, self._nova)

    # Context helpers (set by process before calling actions)
    def set_current_case_context(self, case: dict) -> None:
        """Provide the current Nova case context for subsequent operations."""
        self._case = case

    def _current_case_or_raise(self) -> dict:
        """Return the current case context or raise if it has not been set."""
        if self._case is None:
            raise RuntimeError("RealActionsSink: current case context not set")
        return self._case

    def _current_case_uuid_or_raise(self) -> str:
        """Return the UUID of the current case context."""
        return self._current_case_or_raise()["common"]["uuid"]


class DryRunSink:
    """Tracks actions that would be performed in a dry run.

    Acts as an ActionSink for process functions. Also carries optional
    mock state overlays used solely in dry-run to simulate previous system state.
    """

    # Marker used by the process flow to decide whether to perform side-effects
    is_dry_run: bool = True

    def __init__(self, mock_state: dict | None = None):
        self.sms_actions = []
        self.reminder_actions = []
        self.queue_updates = []
        self.nova_notes = []
        self._batch_meta = {}
        # Optional simulated state overlays (used only in dry-run)
        mock_state = mock_state or {}
        self.mock_queue_state = mock_state.get("queue", {})
        self.mock_nova_reminders = mock_state.get("nova_reminders", {})

    def log_sms(self, cpr: str, first_name: str, language: str, reason: str = ""):
        """Log an SMS that would be sent."""
        self.sms_actions.append({
            "cpr": cpr,
            "first_name": first_name,
            "language": language,
            "reason": reason
        })

    def log_reminder(self, cpr: str, first_name: str, case_number: str, step: int):
        """Log a reminder that would be sent."""
        self.reminder_actions.append({
            "cpr": cpr,
            "first_name": first_name,
            "case_number": case_number,
            "step": step
        })

    def log_queue_update(self, encrypted_ref: str, digital_post: bool, nemsms: bool, case_uuid: str):
        """Log a queue update that would be performed."""
        self.queue_updates.append({
            "encrypted_ref": encrypted_ref,
            "digital_post": digital_post,
            "nemsms": nemsms,
            "case_uuid": case_uuid
        })

    def log_nova_note(self, case_uuid: str, note_type: str, details: str):
        """Log a Nova note that would be added."""
        self.nova_notes.append({
            "case_uuid": case_uuid,
            "note_type": note_type,
            "details": details
        })

    def establish_baseline(self, *, case_uuid: str, step: int = 0):
        """Record that we would establish a baseline (Rykker 0) now."""
        self.log_nova_note(case_uuid, "Rykker note", f"Rykker {step} (baseline)")

    def begin_batch(self, *, correlation_id: str | None = None, metadata: dict | None = None):
        """Optional hook to mark the beginning of a run/batch (no-op)."""
        self._batch_meta = {"correlation_id": correlation_id, "metadata": metadata or {}}

    def end_batch(self):
        """Optional hook to mark the end of a run/batch (no-op)."""
        # no persisted state to finalize
        return None

    def print_report(self, orchestrator_connection: OrchestratorConnection):
        """Print a detailed dry-run report."""
        orchestrator_connection.log_info("=" * 80)
        orchestrator_connection.log_info("DRY-RUN RAPPORT")
        orchestrator_connection.log_info("=" * 80)

        # SMS Report
        orchestrator_connection.log_info(f"\n📱 SMS der ville blive sendt: {len(self.sms_actions)}")
        if self.sms_actions:
            for action in self.sms_actions:
                masked_cpr = f"{action['cpr'][:6]}****"
                reason_text = f" ({action['reason']})" if action['reason'] else ""
                orchestrator_connection.log_info(
                    f"  - {action['first_name']} (CPR: {masked_cpr}) - Sprog: {action['language']}{reason_text}"
                )

        # Reminder Report
        orchestrator_connection.log_info(f"\n📨 Rykkere der ville blive sendt: {len(self.reminder_actions)}")
        if self.reminder_actions:
            for action in self.reminder_actions:
                masked_cpr = f"{action['cpr'][:6]}****"
                orchestrator_connection.log_info(
                    f"  - Sag {action['case_number']}: {action['first_name']} (CPR: {masked_cpr}) - Rykker {action['step']}"
                )

        # Queue Updates
        orchestrator_connection.log_info(f"\n🔄 Queue opdateringer der ville blive udført: {len(self.queue_updates)}")
        if self.queue_updates:
            for upd in self.queue_updates:
                orchestrator_connection.log_info(
                    f"  - Ref: {upd['encrypted_ref']} | digital_post={upd['digital_post']} | nemsms={upd['nemsms']} | case_uuid={upd['case_uuid']}"
                )

        # Nova Notes
        orchestrator_connection.log_info(f"\n📝 Nova notater der ville blive tilføjet: {len(self.nova_notes)}")
        if self.nova_notes:
            for note in self.nova_notes:
                orchestrator_connection.log_info(
                    f"  - {note['note_type']} (case {note['case_uuid']}): {note['details']}"
                )

        orchestrator_connection.log_info("\n" + "=" * 80)
        orchestrator_connection.log_info("OPSUMMERING")
        orchestrator_connection.log_info("=" * 80)
        orchestrator_connection.log_info(f"Ville have sendt {len(self.sms_actions)} SMS")
        orchestrator_connection.log_info(f"Ville have sendt {len(self.reminder_actions)} rykkere")
        orchestrator_connection.log_info(f"Ville have opdateret {len(self.queue_updates)} queue elementer")
        orchestrator_connection.log_info(f"Ville have tilføjet {len(self.nova_notes)} Nova notater")
        orchestrator_connection.log_info("=" * 80)
