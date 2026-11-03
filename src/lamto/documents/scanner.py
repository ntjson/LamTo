import socket
import struct

from django.conf import settings

# The scan runs inside the upload request, so the server's request timeout has
# to stay comfortably above this (ops/gunicorn.conf.py).
SCAN_TIMEOUT_SECONDS = 10


class DocumentScanUnavailable(RuntimeError):
    pass


def scan_with_clamav(file_obj) -> bool:
    try:
        file_obj.seek(0)
        with socket.create_connection(
            (settings.CLAMAV_HOST, int(settings.CLAMAV_PORT)),
            timeout=SCAN_TIMEOUT_SECONDS,
        ) as connection:
            connection.sendall(b"zINSTREAM\0")
            while chunk := file_obj.read(8192):
                connection.sendall(struct.pack("!I", len(chunk)) + chunk)
            connection.sendall(struct.pack("!I", 0))
            response = connection.recv(4096)
    except (OSError, ValueError) as error:
        raise DocumentScanUnavailable("ClamAV is unavailable.") from error
    finally:
        file_obj.seek(0)
    if not response or not response.endswith(b"\0"):
        raise DocumentScanUnavailable("ClamAV returned an invalid response.")
    response = response.rstrip(b"\0")
    if response.endswith(b": OK"):
        return True
    if response.endswith(b": FOUND"):
        return False
    raise DocumentScanUnavailable("ClamAV returned an invalid response.")
