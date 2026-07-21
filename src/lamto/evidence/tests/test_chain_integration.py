"""Live Besu + EvidenceRegistry integration tests.

Skipped unless CHAIN_INTEGRATION=1 and a JSON-RPC endpoint is reachable.
"""

from __future__ import annotations

import os
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

from lamto.accounts.models import (
    Building,
    ManagementMembership,
    SignerAuthorizationRequest,
)
from lamto.config.secrets import coalesce_secret
from lamto.evidence.canonical import payload_hash
from lamto.evidence.chain import EvidenceRegistryClient
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import (
    begin_wallet_registration,
    queue_signed_event,
    register_wallet,
    revoke_wallet,
)
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.evidence.worker import process_outbox_event, sync_signer_authorizations


HASH = "a" * 64
PROPOSAL_PAYLOAD = {
    "proposal_id": 1,
    "proposal_version": 1,
    "record_id": 2,
    "work_order_id": 3,
    "case_id": 4,
    "report_id": 5,
    "amount_vnd": 18_500_000,
    "proposal_snapshot_hash": HASH,
    "work_snapshot_hash": HASH,
    "case_snapshot_hash": HASH,
    "report_snapshot_hash": HASH,
    "quotation_original_hash": HASH,
    "quotation_redacted_hash": HASH,
}

# Anvil/Hardhat default account #0 — funded in qbft genesis alloc.
# Empty or whitespace-only values from a sourced `.env.example` must not
# override the default (os.environ.get returns "" / "   " when set but blank).
_DEFAULT_OWNER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
OWNER_KEY = coalesce_secret(
    os.environ.get("BLOCKCHAIN_CONTRACT_OWNER_PRIVATE_KEY"),
    default=_DEFAULT_OWNER_KEY,
)
OWNER_ADDRESS = Account.from_key(OWNER_KEY).address
RPC_URL = os.environ.get("BLOCKCHAIN_RPC_URL", os.environ.get("CHAIN_RPC_URL", "http://127.0.0.1:8545"))
CONTRACT_ADDRESS = os.environ.get("EVIDENCE_CONTRACT_ADDRESS", "")
CHAIN_INTEGRATION = os.environ.get("CHAIN_INTEGRATION", "") == "1"


def _rpc_reachable() -> bool:
    if not CHAIN_INTEGRATION:
        return False
    if not CONTRACT_ADDRESS or CONTRACT_ADDRESS == "0x" + "00" * 20:
        return False
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 3}))
        return bool(w3.is_connected())
    except Exception:
        return False


@skipUnless(_rpc_reachable(), "CHAIN_INTEGRATION=1 with live Besu RPC and contract required")
@override_settings(
    BLOCKCHAIN_CHAIN_ID=int(os.environ.get("BLOCKCHAIN_CHAIN_ID", "1337")),
    BLOCKCHAIN_RPC_URL=RPC_URL,
    EVIDENCE_CONTRACT_ADDRESS=CONTRACT_ADDRESS,
    BLOCKCHAIN_CONTRACT_OWNER_PRIVATE_KEY=OWNER_KEY,
    WALLET_REGISTRATION_TTL_SECONDS=600,
)
class ChainIntegrationTests(TestCase):
    def setUp(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.owner = Account.from_key(OWNER_KEY)
        # Ephemeral relayer funded by the owner for this test only.
        self.relayer = Account.create()
        fund_tx = {
            "to": self.relayer.address,
            "value": self.w3.to_wei(1, "ether"),
            "nonce": self.w3.eth.get_transaction_count(self.owner.address),
            "gas": 21_000,
            "maxFeePerGas": self.w3.to_wei(2, "gwei"),
            "maxPriorityFeePerGas": self.w3.to_wei(1, "gwei"),
            "chainId": int(os.environ.get("BLOCKCHAIN_CHAIN_ID", "1337")),
        }
        signed = self.owner.sign_transaction(fund_tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = self.w3.eth.send_raw_transaction(raw)
        self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        self.client = EvidenceRegistryClient(
            rpc_url=RPC_URL,
            contract_address=CONTRACT_ADDRESS,
            relayer_private_key=self.relayer.key.hex(),
            owner_private_key=OWNER_KEY,
            chain_id=int(os.environ.get("BLOCKCHAIN_CHAIN_ID", "1337")),
        )

        building = Building.objects.create(name="Integration Building")
        user = get_user_model().objects.create_user(
            email="integration@example.test",
            password="secret",
            display_name="integration",
        )
        self.membership = ManagementMembership.objects.create(user=user, building=building)
        self.stakeholder = Account.create()
        challenge = begin_wallet_registration(self.membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), self.stakeholder.key
        ).signature.hex()
        self.wallet = register_wallet(
            self.membership, self.stakeholder.address.lower(), proof
        )
        sync_signer_authorizations(client=self.client)
        auth = SignerAuthorizationRequest.objects.get(wallet=self.wallet)
        self.assertEqual(auth.status, SignerAuthorizationRequest.Status.CONFIRMED)

    def tearDown(self):
        try:
            if hasattr(self, "wallet") and self.wallet.active:
                revoke_wallet(self.wallet, self.membership)
                sync_signer_authorizations(client=self.client)
        except Exception:
            pass

    def test_signed_event_confirms_once_on_live_chain(self):
        event_id = "0x" + "ab" * 32
        payload = dict(PROPOSAL_PAYLOAD)
        previous = "0x" + "00" * 32
        typed = build_evidence_typed_data(
            event_id,
            EvidenceType.PROPOSAL_CREATED,
            "0x" + payload_hash(payload),
            previous,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), self.stakeholder.key
        ).signature.hex()
        with transaction.atomic():
            event = queue_signed_event(
                event_id,
                EvidenceType.PROPOSAL_CREATED,
                payload,
                previous,
                self.membership,
                signature,
            )

        first = process_outbox_event(event.id, client=self.client)
        second = process_outbox_event(event.id, client=self.client)

        self.assertEqual(first.status, BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(second.status, BlockchainOutboxEvent.Status.CONFIRMED)
        self.assertEqual(first.transaction_hash, second.transaction_hash)
        self.assertTrue(first.transaction_hash)
        record = self.client.find(event)
        self.assertIsNotNone(record)
        self.assertEqual(record.event_type, EvidenceType.PROPOSAL_CREATED)
        self.assertEqual(
            record.signer.lower(), self.stakeholder.address.lower()
        )
