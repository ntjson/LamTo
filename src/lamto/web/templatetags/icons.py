"""Inline SVG icons for the Management workspace and Evidence explorer.

One small, hand-drawn set on a 24px grid with a shared stroke, so every glyph
reads at the same weight beside text. Icons are always decorative
(``aria-hidden``): the text next to them carries the meaning, which keeps them
out of the accessible name and lets colour-independent labels do the work.

    {% load icons %}
    {% icon "inbox" %}
    {% icon "chevron-right" class="row-chevron" %}
"""

from __future__ import annotations

from django import template
from django.utils.html import format_html, mark_safe

register = template.Library()

# Path data only; the <svg> wrapper supplies stroke, caps, and joins.
ICONS: dict[str, str] = {
    "inbox": (
        '<path d="M3.5 13h4.3l1.5 2.5h5.4l1.5-2.5h4.3"/>'
        '<path d="M5.7 5.7A2 2 0 0 1 7.5 4.5h9a2 2 0 0 1 1.8 1.2L20.5 13v4.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V13z"/>'
    ),
    "wrench": (
        '<path d="M14.8 3.7a5 5 0 0 0-4.4 7L4.2 16.9a2 2 0 1 0 2.9 2.9l6.2-6.2a5 5 0 0 0 7-4.4l-2.9 2.9-2.8-.5-.5-2.8z"/>'
    ),
    "doc": (
        '<path d="M13.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8.5z"/>'
        '<path d="M13.5 3.5v5h5"/><path d="M9 13h6"/><path d="M9 16.5h4"/>'
    ),
    "banknote": (
        '<rect x="2.5" y="6.5" width="19" height="11" rx="2"/>'
        '<circle cx="12" cy="12" r="2.5"/><path d="M6 12h.01"/><path d="M18 12h.01"/>'
    ),
    "columns": (
        '<path d="M3.5 9 12 4.5 20.5 9"/><path d="M5.5 10v7"/><path d="M10 10v7"/>'
        '<path d="M14 10v7"/><path d="M18.5 10v7"/><path d="M3.5 19.5h17"/>'
    ),
    "door": (
        '<path d="M6.5 20.5V5A1.5 1.5 0 0 1 8 3.5h8A1.5 1.5 0 0 1 17.5 5v15.5"/>'
        '<path d="M4 20.5h16"/><path d="M14.5 12.5h.01"/>'
    ),
    "person-add": (
        '<circle cx="10" cy="8" r="3.5"/><path d="M3.5 20a6.5 6.5 0 0 1 13 0"/>'
        '<path d="M19 8.5v5"/><path d="M16.5 11h5"/>'
    ),
    "megaphone": (
        '<path d="M4 10.2v3.6a1 1 0 0 0 1 1h2.2L13 18.5v-13L7.2 9.2H5a1 1 0 0 0-1 1z"/>'
        '<path d="M16.5 9.3a3.8 3.8 0 0 1 0 5.4"/><path d="M18.8 7a7 7 0 0 1 0 10"/>'
    ),
    "receipt": (
        '<path d="M6 3.5h12v17l-2-1.4-2 1.4-2-1.4-2 1.4-2-1.4-2 1.4z"/>'
        '<path d="M9 8h6"/><path d="M9 11.5h6"/><path d="M9 15h3.5"/>'
    ),
    "pulse": '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>',
    "alert": (
        '<path d="M10.3 4.6 3.1 17.1A2 2 0 0 0 4.8 20h14.4a2 2 0 0 0 1.7-2.9L13.7 4.6a2 2 0 0 0-3.4 0z"/>'
        '<path d="M12 9.5v4"/><path d="M12 16.8h.01"/>'
    ),
    "chart": (
        '<path d="M4 20.5h16"/><path d="M6.5 17v-4"/><path d="M11 17V7.5"/>'
        '<path d="M15.5 17v-6.5"/><path d="M20 17V4.5"/>'
    ),
    "download": (
        '<path d="M12 4v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M4.5 19.5h15"/>'
    ),
    "chevron-left": '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
    "chevron-right": '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
    "chevron-down": '<path d="M5.5 9.5 12 16l6.5-6.5"/>',
    "chevrons-vertical": '<path d="M8 9.5 12 5.5l4 4"/><path d="M8 14.5l4 4 4-4"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.4-4.4"/>',
    "check": '<path d="M5 12.5 9.5 17 19 7.5"/>',
    "check-circle": '<circle cx="12" cy="12" r="8.5"/><path d="M8.3 12.3l2.5 2.5 5-5"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 7.8h.01"/>',
    "warning": (
        '<path d="M10.3 4.6 3.1 17.1A2 2 0 0 0 4.8 20h14.4a2 2 0 0 0 1.7-2.9L13.7 4.6a2 2 0 0 0-3.4 0z"/>'
        '<path d="M12 9.5v4"/><path d="M12 16.8h.01"/>'
    ),
    "error": '<circle cx="12" cy="12" r="8.5"/><path d="M9 9l6 6"/><path d="M15 9l-6 6"/>',
    "sidebar": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9.5 4.5v15"/>',
    "logout": (
        '<path d="M10 20H6.5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2H10"/>'
        '<path d="m15.5 16 4-4-4-4"/><path d="M19.5 12H9.5"/>'
    ),
    "external": (
        '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5 11 13"/>'
        '<path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>'
    ),
    "copy": (
        '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/>'
        '<path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>'
    ),
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "shield": (
        '<path d="M12 3.5 19 6v5.6c0 4.3-2.9 7.5-7 8.9-4.1-1.4-7-4.6-7-8.9V6z"/>'
        '<path d="m8.8 12 2.2 2.2 4.2-4.2"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "building": (
        '<path d="M5 20.5V5.5A1.5 1.5 0 0 1 6.5 4h7A1.5 1.5 0 0 1 15 5.5v15"/>'
        '<path d="M15 10h3.5a1.5 1.5 0 0 1 1.5 1.5v9"/>'
        '<path d="M8.5 8h3"/><path d="M8.5 11.5h3"/><path d="M8.5 15h3"/><path d="M3 20.5h18"/>'
    ),
    "photo": (
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/>'
        '<circle cx="9" cy="10" r="1.6"/><path d="m20.5 16-5-5-8.5 8.5"/>'
    ),
    "close": '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    "hourglass": (
        '<path d="M7 3.5h10"/><path d="M7 20.5h10"/>'
        '<path d="M8 3.5c0 4.5 8 5 8 8.5s-8 4-8 8.5"/><path d="M16 3.5c0 4.5-8 5-8 8.5s8 4 8 8.5"/>'
    ),
    "user": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    "link": (
        '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/>'
        '<path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'
    ),
    "calendar": (
        '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/>'
        '<path d="M3.5 10h17"/><path d="M8 3v4"/><path d="M16 3v4"/>'
    ),
    "sparkle": (
        '<path d="M12 3.5c.6 3.9 2.1 5.4 6 6-3.9.6-5.4 2.1-6 6-.6-3.9-2.1-5.4-6-6 3.9-.6 5.4-2.1 6-6z"/>'
        '<path d="M18.5 15.5c.3 1.7.8 2.2 2.5 2.5-1.7.3-2.2.8-2.5 2.5-.3-1.7-.8-2.2-2.5-2.5 1.7-.3 2.2-.8 2.5-2.5z"/>'
    ),
}


@register.simple_tag
def icon(name: str, **attrs) -> str:
    paths = ICONS.get(name)
    if paths is None:
        return ""
    css_class = attrs.get("class", "")
    classes = f"icon icon-{name} {css_class}".strip()
    return format_html(
        '<svg class="{}" viewBox="0 0 24 24" width="24" height="24" fill="none" '
        'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" focusable="false">{}</svg>',
        classes,
        mark_safe(paths),  # noqa: S308 - static, trusted markup from ICONS
    )
