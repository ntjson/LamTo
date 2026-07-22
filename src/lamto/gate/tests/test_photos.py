from unittest.mock import Mock, patch

import pytest

from lamto.gate.photos import PhotoVersionMissing, delete_pending_photo, store_pending_photo


def _s3(response=None):
    storage = Mock(bucket_name="private")
    storage.connection.meta.client.put_object.return_value = response or {}
    return storage


def test_s3_put_requires_a_version_id():
    with patch("lamto.gate.photos.storages", {"private": _s3()}):
        with pytest.raises(PhotoVersionMissing):
            store_pending_photo(__import__("io").BytesIO(b"photo"), "image/jpeg")


def test_s3_delete_never_falls_back_to_unversioned_delete():
    storage = _s3()
    with patch("lamto.gate.photos.storages", {"private": storage}):
        with pytest.raises(PhotoVersionMissing):
            delete_pending_photo("photo-key", "")
    storage.connection.meta.client.delete_object.assert_not_called()
