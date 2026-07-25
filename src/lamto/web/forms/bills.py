from django import forms
from django.utils.translation import gettext_lazy as _


class BillForm(forms.Form):
    resident = forms.ChoiceField()
    title = forms.CharField(max_length=160, strip=True)
    amount_vnd = forms.IntegerField(min_value=1)
    period = forms.CharField(max_length=64, required=False, strip=True)
    due_date = forms.DateField(required=False)
    note = forms.CharField(
        max_length=500, required=False, strip=True, widget=forms.Textarea
    )
    document = forms.FileField()

    def __init__(self, *args, resident_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["resident"].choices = list(resident_choices)


class VoidBillForm(forms.Form):
    reason = forms.CharField(max_length=500, label=_("Reason"))
    confirm = forms.BooleanField(
        required=True,
        label=_("I understand voiding this bill cannot be undone."),
    )
