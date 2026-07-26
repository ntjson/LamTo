"""Staff template filters and tags."""

from __future__ import annotations

from django import template
from django.utils import formats, timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy

register = template.Library()

URGENCY_LABELS = {"LOW": _lazy("Low"), "MEDIUM": _lazy("Medium"), "HIGH": _lazy("High")}


@register.filter
def staff_urgency(value):
    """Translated label for a stored urgency code; unknown codes pass through."""
    return URGENCY_LABELS.get(str(value or "").upper(), value)


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
