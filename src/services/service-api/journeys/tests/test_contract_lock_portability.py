from __future__ import annotations

import hashlib

from django.test import SimpleTestCase

from journeys.contracts import LockedFixtures, _canonical_text_bytes


class ContractLockPortabilityTests(SimpleTestCase):
    def test_checkout_line_endings_do_not_change_canonical_text_hash(self) -> None:
        canonical = b'{\n  "status": "PARTIAL"\n}\n'
        checkout = canonical.replace(b"\n", b"\r\n")

        self.assertEqual(
            hashlib.sha256(_canonical_text_bytes(checkout)).hexdigest(),
            hashlib.sha256(canonical).hexdigest(),
        )

    def test_locked_fixtures_load_from_the_current_checkout(self) -> None:
        fixtures = LockedFixtures()

        self.assertEqual(fixtures.get("routing_response")["contractVersion"], "1.0")
