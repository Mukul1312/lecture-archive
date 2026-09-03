"""Focused Cartesia transport-contract boundary tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.platform.cartesia.contract import (
    CARTESIA_TRANSPORT_CONTRACT,
    CartesiaTransportContract,
)


class CartesiaTransportContractTests(unittest.TestCase):
    def test_contract_freezes_the_verified_https_sse_endpoint(self) -> None:
        """Changing the API host or accepting HTTP would risk credential disclosure."""
        endpoint = urlsplit(CARTESIA_TRANSPORT_CONTRACT.origin)

        self.assertEqual(endpoint.scheme, "https")
        self.assertEqual(endpoint.netloc, "api.cartesia.ai")
        self.assertEqual(CARTESIA_TRANSPORT_CONTRACT.sse_path, "/tts/sse")
        self.assertFalse(urlsplit(CARTESIA_TRANSPORT_CONTRACT.sse_path).scheme)
        self.assertFalse(urlsplit(CARTESIA_TRANSPORT_CONTRACT.sse_path).netloc)

    def test_contract_contains_only_positive_bounded_client_safety_limits(self) -> None:
        """Removing a bound could permit an unbounded provider stream or retry."""
        contract = CARTESIA_TRANSPORT_CONTRACT

        self.assertEqual(contract.api_version_header, "Cartesia-Version")
        self.assertEqual(contract.api_version, "2026-08-14")
        self.assertEqual(contract.authentication_header, "Authorization")
        self.assertEqual(contract.connect_timeout_seconds, 10)
        self.assertEqual(contract.write_timeout_seconds, 10)
        self.assertEqual(contract.read_timeout_seconds, 30)
        self.assertEqual(contract.operation_timeout_seconds, 180)
        self.assertEqual(contract.maximum_submissions, 3)
        self.assertEqual(contract.retry_backoff_seconds, (1, 3))
        self.assertEqual(contract.maximum_retry_after_seconds, 30)
        self.assertEqual(contract.maximum_event_bytes, 1 * 1024 * 1024)
        self.assertEqual(contract.maximum_response_bytes, 32 * 1024 * 1024)
        self.assertEqual(contract.maximum_decoded_pcm_bytes, 16 * 1024 * 1024)
        self.assertTrue(
            all(
                value > 0
                for value in (
                    contract.connect_timeout_seconds,
                    contract.write_timeout_seconds,
                    contract.read_timeout_seconds,
                    contract.operation_timeout_seconds,
                    contract.maximum_retry_after_seconds,
                    contract.maximum_event_bytes,
                    contract.maximum_response_bytes,
                    contract.maximum_decoded_pcm_bytes,
                )
            )
        )
        self.assertLessEqual(contract.maximum_submissions, 3)
        self.assertLessEqual(contract.maximum_decoded_pcm_bytes, contract.maximum_response_bytes)

    def test_contract_disables_redirects_and_environment_proxy_inheritance(self) -> None:
        """Enabling either option could transmit provider credentials to another host."""
        self.assertEqual(
            CARTESIA_TRANSPORT_CONTRACT.http_client_options(),
            {"follow_redirects": False, "trust_env": False},
        )

    def test_contract_is_a_frozen_platform_value(self) -> None:
        """Mutating protocol facts after preview would break the frozen transport boundary."""
        self.assertIsInstance(CARTESIA_TRANSPORT_CONTRACT, CartesiaTransportContract)
        with self.assertRaises(FrozenInstanceError):
            CARTESIA_TRANSPORT_CONTRACT.origin = "https://example.invalid"
