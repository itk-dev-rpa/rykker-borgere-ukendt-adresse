"""Action sinks for the robot processing flow.

This module defines concrete sink implementations used to either record actions
(dry-run) or perform real side-effects (production).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from python_serviceplatformen.authentication import KombitAccess
from itk_dev_shared_components.kmd_nova.authentication import NovaAccess

from robot_framework.rykker_borgere import nova_functions, service_platform_functions, util
from robot_framework import config


class RealActionsSink:
    """Production sink that performs real side-effects."""

    is_dry_run: bool = False
    verbose: bool = False

    def __init__(self, *, orchestrator: OrchestratorConnection | None = None,
                 nova_access: NovaAccess | None = None,
                 kombit_access: KombitAccess | None = None) -> None:
        self._orc = orchestrator
        self._nova = nova_access
        self._kombit = kombit_access

    def establish_baseline(self, *, case_uuid: str, step: int = 0) -> None:
        """Create a Nova reminder baseline (Rykker 0) in production."""
        if self._nova is None:
            raise RuntimeError("RealActionsSink requires NovaAccess for baseline establishment")
        nova_functions.add_reminder_note(case_uuid, step, self._nova)

    def send_sms(self, case: dict, cpr: str, _first_name: str, *, language: str, reason: str = "") -> None:
        """Send an SMS via Serviceplatformen and add a Nova note documenting it."""
        if self._kombit is None:
            raise RuntimeError("RealActionsSink requires KombitAccess to send SMS")
        service_platform_functions.send_sms(self._kombit, cpr, language)
        if self._nova is not None:
            nova_functions.add_sms_note(
                case_uuid=case["common"]["uuid"],
                nova_access=self._nova,
                reason=reason,
            )

    def update_queue(self, encrypted_ref: str, digital_post: bool, nemsms: bool, case_uuid: str) -> None:
        """Persist the citizen comms status in the orchestrator queue."""
        if self._orc is None:
            raise RuntimeError("RealActionsSink requires OrchestratorConnection for queue updates")
        util.update_queue_element(self._orc, config.QUEUE_NAME, encrypted_ref, digital_post, nemsms, case_uuid)

    def add_nova_note(self, case_uuid: str, note_type: str, details: str) -> None:
        """Add a generic text note to the Nova case (if Nova access is available)."""
        if self._nova is None:
            return
        nova_functions.nova_notes.add_text_note(
            case_uuid, note_type, details, nova_functions.config.CASEWORKER,
            approved=False, nova_access=self._nova,
        )

    def send_reminder(self, case: dict, cpr: str, first_name: str, step: int, *,
                      nemsms_registered: bool = False) -> None:
        """Send reminder letter and add Nova note in production.

        Brevet uploades altid til Nova så sagsbehandler har det tilgængeligt — uanset om
        digital post-leveringen lykkes. Hvis borgeren ikke er tilmeldt digital post,
        markeres journalnotatet "Ikke sendt: Rykker X sendt" og step-tælleren rykker
        alligevel frem (så robotten ikke prøver samme rykker hver mandag).
        """
        if self._nova is None or self._kombit is None:
            raise RuntimeError("RealActionsSink requires NovaAccess and KombitAccess to send reminders")

        case_uuid = case["common"]["uuid"]
        case_number = case["caseAttributes"]["userFriendlyCaseNumber"]
        template_to_use = f"rykker_borgere/templates/Rykker {step} - Ukendt adresse.docx"
        letter_name = f"{first_name}, din adresse er ukendt.docx"
        deadline_date = datetime.now() + timedelta(days=config.LETTER_DEADLINE_DAYS)
        letter_path = util.fill_template(template_to_use, f"tmp/{letter_name}", first_name, deadline_date, case_number)
        pdf_path = util.convert_docx_to_pdf(letter_path, "tmp/")
        nova_functions.upload_document(self._nova, str(pdf_path), letter_name, case_uuid)

        delivered = service_platform_functions.send_digital_post(self._kombit, str(pdf_path), cpr)
        nova_functions.add_reminder_note(case_uuid, step, self._nova, sent=delivered)

        if delivered and nemsms_registered:
            for lang in ("da", "en"):
                try:
                    service_platform_functions.send_sms(self._kombit, cpr, lang)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    # Brevet er leveret — SMS er bonus. Log og fortsæt.
                    if self._orc is not None:
                        self._orc.log_error(
                            f"NemSMS-notifikation om Rykker {step} for sag {case_number} fejlede ({lang}): {str(e)}"
                        )
            nova_functions.add_sms_note(
                case_uuid=case_uuid,
                nova_access=self._nova,
                reason=f"Notifikation om at Rykker {step} er leveret via digital post",
            )


class DryRunSink:
    """Records actions that would be performed in a dry run."""

    is_dry_run: bool = True

    def __init__(self, mock_state: dict | None = None, verbose: bool = False):
        self.sms_actions = []
        self.reminder_actions = []
        self.queue_updates = []
        self.nova_notes = []
        self.verbose = verbose
        mock_state = mock_state or {}
        self.mock_queue_state = mock_state.get("queue", {})
        self.mock_nova_reminders = mock_state.get("nova_reminders", {})
        # Tillader test af "ikke tilmeldt digital post"-grenen uden faktisk Serviceplatformen-kald.
        # Default True hvis ikke specificeret per CPR — bevarer eksisterende test-adfærd.
        self.mock_digital_post_registered = mock_state.get("digital_post_registered", {})

    def _say(self, msg: str) -> None:
        if self.verbose:
            print(f"  → {msg}", flush=True)

    def send_sms(self, case: dict, cpr: str, first_name: str, *, language: str, reason: str = ""):
        """Record an SMS that would be sent."""
        case_number = case["caseAttributes"]["userFriendlyCaseNumber"]
        self.sms_actions.append({
            "cpr": cpr,
            "first_name": first_name,
            "language": language,
            "reason": reason,
        })
        self._say(f"[sag {case_number}] SMS ({language}) → {first_name} ({util.mask_cpr(cpr)}) — {reason}")

    def send_reminder(self, case: dict, cpr: str, first_name: str, step: int, *,
                      nemsms_registered: bool = False):
        """Record a reminder that would be sent.

        Simulerer leveringsudfaldet via `mock_digital_post_registered[cpr]` (default True).
        Hvis True: et NemSMS-action per sprog registreres oveni hvis nemsms_registered.
        Hvis False: ingen NemSMS (brevet kunne ikke leveres).
        """
        case_number = case["caseAttributes"]["userFriendlyCaseNumber"]
        delivered = self.mock_digital_post_registered.get(cpr, True)
        self.reminder_actions.append({
            "cpr": cpr,
            "first_name": first_name,
            "case_number": case_number,
            "step": step,
            "delivered": delivered,
        })
        status = "Rykker" if delivered else "Ikke sendt: Rykker"
        self._say(f"[sag {case_number}] {status} {step} → {first_name} ({util.mask_cpr(cpr)})")

        if delivered and nemsms_registered:
            for lang in ("da", "en"):
                self.sms_actions.append({
                    "cpr": cpr,
                    "first_name": first_name,
                    "language": lang,
                    "reason": f"Notifikation om at Rykker {step} er leveret via digital post",
                })
            self._say(f"  ↳ NemSMS-notifikation om brev (da+en) → {first_name}")

    def update_queue(self, encrypted_ref: str, digital_post: bool, nemsms: bool, case_uuid: str):
        """Record a queue update that would be performed."""
        self.queue_updates.append({
            "encrypted_ref": encrypted_ref,
            "digital_post": digital_post,
            "nemsms": nemsms,
            "case_uuid": case_uuid,
        })
        self._say(f"Queue: digital_post={digital_post}, nemsms={nemsms}")

    def add_nova_note(self, case_uuid: str, note_type: str, details: str):
        """Record a Nova note that would be added."""
        self.nova_notes.append({
            "case_uuid": case_uuid,
            "note_type": note_type,
            "details": details,
        })

    def establish_baseline(self, *, case_uuid: str, step: int = 0):
        """Record that we would establish a baseline (Rykker 0) now."""
        self.add_nova_note(case_uuid, "Rykker note", f"Rykker {step} (baseline)")
        self._say(f"Baseline: Rykker {step}")

    def print_report(self, orchestrator_connection: OrchestratorConnection):
        """Print a detailed dry-run report."""
        orchestrator_connection.log_info("=" * 80)
        orchestrator_connection.log_info("DRY-RUN RAPPORT")
        orchestrator_connection.log_info("=" * 80)

        orchestrator_connection.log_info(f"\n📱 SMS der ville blive sendt: {len(self.sms_actions)}")
        for action in self.sms_actions:
            masked_cpr = util.mask_cpr(action['cpr'])
            reason_text = f" ({action['reason']})" if action['reason'] else ""
            orchestrator_connection.log_info(
                f"  - {action['first_name']} (CPR: {masked_cpr}) - Sprog: {action['language']}{reason_text}"
            )

        orchestrator_connection.log_info(f"\n📨 Rykkere der ville blive sendt: {len(self.reminder_actions)}")
        for action in self.reminder_actions:
            masked_cpr = util.mask_cpr(action['cpr'])
            label = "Rykker" if action.get('delivered', True) else "Ikke sendt: Rykker"
            orchestrator_connection.log_info(
                f"  - Sag {action['case_number']}: {action['first_name']} (CPR: {masked_cpr}) - {label} {action['step']}"
            )

        orchestrator_connection.log_info(f"\n🔄 Queue opdateringer der ville blive udført: {len(self.queue_updates)}")
        for upd in self.queue_updates:
            orchestrator_connection.log_info(
                f"  - Ref: {upd['encrypted_ref']} | digital_post={upd['digital_post']} | nemsms={upd['nemsms']} | case_uuid={upd['case_uuid']}"
            )

        orchestrator_connection.log_info(f"\n📝 Nova notater der ville blive tilføjet: {len(self.nova_notes)}")
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
