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

    def send_reminder(self, case: dict, cpr: str, first_name: str, step: int, *,
                      nemsms_registered: bool = False) -> None:
        """Send reminder letter and add Nova note in production.

        The letter is always uploaded to Nova so the caseworker has access to it,
        regardless of whether digital post delivery succeeds. If the citizen is not
        registered for digital post, the journal note is titled "Ikke sendt: Rykker X
        sendt" and the step counter still advances (so the robot does not retry the
        same reminder every Monday indefinitely).
        """
        if self._nova is None or self._kombit is None:
            raise RuntimeError("RealActionsSink requires NovaAccess and KombitAccess to send reminders")

        case_uuid = case["common"]["uuid"]
        case_number = case["caseAttributes"]["userFriendlyCaseNumber"]
        template_to_use = str(config.TEMPLATES_DIR / f"Rykker {step} - Ukendt adresse.docx")
        letter_name = f"{first_name}, din adresse er ukendt"
        deadline_date = datetime.now() + timedelta(days=config.LETTER_DEADLINE_DAYS)
        config.TMP_DIR.mkdir(exist_ok=True)
        letter_path = util.fill_template(template_to_use, str(config.TMP_DIR / letter_name), first_name, deadline_date, case_number)
        pdf_path = util.convert_docx_to_pdf(letter_path, str(config.TMP_DIR))

        delivered = service_platform_functions.send_digital_post(self._kombit, str(pdf_path), cpr)

        nova_functions.upload_document(
            nova_access=self._nova,
            document_path=str(pdf_path),
            document_title=letter_name,
            case_id=case_uuid,
        )
        nova_functions.add_reminder_note(case_uuid, step, self._nova, sent=delivered)

        if delivered and nemsms_registered:
            for lang in ("da", "en"):
                try:
                    service_platform_functions.send_sms(self._kombit, cpr, lang)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    # Letter is already delivered — SMS is a bonus. Log and continue.
                    if self._orc is not None:
                        self._orc.log_error(
                            f"NemSMS-notifikation om Rykker {step} for sag {case_number} fejlede ({lang}): {str(e)}"
                        )
            nova_functions.add_sms_note(
                case_uuid=case_uuid,
                nova_access=self._nova,
                reason=f"Notifikation om at Rykker {step} er leveret via digital post",
            )


class DryRunSink:  # pylint: disable=too-many-instance-attributes
    """Records actions that would be performed in a dry run."""

    is_dry_run: bool = True

    def __init__(self, mock_state: dict | None = None, verbose: bool = False):
        self.sms_actions = []
        self.reminder_actions = []
        self.queue_updates = []
        self.verbose = verbose
        mock_state = mock_state or {}
        self.mock_queue_state = mock_state.get("queue", {})
        self.mock_nova_reminders = mock_state.get("nova_reminders", {})
        # Lets tests exercise the "not registered for digital post" branch without
        # hitting the Service Platform. Defaults to True when a CPR is not specified,
        # which preserves the existing test behavior.
        self.mock_digital_post_registered = mock_state.get("digital_post_registered", {})
        # Assigned by process() before print_report is called. Holds a BackofficeAlerts.
        self.backoffice_alerts = None

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

        Simulates the delivery outcome via `mock_digital_post_registered[cpr]`
        (defaults to True). When True, one NemSMS action per language is also
        recorded if `nemsms_registered`. When False, no NemSMS is recorded — the
        letter could not be delivered.
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
        no_case = self.backoffice_alerts.no_case if self.backoffice_alerts else []
        high_step = self.backoffice_alerts.high_step if self.backoffice_alerts else []
        backoffice_total = len(no_case) + len(high_step)
        orchestrator_connection.log_info(
            f"\n📧 Backoffice-mail ville blive sendt: {'JA' if backoffice_total else 'NEJ'} "
            f"(ingen sag: {len(no_case)}, høj step: {len(high_step)})"
        )
        for entry in no_case:
            orchestrator_connection.log_info(f"  - INGEN SAG: {entry['fornavn']} (CPR: {entry['cpr']})")
        for entry in high_step:
            orchestrator_connection.log_info(
                f"  - HØJ STEP: Sag {entry['case_number']} | {entry['fornavn']} "
                f"(CPR: {entry['cpr']}) | step {entry['step']}"
            )
        orchestrator_connection.log_info("\n" + "=" * 80)
        orchestrator_connection.log_info("OPSUMMERING")
        orchestrator_connection.log_info("=" * 80)
        orchestrator_connection.log_info(f"Ville have sendt {len(self.sms_actions)} SMS")
        orchestrator_connection.log_info(f"Ville have sendt {len(self.reminder_actions)} rykkere")
        orchestrator_connection.log_info(f"Ville have opdateret {len(self.queue_updates)} queue elementer")
        orchestrator_connection.log_info(f"Ville have inkluderet {backoffice_total} borgere i backoffice-mail")
        orchestrator_connection.log_info("=" * 80)
