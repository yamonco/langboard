import base64
import secrets
import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError
from ....Env import Env
from .SecretEnvelope import PREFIX, open_secret, seal_secret
from .VaultProvider import VaultProvider


class AwsKmsVaultProvider(VaultProvider):
    def __init__(self):
        try:
            self.client = boto3.client(
                "kms",
                region_name=Env.KEY_PROVIDER_AWS_REGION,
                aws_access_key_id=Env.KEY_PROVIDER_AWS_ACCESS_KEY_ID,
                aws_secret_access_key=Env.KEY_PROVIDER_AWS_SECRET_ACCESS_KEY,
            )
            self.key_arn = Env.KEY_PROVIDER_AWS_KMS_KEY_ARN
        except (NoCredentialsError, PartialCredentialsError) as e:
            raise RuntimeError(
                f"AWS credentials not found or incomplete. "
                f"Please set KEY_PROVIDER_AWS_ACCESS_KEY_ID and KEY_PROVIDER_AWS_SECRET_ACCESS_KEY. "
                f"AWS error: {e}"
            ) from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to initialize AWS KMS client: {e}") from e

    def name(self) -> str:
        return "aws"

    def create_key(self, key_id: str) -> str:
        return self._encrypt_material(key_id, secrets.token_urlsafe(32))

    def store_secret(self, key_id: str, key_material: str) -> str:
        return seal_secret(key_material, lambda key: self._encrypt_material(key_id, key))

    def _encrypt_material(self, key_id: str, key_material: str) -> str:
        try:
            response = self.client.encrypt(KeyId=self.key_arn, Plaintext=f"{key_id}:{key_material}".encode())
            return base64.b64encode(response["CiphertextBlob"]).decode()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "AccessDeniedException":
                raise PermissionError(
                    f"Insufficient permissions to encrypt with AWS KMS key '{self.key_arn}'. "
                    f"Ensure the AWS credentials have kms:Encrypt permission. "
                    f"AWS error: {e}"
                ) from e
            elif error_code == "NotFoundException":
                raise RuntimeError(
                    f"KMS key '{self.key_arn}' not found. "
                    f"Please ensure the key ARN is correct and exists in the specified region."
                ) from e
            else:
                raise RuntimeError(f"Failed to encrypt API key with AWS KMS: {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to encrypt API key with AWS KMS: {e}") from e

    def get_key(self, key_id: str) -> str:
        if key_id.startswith(PREFIX):
            return open_secret(key_id, self.get_key)
        try:
            ciphertext = base64.b64decode(key_id)
            response = self.client.decrypt(CiphertextBlob=ciphertext)
            decrypted = response["Plaintext"].decode()
            # Extract the actual key material (format: "key_id:actual_key")
            return decrypted.split(":", 1)[1]
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid encrypted data format: {e}") from e
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "AccessDeniedException":
                raise PermissionError(
                    f"Insufficient permissions to decrypt with AWS KMS key '{self.key_arn}'. "
                    f"Ensure the AWS credentials have kms:Decrypt permission. "
                    f"AWS error: {e}"
                ) from e
            elif error_code == "InvalidCiphertextException":
                raise ValueError("Invalid ciphertext or ciphertext was encrypted with a different KMS key.") from e
            else:
                raise RuntimeError(f"Failed to decrypt API key with AWS KMS: {e}") from e
        except BotoCoreError as e:
            raise RuntimeError(f"Failed to decrypt API key with AWS KMS: {e}") from e

    def delete_key(self, key_id: str):
        pass

    def health_check(self) -> bool:
        try:
            self.client.describe_key(KeyId=self.key_arn)
            return True
        except (ClientError, BotoCoreError):
            return False
