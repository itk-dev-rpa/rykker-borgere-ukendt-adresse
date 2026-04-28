"""Comprehensive tests for rykker_borgere functions."""
# pylint: disable=broad-exception-caught,protected-access

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

from itk_dev_shared_components.kmd_nova.nova_objects import JournalNote, Caseworker

from robot_framework.rykker_borgere import nova_functions, util, service_platform_functions
from robot_framework import config


# ============================================================================
# UTIL TESTS
# ============================================================================

class TestFillTemplate:
    """Tests for util.fill_template function."""

    def test_fill_template_creates_file(self):
        """Test that fill_template creates output file."""
        print("\n--- Testing fill_template ---")
        # Brug rykker_borgere/templates mappen
        template_path = Path(__file__).parent / "rykker_borgere" / "templates" / "Rykker 1 - Ukendt adresse.docx"
        output_path = Path(__file__).parent / "rykker_borgere" / "test_output_fill.docx"

        try:
            util.fill_template(
                str(template_path),
                str(output_path),
                "Hans Hansen",
                datetime(2025, 11, 13),
                "SAG-2025-001"
            )

            assert output_path.exists(), "Output file was not created"
            print(f"✅ Template filled successfully: {output_path}")
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
        finally:
            # Cleanup
            if output_path.exists():
                output_path.unlink()

    def test_fill_template_with_special_chars(self):
        """Test fill_template with special characters in name."""
        print("\n--- Testing fill_template with special chars ---")
        template_path = Path(__file__).parent / "rykker_borgere" / "templates" / "Rykker 1 - Ukendt adresse.docx"
        output_path = Path(__file__).parent / "rykker_borgere" / "test_output_special.docx"

        try:
            util.fill_template(
                str(template_path),
                str(output_path),
                "Åsa Øvergård",
                datetime(2025, 11, 13),
                "SAG-2025-ÆØÅ"
            )

            assert output_path.exists()
            print("✅ Template with special chars filled successfully")
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
        finally:
            # Cleanup
            if output_path.exists():
                output_path.unlink()


class TestGetStep:
    """Tests for util.get_step function."""

    def test_get_step_no_notes(self):
        """Test get_step with empty notes list."""
        print("\n--- Testing get_step with no notes ---")

        new_step, newest_note = util.get_step([])

        assert new_step == 0, "Should return 0 when no notes exist"
        assert newest_note is None, "Should return None as newest note"
        print("✅ get_step returns (0, None) for empty list")
        return True

    def test_get_step_with_rykker_notes(self):
        """Test get_step with RPA Rykker notes."""
        print("\n--- Testing get_step with rykker notes ---")

        # Brug den rigtige NOTE_PREFIX værdi
        note1 = Mock(spec=JournalNote)
        note1.title = f"{config.NOTE_PREFIX}1"

        note2 = Mock(spec=JournalNote)
        note2.title = f"{config.NOTE_PREFIX}2"

        note3 = Mock(spec=JournalNote)
        note3.title = "Other note"

        notes = [note1, note2, note3]

        try:
            new_step, newest_note = util.get_step(notes)

            assert new_step == 3, f"Should return next step (3), got {new_step}"
            assert newest_note == note2, "Should return the newest rykker note"
            print("✅ get_step correctly identifies step 3 and newest note")
            return True
        except ValueError as e:
            print(f"❌ ValueError (NOTE_PREFIX format issue): {e}")
            print(f"   NOTE_PREFIX value: '{config.NOTE_PREFIX}'")
            return False

    def test_get_step_single_note(self):
        """Test get_step with single RPA Rykker note."""
        print("\n--- Testing get_step with single note ---")

        note = Mock(spec=JournalNote)
        note.title = f"{config.NOTE_PREFIX}1"

        try:
            new_step, newest_note = util.get_step([note])

            assert new_step == 2, "Should return step 2 (next after 1)"
            assert newest_note == note
            print("✅ get_step correctly returns step 2 for single note")
            return True
        except ValueError as e:
            print(f"❌ ValueError: {e}")
            return False

    def test_get_step_mixed_notes(self):
        """Test get_step ignores non-rykker notes."""
        print("\n--- Testing get_step with mixed notes ---")

        note1 = Mock(spec=JournalNote)
        note1.title = "Some other note"

        note2 = Mock(spec=JournalNote)
        note2.title = f"{config.NOTE_PREFIX}1"

        note3 = Mock(spec=JournalNote)
        note3.title = "Another note"

        notes = [note1, note2, note3]

        try:
            new_step, newest_note = util.get_step(notes)

            assert new_step == 2, "Should only count rykker notes"
            assert newest_note == note2
            print("✅ get_step correctly filters non-rykker notes")
            return True
        except ValueError as e:
            print(f"❌ ValueError: {e}")
            return False


# ============================================================================
# NOVA_FUNCTIONS TESTS
# ============================================================================

