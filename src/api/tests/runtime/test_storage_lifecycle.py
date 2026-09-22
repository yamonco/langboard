from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from botocore.exceptions import ClientError
from langboard_shared.core.storage import StorageName
from langboard_shared.core.storage.FileModel import FileModel
from langboard_shared.core.storage.LocalStorage import LocalStorage
from langboard_shared.core.storage.S3Storage import S3Storage
from pytest import MonkeyPatch


def test_local_storage_deletes_uploaded_file_from_its_storage_directory(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(LocalStorage.upload.__globals__, "Env", SimpleNamespace(LOCAL_STORAGE_DIR=tmp_path))
    storage = LocalStorage()

    file_model = storage.upload(BytesIO(b"attachment"), "note.txt", StorageName.CardAttachment)

    assert file_model is not None
    stored_path = tmp_path / StorageName.CardAttachment.value / file_model.filename
    assert stored_path.read_bytes() == b"attachment"
    assert storage.delete(file_model)
    assert not stored_path.exists()


def test_s3_upload_uses_same_storage_prefix_as_download(monkeypatch: MonkeyPatch) -> None:
    storage = S3Storage()
    client = Mock()
    objects: dict[str, bytes] = {}
    client.upload_fileobj.side_effect = lambda Fileobj, Bucket, Key: objects.__setitem__(Key, Fileobj.read())
    client.download_fileobj.side_effect = lambda Bucket, Key, Fileobj: Fileobj.write(objects[Key])
    client.delete_object.side_effect = lambda Bucket, Key: objects.pop(Key, None)
    monkeypatch.setattr(storage, "_connect_client", lambda: client)

    file_model = storage.upload(BytesIO(b"attachment"), "note.txt", StorageName.CardAttachment)

    assert file_model is not None
    assert list(objects) == [f"{file_model.storage_name}/{file_model.filename}"]

    downloaded = BytesIO()
    assert storage.download(file_model.storage_name, file_model.filename, downloaded)
    assert downloaded.getvalue() == b"attachment"
    assert storage.delete(file_model)
    assert objects == {}
    assert client.close.call_count == 3


def test_s3_legacy_object_can_be_downloaded_and_deleted(monkeypatch: MonkeyPatch) -> None:
    storage = S3Storage()
    client = Mock()
    legacy_key = f"{StorageName.CardAttachment}/old.txt"
    objects = {legacy_key: b"legacy attachment"}

    def download_fileobj(*, Bucket: str, Key: str, Fileobj: BytesIO) -> None:
        if Key not in objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        Fileobj.write(objects[Key])

    client.download_fileobj.side_effect = download_fileobj
    client.delete_object.side_effect = lambda Bucket, Key: objects.pop(Key, None)
    monkeypatch.setattr(storage, "_connect_client", lambda: client)

    file_model = FileModel(
        storage_type="s3",
        storage_name=StorageName.CardAttachment.value,
        original_filename="old.txt",
        filename="old.txt",
        path="",
    )
    downloaded = BytesIO()

    assert storage.download(file_model.storage_name, file_model.filename, downloaded)
    assert downloaded.getvalue() == b"legacy attachment"
    assert storage.delete(file_model)
    assert objects == {}


def test_s3_download_does_not_retry_legacy_key_after_access_denied(monkeypatch: MonkeyPatch) -> None:
    storage = S3Storage()
    client = Mock()
    client.download_fileobj.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Access Denied"}}, "HeadObject"
    )
    monkeypatch.setattr(storage, "_connect_client", lambda: client)

    assert not storage.download(StorageName.CardAttachment.value, "note.txt", BytesIO())
    assert client.download_fileobj.call_count == 1
    assert client.download_fileobj.call_args.kwargs["Key"] == "card_attachment/note.txt"
