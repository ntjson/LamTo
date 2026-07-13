# Pilot acceptance report

**Building / pilot name:** _______________________  
**Date window:** _______________________  
**Environment:** (non-prod / pilot) _______________________  
**Build / commit SHA:** _______________________  

## Scope completed

| Scenario | Pass? | Evidence (test log / ticket / screenshot) |
|----------|-------|-------------------------------------------|
| Normal path (report → published ledger → auditor verify) | ☐ | |
| Chain paused: work pending anchor; publish blocked then retry same IDs | ☐ | |
| Payment self-verify denied; publisher dual-control denials | ☐ | |
| Proposal revision after signature requires re-approval | ☐ | |
| AI/email outage: report + action inbox authoritative | ☐ | |
| Role/object/file access denials | ☐ | |
| Emergency drill isolated (no fund post, permanent label) | ☐ | |
| Emergency outcomes: ratified / rejected / overdue | ☐ | |
| Tamper mismatch + correction preserves original / fund reconciles | ☐ | |
| Backup/outbox replay idempotent (no duplicate rows) | ☐ | |

## Automated results

```
# paste: manage.py test lamto.finance.tests.test_pilot_acceptance
# paste: pytest tests/e2e (or e2e-env-fail.log if browser blocked)
# paste: verify_integrity / restore-drill notes if run
```

## Fund / integrity snapshot

- Opening / pre-pilot balance: ________ VND  
- Post normal-path balance: ________ VND  
- Drill fund delta (must be 0): ________ VND  
- Duplicate financial/chain rows found: ________ (must be 0)  
- Unresolved high-severity findings: ________ (must be 0)  

## Sign-off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Board | | | |
| Operator | | | |
| Resident representative | | | |
| Auditor | | | |
| Maintenance | | | |
| Participating resident | | | |

## Attestations

- [ ] No safety incident was manufactured for the pilot.
- [ ] Safety action was never delayed for pilot or chain availability.
- [ ] Pilot was not held open awaiting an emergency.
- [ ] Wallet private keys were not exported to shared channels.
- [ ] Drill records remain permanently labeled and non-convertible.

**Overall decision:** ☐ Accept  ☐ Accept with observations  ☐ Reject  

**Notes:**  
_________________________________________________________________
_________________________________________________________________
