from io import BytesIO
from typing import IO, BinaryIO
from boto3 import client
from ...Env import Env
from .BaseStorage import BaseStorage
from .FileModel import FileModel
from .StorageName import StorageName


class S3Storage(BaseStorage):
    storage_type = "s3"

    def get(self, storage_name: str, filename: str) -> bytes | None:
        destination = BytesIO()
        if not self.download(storage_name, filename, destination):
            return None
        return destination.getvalue()

    def download(self, storage_name: str, filename: str, destination: IO[bytes]) -> bool:
        s3_client = None
        try:
            s3_client = self._connect_client()
            s3_client.download_fileobj(Bucket=Env.S3_BUCKET_NAME, Key=f"{storage_name}/{filename}", Fileobj=destination)
            return True
        except Exception:
            return False
        finally:
            if s3_client:
                s3_client.close()

    def upload(self, file: BinaryIO, filename: str, storage_name: StorageName) -> FileModel | None:
        if not filename:
            return None

        s3_client = None
        try:
            s3_client = self._connect_client()
            new_filename = self.get_random_filename(filename)
            s3_client.upload_fileobj(Fileobj=file, Bucket=Env.S3_BUCKET_NAME, Key=f"{storage_name}/{new_filename}")

            return FileModel(
                storage_type=S3Storage.storage_type,
                storage_name=storage_name.value,
                original_filename=filename,
                filename=new_filename,
                path=f"/file/{self._encrypt_storage_type(S3Storage.storage_type)}/{storage_name.value}/{new_filename}",
            )
        except Exception:
            return None
        finally:
            if s3_client:
                s3_client.close()

    def delete(self, file_model: FileModel) -> bool:
        if file_model.storage_type != S3Storage.storage_type:
            return False

        s3_client = None
        try:
            s3_client = self._connect_client()
            s3_client.delete_object(Bucket=Env.S3_BUCKET_NAME, Key=f"{file_model.storage_name}/{file_model.filename}")
            return True
        except Exception:
            return False
        finally:
            if s3_client:
                s3_client.close()

    def is_connectable(self) -> bool:
        if not Env.S3_ACCESS_KEY_ID or not Env.S3_SECRET_ACCESS_KEY:
            return False

        s3_client = None
        try:
            s3_client = self._connect_client()
            return True
        except Exception:
            return False
        finally:
            if s3_client:
                s3_client.close()

    def _connect_client(self):
        return client(
            "s3",
            region_name=Env.S3_REGION_NAME,
            aws_access_key_id=Env.S3_ACCESS_KEY_ID,
            aws_secret_access_key=Env.S3_SECRET_ACCESS_KEY,
        )
