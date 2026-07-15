"""FCM sender + payload minimization (spec 7.1, 7.4). No abstraction layer:
firebase_admin.messaging is called directly."""

from django.conf import settings

from .services import (
    EVENT_CORRECTION_STATUS,
    EVENT_PUBLICATION,
    EVENT_REPORT_RECEIPT,
    EVENT_TRIAGE_STATUS,
    EVENT_WORK_COMPLETED,
    _event_code_from_key,
)

# Fixed generic Vietnamese copy shown by the OS before the app runs (spec 7.4);
# never the delivery's sensitive subject/body.
PUSH_COPY = {
    EVENT_REPORT_RECEIPT: ("Đã nhận phản ánh", "Phản ánh của bạn đã được ghi nhận."),
    EVENT_TRIAGE_STATUS: ("Phản ánh đã được phân loại", "Phản ánh của bạn đã được mở thành yêu cầu xử lý."),
    EVENT_WORK_COMPLETED: ("Công việc đã hoàn thành", "Vui lòng đánh giá công việc đã thực hiện."),
    EVENT_PUBLICATION: ("Khoản chi mới được công bố", "Có khoản chi mới trong sổ quỹ tòa nhà."),
    EVENT_CORRECTION_STATUS: ("Có điều chỉnh mới", "Một điều chỉnh đã được công bố trong sổ quỹ."),
}
_DEFAULT_COPY = ("Thông báo mới", "Bạn có một thông báo mới.")

# Allowlisted entity segment (from event_key) -> app deep-link route type.
DEEP_LINK_TYPES = {"report": "report", "case": "case", "entry": "ledger", "correction": "ledger"}

_firebase_app = None


def _ensure_app():
    global _firebase_app
    if _firebase_app is None:
        import firebase_admin
        from firebase_admin import credentials

        _firebase_app = firebase_admin.initialize_app(
            credentials.Certificate(settings.FIREBASE_CREDENTIALS)
        )
    return _firebase_app


def send_push(token, *, title, body, data, collapse_key=None) -> str:
    """Send one FCM message; returns the provider message id. Raises firebase
    messaging errors, classified by classify_push_error."""
    from firebase_admin import messaging

    _ensure_app()
    message = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in data.items()},
        android=messaging.AndroidConfig(collapse_key=collapse_key) if collapse_key else None,
        apns=(
            messaging.APNSConfig(headers={"apns-collapse-id": collapse_key})
            if collapse_key
            else None
        ),
    )
    return messaging.send(message)


def classify_push_error(exc) -> str:
    """Terminal (dead token -> deactivate device) vs transient (retry) (spec 7.3).

    Terminal covers all invalid/unregistered/mismatched-token cases exposed by
    pinned firebase-admin>=6,<8: UnregisteredError, SenderIdMismatchError, and
    InvalidArgumentError for bad registration tokens. Everything else is transient.
    """
    from firebase_admin import exceptions, messaging

    if isinstance(exc, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
        return "terminal"
    # InvalidArgumentError lives on firebase_admin.exceptions (not messaging) in >=6.
    if isinstance(exc, exceptions.InvalidArgumentError):
        msg = str(exc).lower()
        if any(
            needle in msg
            for needle in (
                "registration token",
                "not a valid fcm",
                "invalid registration",
                "requested entity was not found",
            )
        ):
            return "terminal"
    return "transient"


def _parse_reference(event_key: str):
    parts = event_key.split(":")
    if len(parts) >= 3:
        return parts[1], parts[2]
    return None, None


def build_push_payload(delivery):
    """Generic Vietnamese title/body + allowlisted deep link + delivery id (spec 7.4)."""
    code = delivery.event_code or _event_code_from_key(delivery.event_key)
    title, body = PUSH_COPY.get(code, _DEFAULT_COPY)
    entity, entity_id = _parse_reference(delivery.event_key)
    link_type = DEEP_LINK_TYPES.get(entity, "notifications")
    data = {"type": link_type, "id": entity_id or "", "delivery_id": str(delivery.pk)}
    return title, body, data
