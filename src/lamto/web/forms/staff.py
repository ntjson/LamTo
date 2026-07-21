"""Staff workspace forms — mutations go through domain services only."""

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError

from lamto.accounts.models import OrganizationMembership
from lamto.documents.models import Document, DocumentVersion
from lamto.finance.acceptance import accept_work
from lamto.finance.models import MaintenanceFundEntry, PaymentVerification
from lamto.finance.payments import record_payment, verify_payment
from lamto.maintenance.models import BuildingLocation
from lamto.maintenance.triage import confirm_triage
from lamto.maintenance.workorders import (
    complete_work_order,
    create_work_order,
    start_work_order,
)
from lamto.notifications.models import NotificationPreference
from lamto.notifications.services import PREFERENCE_EVENT_CHOICES


class MembershipSwitchForm(forms.Form):
    membership = forms.ModelChoiceField(
        queryset=OrganizationMembership.objects.none(),
        label="Active membership",
    )

    def __init__(self, *args, memberships=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership"].queryset = memberships or OrganizationMembership.objects.none()


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
    department = forms.CharField(max_length=128, widget=forms.TextInput(attrs={"class": "input"}))
    deadline_minutes = forms.IntegerField(
        min_value=1, widget=forms.NumberInput(attrs={"class": "input"})
    )

    def __init__(self, *args, building_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        if building_id is not None:
            self.fields["location"].queryset = BuildingLocation.objects.filter(
                building_id=building_id, active=True
            ).order_by("name")

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


class CreateWorkOrderForm(forms.Form):
    assignee = forms.ModelChoiceField(
        queryset=OrganizationMembership.objects.none(),
        label="Assignee (maintenance membership)",
        widget=forms.Select(attrs={"class": "input"}),
    )
    requires_spending = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, building_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        if building_id is not None:
            self.fields["assignee"].queryset = OrganizationMembership.objects.filter(
                active=True,
                role=OrganizationMembership.Role.MAINTENANCE,
                organization__building_id=building_id,
            ).select_related("user")

    def save(self, case, operator):
        membership = self.cleaned_data["assignee"]
        return create_work_order(
            case,
            operator,
            membership.user,
            bool(self.cleaned_data.get("requires_spending")),
        )


class CompleteWorkOrderForm(forms.Form):
    cause = forms.CharField(widget=forms.Textarea(attrs={"class": "input", "rows": 3}))
    result = forms.CharField(widget=forms.Textarea(attrs={"class": "input", "rows": 3}))
    before_versions = forms.ModelMultipleChoiceField(
        queryset=DocumentVersion.objects.none(),
        widget=forms.SelectMultiple(attrs={"class": "input"}),
        label="Before photos",
    )
    after_versions = forms.ModelMultipleChoiceField(
        queryset=DocumentVersion.objects.none(),
        widget=forms.SelectMultiple(attrs={"class": "input"}),
        label="After photos",
    )

    def __init__(self, *args, building_id=None, uploader_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        base = DocumentVersion.objects.filter(
            document__building_id=building_id,
            uploader_id=uploader_id,
            variant=DocumentVersion.Variant.ORIGINAL,
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

    def save(self, work_order, maintenance_user):
        return complete_work_order(
            work_order,
            maintenance_user,
            self.cleaned_data["cause"],
            self.cleaned_data["result"],
            list(self.cleaned_data["before_versions"]),
            list(self.cleaned_data["after_versions"]),
        )


class SignedDecisionForm(forms.Form):
    """Common fields for wallet-signed domain actions."""

    # Do not emit HTML5 required= on signature: wallet-signing.js fills it on
    # submit via MetaMask. Server-side validation still requires the field.
    use_required_attribute = False

    # Hidden: pilots must not type event ids / signatures. Server + MetaMask own them.
    event_id = forms.CharField(max_length=66, widget=forms.HiddenInput())
    signature = forms.CharField(
        max_length=132,
        required=False,
        widget=forms.HiddenInput(),
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 2}),
    )

    def clean_signature(self):
        value = (self.cleaned_data.get("signature") or "").strip()
        if not value:
            raise forms.ValidationError(
                "Signature is required. Keep your entries, connect the wallet "
                "registered for this role, and submit again."
            )
        return value


class AcceptWorkForm(SignedDecisionForm):
    actual_cost_vnd = forms.IntegerField(
        min_value=1, widget=forms.NumberInput(attrs={"class": "input"})
    )
    invoice_pair = forms.ChoiceField(
        choices=(),
        widget=forms.Select(attrs={"class": "input"}),
        error_messages={"invalid_choice": "Select valid evidence."},
        label="Invoice evidence",
    )
    acceptance_pair = forms.ChoiceField(
        choices=(),
        widget=forms.Select(attrs={"class": "input"}),
        error_messages={"invalid_choice": "Select valid evidence."},
        label="Acceptance report evidence",
    )

    def __init__(self, *args, invoice_choices=None, acceptance_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        inv = [("", "Select evidence…")] + list(invoice_choices or [])
        acc = [("", "Select evidence…")] + list(acceptance_choices or [])
        self.fields["invoice_pair"].choices = inv
        self.fields["acceptance_pair"].choices = acc

    def save(self, work_order, membership, documents):
        return accept_work(
            work_order,
            membership,
            self.cleaned_data["actual_cost_vnd"],
            documents["invoice_original"],
            documents["invoice_redacted"],
            documents["acceptance_original"],
            documents["acceptance_redacted"],
            self.cleaned_data["signature"],
            self.cleaned_data["event_id"],
        )


class RecordPaymentForm(SignedDecisionForm):
    bank_reference = forms.CharField(
        max_length=128, widget=forms.TextInput(attrs={"class": "input"})
    )
    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    external_status = forms.ChoiceField(
        choices=[("COMPLETED", "Completed"), ("FAILED", "Failed"), ("REVERSED", "Reversed")],
        widget=forms.Select(attrs={"class": "input"}),
    )
    proof_pair = forms.ChoiceField(
        choices=(),
        widget=forms.Select(attrs={"class": "input"}),
        error_messages={"invalid_choice": "Select valid evidence."},
        label="Payment proof evidence",
    )
    payment_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    # Must match the timestamp baked into EIP-712 typed data shown to MetaMask.
    # Using timezone.now() again on POST would change the payload hash and make
    # ecrecover return a random "signed as" address for a valid recorder signature.
    completed_at = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, proof_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proof_pair"].choices = [("", "Select evidence…")] + list(
            proof_choices or []
        )

    def save(self, acceptance, membership, proof_original, proof_redacted, completed_at=None):
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime
        from lamto.finance.payments import allocate_payment_id

        payment_id = self.cleaned_data.get("payment_id") or allocate_payment_id()
        pinned = completed_at
        if pinned is None:
            raw = (self.cleaned_data.get("completed_at") or "").strip()
            pinned = parse_datetime(raw) if raw else None
        if pinned is not None and timezone.is_naive(pinned):
            pinned = timezone.make_aware(pinned, timezone.utc)
        if pinned is None:
            pinned = timezone.now()
        return record_payment(
            acceptance,
            membership,
            self.cleaned_data["bank_reference"],
            self.cleaned_data["amount_vnd"],
            self.cleaned_data["external_status"],
            pinned,
            proof_original,
            proof_redacted,
            self.cleaned_data["signature"],
            self.cleaned_data["event_id"],
            payment_id,
        )


class VerifyPaymentForm(SignedDecisionForm):
    decision = forms.ChoiceField(
        choices=[
            (PaymentVerification.Decision.VERIFIED, "Verified"),
            (PaymentVerification.Decision.REJECTED, "Rejected"),
        ],
        widget=forms.Select(attrs={"class": "input"}),
    )

    def save(self, payment, membership):
        return verify_payment(
            payment,
            membership,
            self.cleaned_data["decision"],
            self.cleaned_data.get("reason") or "",
            self.cleaned_data["signature"],
            self.cleaned_data["event_id"],
        )


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


class PreparePublicationForm(SignedDecisionForm):
    """Board ledger publication (signed)."""

    publication_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    # Must match EIP-712 publication_timestamp baked into typed data.
    publication_timestamp = forms.CharField(widget=forms.HiddenInput())

    def save(self, proposal, membership):
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        from lamto.finance.publication import prepare_publication

        raw = (self.cleaned_data.get("publication_timestamp") or "").strip()
        ts = parse_datetime(raw) if raw else None
        if ts is not None and timezone.is_naive(ts):
            ts = timezone.make_aware(ts, timezone.utc)
        return prepare_publication(
            proposal,
            membership,
            self.cleaned_data["signature"],
            self.cleaned_data["event_id"],
            publication_id=self.cleaned_data.get("publication_id") or None,
            timestamp=ts,
        )


class CreateProposalForm(forms.Form):
    """Operator-entered proposal draft; the quotation pair uploads on prepare."""

    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    contractor_name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "input"}))
    quotation_original = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))
    quotation_redacted = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))


