"""Helper module for dry-run functionality."""
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection


class DryRunTracker:
    """Tracks actions that would be performed in a dry run."""

    def __init__(self, mock_state: dict | None = None):
        self.sms_actions = []
        self.reminder_actions = []
        self.queue_updates = []
        self.nova_notes = []
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
