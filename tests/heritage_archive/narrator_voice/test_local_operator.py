"""The process principal maps only to the configured local operator."""
from pathlib import Path
from secrets import compare_digest
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from heritage_archive.kernel import ActorId, ValidationError
from heritage_archive.contexts.narrator_voice.application.ports import PrincipalAuthority
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied
from heritage_archive.contexts.narrator_voice.domain.evidence import ReviewAuthority
from heritage_archive.contexts.narrator_voice.infrastructure.local_operator import SingleOperatorActorResolver
from tests.heritage_archive.narrator_voice.fixtures import uuid


MODULE = "heritage_archive.contexts.narrator_voice.infrastructure.local_operator"
PRINCIPAL = "fixture-Process-Principal"


class SingleOperatorActorResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver_type = SingleOperatorActorResolver
        self.actor_id = ActorId(uuid(801))
        self.resolver = self.resolver_type(PRINCIPAL, self.actor_id)

    def test_exact_principal_repeatedly_resolves_stable_operational_actor(self):
        expected = PrincipalAuthority(self.actor_id, True, ReviewAuthority.OPERATIONAL, None)
        for _ in range(3):
            authority = self.resolver.resolve_principal(PRINCIPAL)
            self.assertEqual(authority, expected)
            self.assertIs(authority.actor_id, self.actor_id)

    def test_comparable_principals_use_one_exact_constant_time_comparison(self):
        with patch(MODULE + ".compare_digest", wraps=compare_digest) as compare:
            self.resolver.resolve_principal(PRINCIPAL)
            compare.assert_called_once_with(PRINCIPAL, PRINCIPAL)
            compare.reset_mock()
            with self.assertRaises(AuthorizationDenied):
                self.resolver.resolve_principal("fixture-unknown-principal")
            compare.assert_called_once_with("fixture-unknown-principal", PRINCIPAL)

    def test_unknown_and_malformed_principals_have_the_same_redacted_denial(self):
        denied = (
            PRINCIPAL.lower(), " " + PRINCIPAL, PRINCIPAL + " ",
            PRINCIPAL[:-1], PRINCIPAL + "-suffix", "fixture-unknown-principal",
            None, PRINCIPAL.encode("ascii"), [], object(), "", "\u0b13", "\ud800",
        )
        for principal in denied:
            with self.subTest(principal=principal):
                with self.assertRaises(AuthorizationDenied) as raised:
                    self.resolver.resolve_principal(principal)
                self.assertEqual(str(raised.exception), "principal_not_authorized")
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_configuration_rejects_invalid_principal_or_actor_without_values(self):
        class StringSubclass(str):
            pass

        for principal, actor in (
            (None, self.actor_id), (b"fixture-principal", self.actor_id),
            ("", self.actor_id), ("\u0b13", self.actor_id), ("\ud800", self.actor_id),
            (StringSubclass(PRINCIPAL), self.actor_id),
            (PRINCIPAL, self.actor_id.value), (PRINCIPAL, None),
        ):
            with self.subTest(principal=principal, actor=actor):
                with self.assertRaises(ValidationError) as raised:
                    self.resolver_type(principal, actor)
                self.assertEqual(str(raised.exception), "invalid_single_operator_configuration")


if __name__ == "__main__":
    unittest.main()
