from django import forms
from django.core.exceptions import ValidationError
from django.forms.widgets import Input

from lamto.documents.scanner import scan_with_clamav
from lamto.documents.services import (
    DocumentUploadQuarantined,
    DocumentUploadRejected,
    create_resident_report_photo,
)
from lamto.maintenance.models import BuildingLocation
from lamto.maintenance.ratings import rate_completed_work
from lamto.maintenance.reporting import submit_report


class MultiFileInput(Input):
    """Minimal multi-file input; Django's FileInput rejects the multiple attribute."""

    input_type = "file"
    needs_multipart_form = True
    allow_multiple_selected = True

    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.attrs["multiple"] = True

    def value_from_datadict(self, data, files, name):
        if hasattr(files, "getlist"):
            return files.getlist(name)
        return files.get(name)


class ResidentReportForm(forms.Form):
    text = forms.CharField(
        label="Describe the issue",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "class": "input",
                "autocomplete": "off",
                "data-draft-field": "text",
            }
        ),
        min_length=3,
        max_length=4000,
    )
    location = forms.ModelChoiceField(
        label="Location",
        queryset=BuildingLocation.objects.none(),
        widget=forms.Select(attrs={"class": "input", "data-draft-field": "location"}),
    )
    photos = forms.FileField(
        label="Photos (optional)",
        required=False,
        widget=MultiFileInput(
            attrs={
                "class": "input",
                "accept": "image/jpeg,image/png",
            }
        ),
    )

    def __init__(self, *args, resident=None, occupancy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resident = resident
        self.occupancy = occupancy
        if self.occupancy is not None:
            self.fields["location"].queryset = BuildingLocation.objects.filter(
                building_id=self.occupancy.unit.building_id,
                active=True,
            ).order_by("name")

    def clean_photos(self):
        value = self.cleaned_data.get("photos")
        if not value:
            return []
        if isinstance(value, list):
            return [item for item in value if item]
        return [value]

    def clean(self):
        cleaned = super().clean()
        if self.resident is None or self.occupancy is None:
            raise ValidationError("Active occupancy is required to submit a report.")
        return cleaned

    def save(self, files=None):
        if files is None:
            files = self.cleaned_data.get("photos") or []
        photo_versions = []
        building = self.occupancy.unit.building
        for uploaded in files:
            if not uploaded:
                continue
            try:
                photo_versions.append(
                    create_resident_report_photo(
                        self.resident,
                        building,
                        uploaded,
                        scan_with_clamav,
                    )
                )
            except (DocumentUploadRejected, DocumentUploadQuarantined) as error:
                raise ValidationError(f"Photo upload failed: {error}") from error
        return submit_report(
            self.resident,
            self.occupancy.unit,
            self.cleaned_data["text"],
            self.cleaned_data["location"],
            photo_versions,
        )


class WorkRatingForm(forms.Form):
    score = forms.TypedChoiceField(
        label="Score",
        coerce=int,
        choices=[(i, str(i)) for i in range(1, 6)],
        widget=forms.RadioSelect,
    )
    comment = forms.CharField(
        label="Comment (optional)",
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "class": "input"}),
    )

    def __init__(self, *args, resident=None, work_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resident = resident
        self.work_order = work_order

    def save(self):
        return rate_completed_work(
            self.resident,
            self.work_order,
            self.cleaned_data["score"],
            self.cleaned_data.get("comment") or "",
        )
