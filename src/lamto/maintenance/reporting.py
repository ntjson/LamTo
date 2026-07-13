from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from lamto.accounts.models import ResidentOccupancy
from lamto.audit.services import record_audit
from lamto.documents.models import Document, DocumentVersion

from .models import IssueReport, ReportPhoto, TriageJob


@transaction.atomic
def submit_report(resident, unit, text, location, photo_versions) -> IssueReport:
    occupancy = ResidentOccupancy.objects.filter(user=resident, unit=unit, active=True).first()
    if occupancy is None:
        raise PermissionDenied("Active occupancy is required to submit a report.")
    if not isinstance(text, str) or not (text := text.strip()):
        raise ValidationError("Report text is required.")
    if not location.active or location.building_id != unit.building_id:
        raise ValidationError("Report location must be active and belong to the unit building.")
    path_location = location
    seen_locations = set()
    while path_location is not None:
        if (
            path_location.pk in seen_locations
            or not path_location.active
            or path_location.building_id != unit.building_id
        ):
            raise ValidationError("Report location hierarchy must be active and belong to the unit building.")
        seen_locations.add(path_location.pk)
        path_location = path_location.parent

    photo_versions = list(photo_versions)
    photo_ids = [version.pk for version in photo_versions]
    if len(photo_ids) != len(set(photo_ids)):
        raise ValidationError("A photo version can only be attached once.")
    photo_versions = list(
        DocumentVersion.objects.select_for_update()
        .select_related("document")
        .filter(
            pk__in=photo_ids,
            uploader_id=resident.pk,
            document__building_id=unit.building_id,
            document__kind=Document.Kind.REPORT_PHOTO,
            variant=DocumentVersion.Variant.ORIGINAL,
            scan_status=DocumentVersion.ScanStatus.CLEAN,
        )
    )
    if len(photo_versions) != len(photo_ids):
        raise ValidationError("Report photos must be owned, clean original photos in the unit building.")

    report = IssueReport.objects.create(
        reporter=resident,
        unit=unit,
        text=text,
        selected_location=location,
        location_path_snapshot=location.path_label,
    )
    ReportPhoto.objects.bulk_create(
        [ReportPhoto(report=report, version=version) for version in photo_versions]
    )
    TriageJob.objects.create(report=report)
    record_audit(
        actor=resident,
        membership=None,
        action="report.submit",
        target_type="IssueReport",
        target_id=str(report.pk),
        result="accepted",
        metadata={"occupancy_id": occupancy.pk},
    )
    return report