class SignProposalForm(SignedDecisionForm):
    """Signed submit of the frozen proposal version. Hidden fields carry the
    prepared draft so the posted signature matches the exact payload."""

    amount_vnd = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    contractor_name = forms.CharField(max_length=255, widget=forms.HiddenInput())
    quotation_original_id = forms.IntegerField(widget=forms.HiddenInput())
    proposal_id = forms.IntegerField(widget=forms.HiddenInput())


class RecordFundSourceForm(forms.Form):
    """Fund source draft; the evidence pair uploads on prepare."""

    entry_type = forms.ChoiceField(
        choices=[
            (MaintenanceFundEntry.EntryType.OPENING_BALANCE, "Opening balance"),
            (MaintenanceFundEntry.EntryType.INFLOW, "Inflow"),
        ],
        widget=forms.Select(attrs={"class": "input"}),
    )
    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    evidence_original = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))
    evidence_redacted = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))


class SignFundSourceForm(SignedDecisionForm):
    """Signed submit of a prepared fund source. Hidden fields pin the exact
    signed payload (id, amount, evidence hashes, timestamp)."""

    entry_type = forms.CharField(max_length=32, widget=forms.HiddenInput())
    amount_vnd = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    evidence_original_id = forms.IntegerField(widget=forms.HiddenInput())
    evidence_redacted_id = forms.IntegerField(widget=forms.HiddenInput())
    fund_entry_id = forms.IntegerField(widget=forms.HiddenInput())
    entry_timestamp = forms.CharField(max_length=40, widget=forms.HiddenInput())
