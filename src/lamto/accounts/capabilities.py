from .models import Organization


REPORT_TRIAGE = "report.triage"
WORK_ASSIGN = "work.assign"
PROPOSAL_CREATE = "proposal.create"
PROPOSAL_APPROVE = "proposal.approve"
EMERGENCY_AUTHORIZE = "emergency.authorize"
WORK_ACCEPT = "work.accept"
PAYMENT_RECORD = "payment.record"
PAYMENT_VERIFY = "payment.verify"
FUND_RECORD = "fund.record"
FUND_VERIFY = "fund.verify"
LEDGER_PUBLISH = "ledger.publish"
CORRECTION_CREATE = "correction.create"
CORRECTION_APPROVE = "correction.approve"
AUDIT_EXPORT = "audit.export"
TECH_ADMIN = "tech.admin"


ALLOWED_ORGANIZATION_KINDS = {
    REPORT_TRIAGE: {Organization.Kind.OPERATOR},
    WORK_ASSIGN: {Organization.Kind.OPERATOR},
    PROPOSAL_CREATE: {Organization.Kind.OPERATOR},
    PROPOSAL_APPROVE: {Organization.Kind.BOARD, Organization.Kind.RESIDENT_REP},
    EMERGENCY_AUTHORIZE: {Organization.Kind.BOARD},
    WORK_ACCEPT: {Organization.Kind.BOARD},
    PAYMENT_RECORD: {Organization.Kind.BOARD},
    PAYMENT_VERIFY: {Organization.Kind.BOARD},
    FUND_RECORD: {Organization.Kind.BOARD},
    FUND_VERIFY: {Organization.Kind.BOARD},
    LEDGER_PUBLISH: {Organization.Kind.BOARD},
    CORRECTION_CREATE: {Organization.Kind.OPERATOR},
    CORRECTION_APPROVE: {Organization.Kind.BOARD, Organization.Kind.RESIDENT_REP},
    AUDIT_EXPORT: {Organization.Kind.AUDITOR},
    TECH_ADMIN: {Organization.Kind.PLATFORM},
}
