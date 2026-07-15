"""Signed resident document downloads (spec 3.6).

Django-hosted, short-TTL signed URLs — never presigned object-store URLs.
The token binds a version to the requesting user; redemption re-checks the
user and re-runs resident_can_download, so a token can never widen access.
"""

from django.core import signing
from django.db.models import Q

from lamto.accounts.tenancy import active_occupancies
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.models import SETTLED_STATUSES
from lamto.finance.models import PublishedLedgerEntry
from lamto.maintenance.models import ReportPhoto

DOWNLOAD_SALT = "lamto.api.download"
DOWNLOAD_MAX_AGE = 300  # spec 3.6: TTL <= 5 minutes


def sanitize_download_filename(filename: str | None) -> str:
    """Make a stored filename safe for a Content-Disposition ``filename="…"`` value.

    Strips path components, CR/LF, and double-quotes so a hostile or malformed
    stored name cannot break or inject into the response header. Empty results
    fall back to a neutral default.
    """
    if not filename:
        return "download"
    # Drop any directory components (POSIX or Windows separators).
    name = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
    for ch in ("\r", "\n", '"'):
        name = name.replace(ch, "")
    name = name.strip()
    return name or "download"


def issue_download_token(user_id: int, version_id: int) -> str:
    """Signed, TTL-bound token binding a document version to one user."""
    return signing.dumps({"v": version_id, "u": user_id}, salt=DOWNLOAD_SALT)


def resident_can_download(user, version) -> bool:
    """True only for the caller's own report photos and redacted published-ledger
    documents. Originals of staff documents are unreachable from this path."""
    if version.document.kind == Document.Kind.REPORT_PHOTO:
        return ReportPhoto.objects.filter(version=version, report__reporter=user).exists()
    if version.variant != DocumentVersion.Variant.REDACTED:
        return False
    building_ids = list(active_occupancies(user).values_list("unit__building_id", flat=True))
    if not building_ids:
        return False
    return (
        PublishedLedgerEntry.objects.filter(
            case__building_id__in=building_ids,
            snapshot__outbox_event__status__in=SETTLED_STATUSES,
        )
        .filter(
            Q(work_order__acceptance__invoice_redacted=version)
            | Q(work_order__acceptance__acceptance_redacted=version)
            | Q(payment__proof_redacted=version)
        )
        .exists()
    )
