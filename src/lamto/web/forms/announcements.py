from django import forms


class AnnouncementForm(forms.Form):
    title = forms.CharField(max_length=160, strip=True)
    body = forms.CharField(max_length=2000, strip=True, widget=forms.Textarea)
    expected_revision = forms.IntegerField(required=False, widget=forms.HiddenInput)
