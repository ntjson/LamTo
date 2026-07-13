import re

from django.conf import settings
from eth_account import Account
from eth_account.messages import encode_typed_data


BYTES32_RE = re.compile(r"0x[0-9a-f]{64}\Z")


def build_evidence_typed_data(event_id, event_type, payload_hash_hex, previous_hash_hex):
    if any(
        not isinstance(value, str) or not BYTES32_RE.fullmatch(value)
        for value in (event_id, payload_hash_hex, previous_hash_hex)
    ):
        raise ValueError("Evidence IDs and hashes must be lowercase 0x-prefixed bytes32 values.")
    if isinstance(event_type, bool) or not isinstance(event_type, int) or event_type not in range(1, 12):
        raise ValueError("Evidence event type must be an integer from 1 through 11.")
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Evidence": [
                {"name": "eventId", "type": "bytes32"},
                {"name": "payloadHash", "type": "bytes32"},
                {"name": "previousHash", "type": "bytes32"},
                {"name": "eventType", "type": "uint8"},
            ],
        },
        "primaryType": "Evidence",
        "domain": {
            "name": "LamToEvidence",
            "version": "1",
            "chainId": settings.BLOCKCHAIN_CHAIN_ID,
            "verifyingContract": settings.EVIDENCE_CONTRACT_ADDRESS,
        },
        "message": {
            "eventId": event_id,
            "payloadHash": payload_hash_hex,
            "previousHash": previous_hash_hex,
            "eventType": event_type,
        },
    }


def recover_signer(typed_data, signature) -> str:
    return Account.recover_message(
        encode_typed_data(full_message=typed_data), signature=signature
    )
