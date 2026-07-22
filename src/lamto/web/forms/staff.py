"""Staff workspace forms — mutations go through domain services only."""

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError

from lamto.accounts.models import ManagementMembership
from lamto.documents.models import Document, DocumentVersion
from lamto.finance.models import MaintenanceFundEntry
from lamto.maintenance.models import BuildingLocation
from lamto.maintenance.triage import confirm_triage
from lamto.notifications.models import NotificationPreference
from lamto.notifications.services import PREFERENCE_EVENT_CHOICES


class MembershipSwitchForm(forms.Form):
    membership = forms.ModelChoiceField(
        queryset=ManagementMembership.objects.none(),
        label="Active membership",
    )

    def __init__(self, *args, memberships=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership"].queryset = memberships or ManagementMembership.objects.none()


class ConfirmTriageForm(forms.Form):
    category = forms.CharField(max_length=128, widget=forms.TextInput(attrs={"class": "input"}))
    urgency = forms.ChoiceField(
        # Must match lamto.maintenance.ai.URGENCIES / confirm_triage.
        choices=[
            ("LOW", "Low"),
            ("MEDIUM", "Medium"),
            ("HIGH", "High"),
        ],
        widget=forms.Select(attrs={"class": "input"}),
    )
    location = forms.ModelChoiceField(
        queryset=BuildingLocation.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
    )
    department = forms.CharField(
        max_length=128,
        label="Management queue",
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    deadline_minutes = forms.TypedChoiceField(
        choices=[
            (60, "1 hour"),
            (240, "4 hours"),
            (480, "8 hours"),
            (1440, "1 day"),
            (2880, "2 days"),
            (4320, "3 days"),
            (10080, "1 week"),
        ],
        coerce=int,
        widget=forms.Select(attrs={"class": "input"}),
        label="Deadline",
    )

    def __init__(self, *args, building_id=None, extra_deadline_minutes=None, **kwargs):
        super().__init__(*args, **kwargs)
        if building_id is not None:
            self.fields["location"].queryset = BuildingLocation.objects.filter(
                building_id=building_id, active=True
            ).order_by("name")
        if extra_deadline_minutes is not None:
            choices = list(self.fields["deadline_minutes"].choices)
            if not any(int(v) == extra_deadline_minutes for v, _ in choices):
                self.fields["deadline_minutes"].choices = [
                    (extra_deadline_minutes, f"{extra_deadline_minutes} minutes"),
                    *choices,
                ]

    def save(self, report, operator):
        return confirm_triage(
            report,
            operator,
            self.cleaned_data["category"],
            self.cleaned_data["urgency"],
            self.cleaned_data["location"],
            self.cleaned_data["department"],
            self.cleaned_data["deadline_minutes"],
        )


class InfoRequestForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea, label="What information is missing?")


class DeclineReportForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea, label="Reason shown to the resident")
    confirm = forms.BooleanField(
        required=True,
        label="I understand this decline will be sent to the resident and cannot be undone.",
    )


class ProgressUpdateForm(forms.Form):
    cause = forms.CharField(widget=forms.Textarea(attrs={"class": "input", "rows": 3}))
    result = forms.CharField(widget=forms.Textarea(attrs={"class": "input", "rows": 3}))
    before_versions = forms.ModelMultipleChoiceField(
        queryset=DocumentVersion.objects.none(),
        widget=forms.SelectMultiple(attrs={"class": "input"}),
        label="Before photos",
        required=False,
    )
    after_versions = forms.ModelMultipleChoiceField(
        queryset=DocumentVersion.objects.none(),
        widget=forms.SelectMultiple(attrs={"class": "input"}),
        label="After photos",
        required=False,
    )

    def __init__(self, *args, building_id=None, uploader_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        base = DocumentVersion.objects.filter(
            document__building_id=building_id,
            uploader_id=uploader_id,
            scan_status=DocumentVersion.ScanStatus.CLEAN,
        )
        self.fields["before_versions"].queryset = base.filter(
            document__kind=Document.Kind.BEFORE_PHOTO
        )
        self.fields["after_versions"].queryset = base.filter(
            document__kind=Document.Kind.AFTER_PHOTO
        )

        def _label(obj):
            return (
                f"{obj.filename} (v{obj.version})"
                if getattr(obj, "filename", None)
                else str(obj.pk)
            )

        self.fields["before_versions"].label_from_instance = _label
        self.fields["after_versions"].label_from_instance = _label

class RecordSettlementTransferForm(forms.Form):
    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    payee_name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "input"}))
    bank_reference = forms.CharField(max_length=64, widget=forms.TextInput(attrs={"class": "input"}))
    proof = forms.ChoiceField(choices=(), widget=forms.Select(attrs={"class": "input"}))

    def __init__(self, *args, proof_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proof"].choices = [("", "Select evidence…"), *proof_choices]


class RecordSettlementAcknowledgementForm(forms.Form):
    event_id = forms.CharField(max_length=66, widget=forms.HiddenInput())
    proof = forms.ChoiceField(choices=(), widget=forms.Select(attrs={"class": "input"}))

    def __init__(self, *args, proof_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proof"].choices = [("", "Select evidence…"), *proof_choices]


class NotificationPreferenceForm(forms.Form):
    """Email/push opt-in flags per material event; in-app remains required."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        from lamto.notifications.services import RESIDENT_PUSH_EVENT_CODES

        existing = list(NotificationPreference.objects.filter(user=user))
        email_prefs = {p.event_code: p.email_enabled for p in existing}
        push_prefs = {p.event_code: p.push_enabled for p in existing}
        for code, label in PREFERENCE_EVENT_CHOICES:
            self.fields[f"email_{code}"] = forms.BooleanField(
                label=f"Email: {label}",
                required=False,
                initial=email_prefs.get(code, True),
            )
            if code not in RESIDENT_PUSH_EVENT_CODES:
                continue
            self.fields[f"push_{code}"] = forms.BooleanField(
                label=f"Push: {label}",
                required=False,
                initial=push_prefs.get(code, True),
            )

    def save(self):
        if self.user is None:
            raise ValidationError("User is required.")
        from lamto.notifications.services import RESIDENT_PUSH_EVENT_CODES

        for code, _label in PREFERENCE_EVENT_CHOICES:
            defaults = {"email_enabled": bool(self.cleaned_data.get(f"email_{code}"))}
            if code in RESIDENT_PUSH_EVENT_CODES and f"push_{code}" in self.fields:
                defaults["push_enabled"] = bool(self.cleaned_data.get(f"push_{code}"))
            NotificationPreference.objects.update_or_create(
                user=self.user,
                event_code=code,
                defaults=defaults,
            )


class CreateProposalForm(forms.Form):
    """Management-entered proposal draft; the quotation uploads on prepare."""

    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    contractor_name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "input"}))
    fund_code = forms.CharField(max_length=32, required=False, initial="GENERAL", widget=forms.TextInput(attrs={"class": "input"}))
    purpose = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": "input"}))
    proposed_action = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": "input"}))
    expected_schedule = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "input"}))
    quotation = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))


class StandaloneProposalForm(CreateProposalForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("fund_code", "purpose", "proposed_action", "expected_schedule"):
            self.fields[name].required = True


class RecordFundSourceForm(forms.Form):
    """Fund source draft; the evidence uploads on prepare."""

    entry_type = forms.ChoiceField(
        choices=[
            (MaintenanceFundEntry.EntryType.OPENING_BALANCE, "Opening balance"),
            (MaintenanceFundEntry.EntryType.INFLOW, "Inflow"),
        ],
        widget=forms.Select(attrs={"class": "input"}),
    )
    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    evidence = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))
