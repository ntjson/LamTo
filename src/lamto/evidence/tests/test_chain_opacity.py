"""Chain-payload opacity audit (spec 2.2).

Only opaque values reach the chain: random event IDs and payload hashes.
These tests freeze the properties that keep payload hashes non-invertible
and keep identifying free text (building names, personal content) out of
evidence payload schemas forever.
"""

from django.test import SimpleTestCase

from lamto.evidence.models import EvidenceType
from lamto.evidence.services import EVIDENCE_PAYLOAD_SCHEMAS

# Closed vocabulary of value shapes. Anything else — in particular any
# free-text shape — is an opacity regression and must not be added.
OPAQUE_SHAPES = {"id", "positive_int", "money", "bool", "hash", "hashes", "bytes32", "timestamp"}
HASH_SHAPES = {"hash", "hashes", "bytes32"}


class ChainOpacityTests(SimpleTestCase):
    def test_every_event_type_has_a_schema(self):
        self.assertEqual(set(EVIDENCE_PAYLOAD_SCHEMAS), set(EvidenceType.values))

    def test_payload_schemas_admit_only_opaque_shapes(self):
        for event_type, (required, optional) in EVIDENCE_PAYLOAD_SCHEMAS.items():
            for field, shape in {**required, **optional}.items():
                with self.subTest(event_type=event_type, field=field):
                    if isinstance(shape, frozenset):
                        # Closed enums only: uppercase machine tokens, no names.
                        for member in shape:
                            self.assertRegex(member, r"^[A-Z_]+$")
                    else:
                        self.assertIn(shape, OPAQUE_SHAPES)

    def test_every_schema_requires_a_hash_field(self):
        # At least one 256-bit unknown per payload keeps the on-chain
        # payload hash non-invertible by dictionary attack.
        for event_type, (required, _optional) in EVIDENCE_PAYLOAD_SCHEMAS.items():
            with self.subTest(event_type=event_type):
                self.assertTrue(
                    HASH_SHAPES.intersection(required.values()),
                    f"event type {event_type} has no required hash field",
                )
