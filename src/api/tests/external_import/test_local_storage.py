from io import BytesIO
from pathlib import Path
from langboard_shared.core.storage import FileModel
from langboard_shared.core.storage.LocalStorage import LocalStorage
from langboard_shared.core.storage.S3Storage import S3Storage
from langboard_shared.core.storage.StorageName import StorageName
from langboard_shared.Env import Env


def test_named_upload_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(type(Env), "LOCAL_STORAGE_DIR", property(lambda _self: tmp_path))
    storage = LocalStorage()

    first = storage.upload_named(BytesIO(b"first"), "report.txt", StorageName.CardAttachment, "stable.txt")
    second = storage.upload_named(BytesIO(b"second"), "report.txt", StorageName.CardAttachment, "stable.txt")

    assert first is not None
    assert second is not None
    assert first.filename == second.filename == "stable.txt"
    assert (tmp_path / "card_attachment" / "stable.txt").read_bytes() == b"second"


def test_delete_uses_the_storage_namespace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(type(Env), "LOCAL_STORAGE_DIR", property(lambda _self: tmp_path))
    stored = tmp_path / "card_attachment" / "generated.txt"
    stored.parent.mkdir()
    stored.write_text("payload")
    file_model = FileModel(
        storage_type="local",
        storage_name="card_attachment",
        original_filename="report.txt",
        filename="generated.txt",
        path="/file/local/card_attachment/generated.txt",
    )

    assert LocalStorage().delete(file_model) is True
    assert not stored.exists()


def test_delete_returns_false_without_touching_other_namespaces(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(type(Env), "LOCAL_STORAGE_DIR", property(lambda _self: tmp_path))
    stored = tmp_path / "card_attachment" / "generated.txt"
    stored.parent.mkdir()
    stored.write_text("payload")
    file_model = FileModel(
        storage_type="s3",
        storage_name="card_attachment",
        original_filename="report.txt",
        filename="generated.txt",
        path="/file/s3/card_attachment/generated.txt",
    )

    assert LocalStorage().delete(file_model) is False
    assert stored.exists()


def test_s3_named_upload_uses_the_same_namespace_as_download(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeClient:
        def upload_fileobj(self, **kwargs) -> None:
            calls.append(kwargs)

        def close(self) -> None:
            pass

    storage = S3Storage()
    monkeypatch.setattr(storage, "_connect_client", FakeClient)
    monkeypatch.setattr(type(Env), "S3_BUCKET_NAME", property(lambda _self: "bucket"))

    uploaded = storage.upload_named(BytesIO(b"payload"), "report.txt", StorageName.CardAttachment, "stable.txt")

    assert uploaded is not None
    assert calls[0]["Bucket"] == "bucket"
    assert calls[0]["Key"] == "card_attachment/stable.txt"