class TestNovaFunctions:
    """Tests for nova_functions."""

    @patch('robot_framework.rykker_borgere.nova_functions.requests.put')
    def test_get_cases_single_batch(self, mock_put):
        """Test get_cases with single batch (no pagination)."""
        print("\n--- Testing get_cases single batch ---")

        mock_response = Mock()
        mock_response.json.return_value = {
            "pagingInformation": {"hasMoreRows": False},
            "cases": [
                {"caseId": "case1", "caseAttributes": {"title": "Kat A"}},
                {"caseId": "case2", "caseAttributes": {"title": "Kat A"}},
            ]
        }
        mock_put.return_value = mock_response

        nova_access = Mock()
        nova_access.domain = "https://nova.example.com/"
        nova_access.get_bearer_token.return_value = "test-token"

        cases = nova_functions.get_cases(nova_access)

        assert len(cases) == 2
        assert mock_put.call_count == 1
        print("✅ get_cases returns 2 cases in single batch")
        return True

    @patch('robot_framework.rykker_borgere.nova_functions.requests.put')
    def test_get_cases_multiple_batches(self, mock_put):
        """Test get_cases with pagination."""
        print("\n--- Testing get_cases multiple batches ---")

        # First batch
        first_response = Mock()
        first_response.json.return_value = {
            "pagingInformation": {"hasMoreRows": True},
            "cases": [{"caseId": f"case{i}"} for i in range(500)]
        }

        # Second batch
        second_response = Mock()
        second_response.json.return_value = {
            "pagingInformation": {"hasMoreRows": False},
            "cases": [{"caseId": f"case{i}"} for i in range(500, 750)]
        }

        mock_put.side_effect = [first_response, second_response]

        nova_access = Mock()
        nova_access.domain = "https://nova.example.com/"
        nova_access.get_bearer_token.return_value = "test-token"

        cases = nova_functions.get_cases(nova_access)

        assert len(cases) == 750
        assert mock_put.call_count == 2
        print("✅ get_cases handles pagination correctly (750 cases)")
        return True

    @patch('robot_framework.rykker_borgere.nova_functions.nova_notes.get_notes')
    def test_get_notes_single_batch(self, mock_get_notes):
        """Test get_notes with single batch."""
        print("\n--- Testing get_notes single batch ---")

        mock_notes = [Mock(spec=JournalNote) for _ in range(100)]
        mock_get_notes.side_effect = [mock_notes, []]  # First call returns notes, second returns empty

        nova_access = Mock()

        notes = nova_functions.get_notes(nova_access, "case-uuid-123")

        assert len(notes) == 100
        print("✅ get_notes returns 100 notes from single batch")
        return True

    @patch('robot_framework.rykker_borgere.nova_functions.nova_notes.get_notes')
    def test_get_notes_multiple_batches(self, mock_get_notes):
        """Test get_notes with pagination."""
        print("\n--- Testing get_notes multiple batches ---")

        batch1 = [Mock(spec=JournalNote) for _ in range(500)]
        batch2 = [Mock(spec=JournalNote) for _ in range(300)]
        batch3 = []

        mock_get_notes.side_effect = [batch1, batch2, batch3]

        nova_access = Mock()

        notes = nova_functions.get_notes(nova_access, "case-uuid-123")

        assert len(notes) == 800
        assert mock_get_notes.call_count == 3
        print("✅ get_notes handles pagination (800 notes total)")
        return True

    @patch('robot_framework.rykker_borgere.nova_functions.requests.patch')
    def test_update_case_state_only(self, mock_patch):
        """Test update_case with only state change."""
        print("\n--- Testing update_case with state ---")

        mock_response = Mock()
        mock_patch.return_value = mock_response

        nova_access = Mock()
        nova_access.domain = "https://nova.example.com/"
        nova_access.get_bearer_token.return_value = "test-token"

        nova_functions.update_case(
            "case-uuid-123",
            nova_access,
            new_state="Afgjort"
        )

        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        payload = call_args.kwargs['json']

        assert payload['state'] == "Afgjort"
        assert 'caseworker' not in payload
        print("✅ update_case correctly updates state")
        return True

    @patch('robot_framework.rykker_borgere.nova_functions.requests.patch')
    def test_update_case_with_caseworker(self, mock_patch):
        """Test update_case with caseworker change."""
        print("\n--- Testing update_case with caseworker ---")

        mock_response = Mock()
        mock_patch.return_value = mock_response

        nova_access = Mock()
        nova_access.domain = "https://nova.example.com/"
        nova_access.get_bearer_token.return_value = "test-token"

        caseworker = Mock(spec=Caseworker)
        caseworker.type = 'user'
        caseworker.ident = 'jdoe'
        caseworker.name = 'John Doe'

        nova_functions.update_case(
            "case-uuid-123",
            nova_access,
            new_caseworker=caseworker
        )

        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        payload = call_args.kwargs['json']

        assert 'caseworker' in payload
        assert payload['caseworker']['kspIdentity']['racfId'] == 'jdoe'
        print("✅ update_case correctly updates caseworker")
        return True

    def test_build_caseworker_payload_user(self):
        """Test _build_caseworker_payload for user type."""
        print("\n--- Testing _build_caseworker_payload user ---")

        caseworker = Mock(spec=Caseworker)
        caseworker.type = 'user'
        caseworker.ident = 'jdoe'
        caseworker.name = 'John Doe'

        payload = nova_functions._build_caseworker_payload(caseworker)

        assert payload['kspIdentity']['racfId'] == 'jdoe'
        assert payload['kspIdentity']['fullName'] == 'John Doe'
        print("✅ _build_caseworker_payload correctly builds user payload")
        return True

    def test_build_caseworker_payload_group(self):
        """Test _build_caseworker_payload for group type."""
        print("\n--- Testing _build_caseworker_payload group ---")

        caseworker = Mock(spec=Caseworker)
        caseworker.type = 'group'
        caseworker.ident = 'group-123'
        caseworker.name = 'Support Team'

        payload = nova_functions._build_caseworker_payload(caseworker)

        assert payload['losIdentity']['administrativeUnitId'] == 'group-123'
        assert payload['losIdentity']['fullName'] == 'Support Team'
        print("✅ _build_caseworker_payload correctly builds group payload")
        return True

    def test_build_caseworker_payload_invalid_type(self):
        """Test _build_caseworker_payload with invalid type."""
        print("\n--- Testing _build_caseworker_payload invalid type ---")

        caseworker = Mock(spec=Caseworker)
        caseworker.type = 'invalid'
        caseworker.ident = 'test'
        caseworker.name = 'Test'

        try:
            nova_functions._build_caseworker_payload(caseworker)
            print("❌ Should have raised ValueError")
            return False
        except ValueError as e:
            assert "Unknown caseworker type" in str(e)
            print("✅ _build_caseworker_payload raises ValueError for invalid type")
            return True


