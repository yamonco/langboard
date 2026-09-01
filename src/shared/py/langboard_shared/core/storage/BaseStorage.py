from abc import ABC, abstractmethod
from os import urandom
from typing import IO, BinaryIO
from ..types import SafeDateTime
from ..utils.Encryptor import Encryptor
from ..utils.String import concat
from .FileModel import FileModel
from .StorageName import StorageName


class BaseStorage(ABC):
    storage_type = ""

    @staticmethod
    def decrypt_storage_type(storage_type: str) -> str:
        return Encryptor.decrypt(storage_type, "storage_type")

    @abstractmethod
    def get(self, storage_name: str, filename: str) -> bytes | None:
        """Get a file from the storage and return the bytes.

        :param file_model: The :class:`FileModel` object to get.
        """

    @abstractmethod
    def download(self, storage_name: str, filename: str, destination: IO[bytes]) -> bool:
        """Download a stored file into an open binary destination."""

    @abstractmethod
    def upload(self, file: BinaryIO, filename: str, storage_name: StorageName) -> FileModel | None:
        """Upload a file to the storage and return the FileModel object.

        :param file: The :class:`BinaryIO` object to upload.
        """

    @abstractmethod
    def delete(self, file_model: FileModel) -> bool:
        """Delete a file from the storage.

        :param file_model: The :class:`FileModel` object to delete.
        """

    @abstractmethod
    def is_connectable(self) -> bool:
        """Check if the storage is connectable."""

    def _encrypt_storage_type(self, storage_type: str) -> str:
        return Encryptor.encrypt(storage_type, "storage_type")

    def get_random_filename(self, file_name: str | None) -> str:
        extension = file_name.split(".")[-1] if file_name else ""

        return concat(str(int(SafeDateTime.now().timestamp())), urandom(10).hex(), ".", extension)
