import uuid

from django.core.files.base import File
from django.core.files.storage import storages

PREFIX = "gate/pending-enrollment"


def _is_s3(storage):
    return hasattr(storage, "bucket_name") and hasattr(storage, "connection")


def store_pending_photo(file_obj, content_type):
    storage = storages["private"]
    key = f"{PREFIX}/{uuid.uuid4().hex}"
    file_obj.seek(0)
    if _is_s3(storage):
        response = storage.connection.meta.client.put_object(
            Bucket=storage.bucket_name, Key=key, Body=file_obj, ContentType=content_type
        )
        return key, response.get("VersionId") or ""
    return storage.save(key, File(file_obj, name=key)), ""


def delete_pending_photo(storage_key, provider_version_id=""):
    if not storage_key:
        return
    storage = storages["private"]
    if _is_s3(storage):
        kwargs = {"Bucket": storage.bucket_name, "Key": storage_key}
        if provider_version_id:
            kwargs["VersionId"] = provider_version_id
        storage.connection.meta.client.delete_object(**kwargs)
    else:
        storage.delete(storage_key)
