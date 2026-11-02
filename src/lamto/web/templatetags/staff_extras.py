"""Staff template filters and tags."""

from __future__ import annotations

from django import template
from django.utils import formats, timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.utils.translation import pgettext_lazy

register = template.Library()

URGENCY_LABELS = {"LOW": _lazy("Low"), "MEDIUM": _lazy("Medium"), "HIGH": _lazy("High")}

# Stored QuarantinedUpload.reason codes stay stable English; screens translate.
UPLOAD_REASON_LABELS = {
    "unsupported content type": _lazy("the file type is not supported"),
    "upload exceeds size limit": _lazy("the file exceeds the size limit"),
    "file signature does not match content type": _lazy("the file content does not match its declared type"),
    "image verification failed": _lazy("the image could not be verified"),
    "scanner unavailable": _lazy("the virus scanner was unavailable"),
    "malware detected": _lazy("the scan detected malware"),
}


def upload_reason_label(value):
    """Translated label for a stored upload-rejection reason; unknown text passes through."""
    return UPLOAD_REASON_LABELS.get(str(value or "").strip(), value)


@register.filter
def staff_upload_reason(value):
    return upload_reason_label(value)


@register.filter
def staff_urgency(value):
    """Translated label for a stored urgency code; unknown codes pass through."""
    return URGENCY_LABELS.get(str(value or "").upper(), value)


@register.filter
def staff_category(value):
    """Translated label for a stored case category code; unknown codes pass through."""
    from lamto.maintenance.models import CaseCategory

    try:
        return CaseCategory(str(value)).label
    except ValueError:
        return value


@register.filter
def describe_errors(bound_field):
    """Widget with aria-describedby/aria-invalid wired to its error block.

    Help text stays described too, so the error does not replace the hint.
    """
    if not getattr(bound_field, "errors", None):
        return bound_field
    described_by = [f"{bound_field.auto_id}-error"]
    if bound_field.help_text:
        described_by.insert(0, f"{bound_field.auto_id}_helptext")
    return bound_field.as_widget(attrs={
        "aria-describedby": " ".join(described_by),
        "aria-invalid": "true",
    })


@register.filter(expects_localtime=True)
def staff_datetime(value):
    """One shared staff datetime format (locale-aware SHORT_DATETIME_FORMAT)."""
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(value)
        if parsed is None:
            return value
        value = parsed
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return formats.date_format(value, "SHORT_DATETIME_FORMAT")


@register.simple_tag
def staff_entry_count(count):
    """Translatable entry/entries label (replaces entr|y,ies pluralize)."""
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = 0
    return _("%(count)d entry") % {"count": n} if n == 1 else _("%(count)d entries") % {"count": n}


@register.simple_tag
def staff_result_count(count):
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = 0
    return _("%(count)d result") % {"count": n} if n == 1 else _("%(count)d results") % {"count": n}


@register.simple_tag
def staff_task_count(count):
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = 0
    return _("%(count)d open task") % {"count": n} if n == 1 else _("%(count)d open tasks") % {"count": n}


# Short money for tight cells (the fund calendar): 82 K, 1,5 M, 1 B. The
# suffixes translate (vi: N, Tr, Tỷ); full amounts stay in titles and tables.
COMPACT_VND_STEPS = (
    (1_000_000_000, pgettext_lazy("compact money", "B")),
    (1_000_000, pgettext_lazy("compact money", "M")),
    (1_000, pgettext_lazy("compact money", "K")),
)


@register.filter
def vnd_compact(value):
    try:
        amount = abs(int(value))
    except (TypeError, ValueError):
        return value
    for step, suffix in COMPACT_VND_STEPS:
        if amount >= step:
            rounded = round(amount / step, 1)
            short = formats.number_format(int(rounded) if rounded.is_integer() else rounded)
            return f"{short} {suffix}"
    return formats.number_format(amount)


@register.filter
def vnd_abs(value):
    try:
        return abs(int(value))
    except (TypeError, ValueError):
        return value


@register.filter
def staff_duration(seconds):
    """A wait in words a manager reads at a glance: 45 s, 12 min, 3 h 42 min, 2 days 4 h."""
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return seconds
    days, rest = divmod(total, 86_400)
    hours, rest = divmod(rest, 3_600)
    minutes, secs = divmod(rest, 60)
    if days:
        return _("%(days)d d %(hours)d h") % {"days": days, "hours": hours}
    if hours:
        return _("%(hours)d h %(minutes)d min") % {"hours": hours, "minutes": minutes}
    if minutes:
        return _("%(minutes)d min") % {"minutes": minutes}
    return _("%(seconds)d s") % {"seconds": secs}


@register.filter
def phone_display(value):
    """+84912345678 -> 0912 345 678; anything else passes through."""
    text = str(value or "")
    if text.startswith("+84") and text[3:].isdigit() and len(text) == 12:
        local = "0" + text[3:]
        return f"{local[:4]} {local[4:7]} {local[7:]}"
    return text
