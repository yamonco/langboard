from os import path, unlink
from pathlib import Path
from shutil import copyfileobj
from typing import IO, BinaryIO
from ...Env import Env
from .BaseStorage import BaseStorage
from .FileModel import FileModel
from .StorageName import StorageName


class LocalStorage(BaseStorage):
    storage_type = "local"

    def get(self, storage_name: str, filename: str) -> bytes | None:
        file_path = Env.LOCAL_STORAGE_DIR / storage_name / filename
        if not path.exists(file_path):
            return None

        with open(file_path, "rb") as f:
            return f.read()

    def download(self, storage_name: str, filename: str, destination: IO[bytes]) -> bool:
        file_path = Env.LOCAL_STORAGE_DIR / storage_name / filename
        if not path.exists(file_path):
            return False

        try:
            with open(file_path, "rb") as source:
                copyfileobj(source, destination)
            return True
        except OSError:
            return False

    def upload(self, file: BinaryIO, filename: str, storage_name: StorageName) -> FileModel | None:
        if not filename:
            return None

        storage_path = Env.LOCAL_STORAGE_DIR / storage_name.value
        storage_path.mkdir(parents=True, exist_ok=True)

        new_filename = self.get_random_filename(filename)
        with open(storage_path / new_filename, "wb") as f:
            copyfileobj(file, f)

        return FileModel(
            storage_type=LocalStorage.storage_type,
            storage_name=storage_name.value,
            original_filename=Path(filename).name,
            filename=new_filename,
            path=f"/file/{self._encrypt_storage_type(LocalStorage.storage_type)}/{storage_name.value}/{new_filename}",
        )

    def delete(self, file_model: FileModel) -> bool:
        if file_model.storage_type != LocalStorage.storage_type:
            return False

        try:
            unlink(Env.LOCAL_STORAGE_DIR / file_model.filename)
            return True
        except Exception:
            return False

    def is_connectable(self) -> bool:
        return True
