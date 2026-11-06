# LamTo demo

The terminal below prints the addresses, the logins and a QR code once the demo
is up (a few minutes the first time). To see them again:

    bash ops/codespace/show.sh

## The demo flow

1. **Phone:** scan the QR code and sign in to the Resident app with the
   resident phone number and the password.
2. **Phone:** file a report about a lift that shakes badly, with any photo.
3. **Laptop:** open the Management workspace (`/s/`) and sign in with the
   Management email. The report is in the Action inbox.
4. **Laptop:** triage it with the **Thang máy** (Elevator) category.
5. **Laptop:** download the quotation from `/demo-kit/`. Create a proposal
   from the case with it, ask for a Price comparison, and publish it.
6. **Laptop:** make the Proceed decision, then report progress and completion.
7. **Laptop:** settle the proposal with the Transfer proof from `/demo-kit/`.
8. **Phone:** open the spend in the ledger, follow it to the Evidence explorer
   and open the Transfer proof.

Typing without accents, or using dictation, is fine.

## What isn't here

Virus scanning, blockchain anchoring, AI triage and price prediction, and
push notifications are all off. Every name, number and document is synthetic.
Evidence is signed by a key minted inside this Codespace, which is deleted
with it.

GitHub stops a Codespace after 30 minutes without activity in this window.
Your data survives a stop; reopen the Codespace to carry on.
