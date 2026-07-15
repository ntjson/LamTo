"""Staff workspace forms — mutations go through domain services only."""

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError

from lamto.accounts.models import OrganizationMembership
from lamto.finance.acceptance import accept_work
from lamto.finance.approvals import decide_proposal
from lamto.finance.emergencies import authorize_emergency, decide_emergency
from lamto.finance.models import ApprovalDecision, PaymentVerification
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
        choices=[("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High"), ("CRITICAL", "Critical")],
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

    def save(self, work_order, maintenance_user, before_versions, after_versions):
        return complete_work_order(
            work_order,
            maintenance_user,
            self.cleaned_data["cause"],
            self.cleaned_data["result"],
            before_versions,
            after_versions,
        )


class SignedDecisionForm(forms.Form):
    """Common fields for wallet-signed domain actions."""

    event_id = forms.CharField(
        max_length=66,
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "off"}),
    )
    signature = forms.CharField(
        max_length=132,
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "off"}),
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 2}),
    )


class ProposalDecisionForm(SignedDecisionForm):
    decision = forms.ChoiceField(
        choices=[
            (ApprovalDecision.Decision.APPROVE, "Approve"),
            (ApprovalDecision.Decision.REJECT, "Reject"),
        ],
        widget=forms.Select(attrs={"class": "input"}),
    )

    def save(self, version, membership):
        return decide_proposal(
            version,
            membership,
            self.cleaned_data["decision"],
            self.cleaned_data.get("reason") or "",
            self.cleaned_data["signature"],
            self.cleaned_data["event_id"],
        )


class AcceptWorkForm(SignedDecisionForm):
    actual_cost_vnd = forms.IntegerField(
        min_value=1, widget=forms.NumberInput(attrs={"class": "input"})
    )
    invoice_original_id = forms.IntegerField(widget=forms.NumberInput(attrs={"class": "input"}))
    invoice_redacted_id = forms.IntegerField(widget=forms.NumberInput(attrs={"class": "input"}))
    acceptance_original_id = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": "input"})
    )
    acceptance_redacted_id = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": "input"})
    )

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
    proof_original_id = forms.IntegerField(widget=forms.NumberInput(attrs={"class": "input"}))
    proof_redacted_id = forms.IntegerField(widget=forms.NumberInput(attrs={"class": "input"}))
    payment_id = forms.IntegerField(
        required=False, widget=forms.NumberInput(attrs={"class": "input"})
    )

    def save(self, acceptance, membership, proof_original, proof_redacted, completed_at=None):
        from django.utils import timezone
        from lamto.finance.payments import allocate_payment_id

        payment_id = self.cleaned_data.get("payment_id") or allocate_payment_id()
        return record_payment(
            acceptance,
            membership,
            self.cleaned_data["bank_reference"],
            self.cleaned_data["amount_vnd"],
            self.cleaned_data["external_status"],
            completed_at or timezone.now(),
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


class EmergencyAuthorizeForm(SignedDecisionForm):
    estimate_vnd = forms.IntegerField(
        required=False, min_value=1, widget=forms.NumberInput(attrs={"class": "input"})
    )

    def save(self, work_order, membership):
        from django.utils import timezone

        return authorize_emergency(
            work_order,
            membership,
            self.cleaned_data.get("estimate_vnd"),
            self.cleaned_data["signature"],
            self.cleaned_data["event_id"],
            timezone.now(),
        )


class EmergencyDecideForm(SignedDecisionForm):
    decision = forms.ChoiceField(
        choices=[("RATIFY", "Ratify"), ("REJECT", "Reject")],
        widget=forms.Select(attrs={"class": "input"}),
    )

    def save(self, authorization, membership):
        return decide_emergency(
            authorization,
            membership,
            self.cleaned_data["decision"],
            self.cleaned_data.get("reason") or "",
            self.cleaned_data["signature"],
            self.cleaned_data["event_id"],
        )


class NotificationPreferenceForm(forms.Form):
    """Email opt-in flags per material event; in-app remains required."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        prefs = {
            p.event_code: p.email_enabled
            for p in NotificationPreference.objects.filter(user=user)
        }
        for code, label in PREFERENCE_EVENT_CHOICES:
            self.fields[f"email_{code}"] = forms.BooleanField(
                label=f"Email: {label}",
                required=False,
                initial=prefs.get(code, True),
            )

    def save(self):
        if self.user is None:
            raise ValidationError("User is required.")
        for code, _label in PREFERENCE_EVENT_CHOICES:
            field = f"email_{code}"
            enabled = bool(self.cleaned_data.get(field))
            NotificationPreference.objects.update_or_create(
                user=self.user,
                event_code=code,
                defaults={"email_enabled": enabled},
            )


class PreparePublicationForm(SignedDecisionForm):
    """Board ledger publication (signed)."""

    publication_id = forms.IntegerField(
        required=False, min_value=1, widget=forms.NumberInput(attrs={"class": "input"})
    )

    def save(self, proposal, membership):
        from lamto.finance.publication import prepare_publication

        return prepare_publication(
            proposal,
            membership,
            self.cleaned_data["signature"],
            self.cleaned_data["event_id"],
            publication_id=self.cleaned_data.get("publication_id") or None,
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