# ============================================================================
# SERVICE_PLATFORM_FUNCTIONS TESTS
# ============================================================================

class TestServicePlatformFunctions:
    """Tests for service_platform_functions."""

    @patch('robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered')
    def test_send_digital_post_not_registered(self, mock_is_registered):
        """Test send_digital_post when recipient is not registered."""
        print("\n--- Testing send_digital_post not registered ---")

        mock_is_registered.return_value = False

        kombit_access = Mock()
        result = service_platform_functions.send_digital_post(
            kombit_access,
            "test.docx",
            "0101011234"
        )

        assert result is False
        print("✅ send_digital_post returns False for unregistered recipient")
        return True

    @patch('robot_framework.rykker_borgere.service_platform_functions.digital_post.send_message')
    @patch('robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered')
    def test_send_digital_post_success(self, mock_is_registered, mock_send_message):
        """Test send_digital_post successful send."""
        print("\n--- Testing send_digital_post success ---")

        mock_is_registered.return_value = True

        # Create test file
        test_file_path = Path(__file__).parent / "test_digital_post.docx"
        test_content = b"Test PDF content"
        test_file_path.write_bytes(test_content)

        try:
            kombit_access = Mock()
            result = service_platform_functions.send_digital_post(
                kombit_access,
                str(test_file_path),
                "0101011234"
            )

            assert result is True
            mock_send_message.assert_called_once()
            print("✅ send_digital_post successfully sends message")
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
        finally:
            if test_file_path.exists():
                test_file_path.unlink()

    @patch('robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered')
    def test_send_sms_not_registered(self, mock_is_registered):
        """Test send_sms when recipient is not registered."""
        print("\n--- Testing send_sms not registered ---")

        mock_is_registered.return_value = False

        kombit_access = Mock()
        result = service_platform_functions.send_sms(kombit_access, "0101011234")

        assert result is False
        print("✅ send_sms returns False for unregistered recipient")
        return True

    @patch('robot_framework.rykker_borgere.service_platform_functions.digital_post.is_registered')
    @patch('robot_framework.rykker_borgere.service_platform_functions.digital_post.send_message')
    @patch('builtins.open', new_callable=mock_open, read_data="Test SMS content")
    def test_send_sms_success(self, mock_file, mock_send_message, mock_is_registered):
        """Test send_sms successful send."""
        print("\n--- Testing send_sms success ---")

        mock_is_registered.return_value = True

        kombit_access = Mock()
        result = service_platform_functions.send_sms(kombit_access, "0101011234")

        assert result is True
        mock_send_message.assert_called_once()
        mock_file.assert_called_once_with("sms_text.txt", "r")
        print("✅ send_sms successfully sends message")
        return True


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Running comprehensive tests for rykker_borgere")
    print("=" * 70)

    results = []
    test_classes = [TestFillTemplate, TestGetStep, TestNovaFunctions, TestServicePlatformFunctions]

    for test_class in test_classes:
        print(f"\n{'=' * 70}")
        print(f"Testing: {test_class.__name__}")
        print(f"{'=' * 70}")

        instance = test_class()
        for method_name in dir(instance):
            if method_name.startswith('test_'):
                method = getattr(instance, method_name)
                try:
                    passed = method()
                    results.append((f"{test_class.__name__}.{method_name}", passed))
                except Exception as e:
                    print(f"❌ Exception: {e}")
                    results.append((f"{test_class.__name__}.{method_name}", False))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")

    total_passed = sum(1 for _, p in results if p)
    print(f"\nTotal: {total_passed}/{len(results)} tests passed")
