import base64
import secrets
from azure.core.exceptions import AzureError, ClientAuthenticationError, ResourceNotFoundError
from azure.identity import ClientSecretCredential
from azure.keyvault.keys import KeyClient
from azure.keyvault.keys.crypto import CryptographyClient, EncryptionAlgorithm
from ....Env import Env
from .SecretEnvelope import PREFIX, open_secret, seal_secret
from .VaultProvider import VaultProvider


class AzureVaultProvider(VaultProvider):
    def __init__(self):
        try:
            self.credential = ClientSecretCredential(
                tenant_id=Env.KEY_PROVIDER_AZURE_TENANT_ID,
                client_id=Env.KEY_PROVIDER_AZURE_CLIENT_ID,
                client_secret=Env.KEY_PROVIDER_AZURE_CLIENT_SECRET,
            )
            self.key_client = KeyClient(vault_url=Env.KEY_PROVIDER_AZURE_KEYVAULT_URL, credential=self.credential)
        except ClientAuthenticationError as e:
            raise RuntimeError(
                f"Failed to authenticate with Azure Key Vault. "
                f"Please check your Azure credentials (CLIENT_ID, CLIENT_SECRET, TENANT_ID). "
                f"Azure error: {e}"
            ) from e
        except AzureError as e:
            raise RuntimeError(f"Failed to connect to Azure Key Vault: {e}") from e

    def name(self) -> str:
        return "azure"

    def create_key(self, key_id: str) -> str:
        return self._encrypt_material(key_id, secrets.token_urlsafe(32))

    def store_secret(self, key_id: str, key_material: str) -> str:
        return seal_secret(key_material, lambda key: self._encrypt_material(key_id, key))

    def _encrypt_material(self, key_id: str, key_material: str) -> str:
        try:
            crypto_client = self._get_crypto_client(Env.KEY_PROVIDER_AZURE_ENCRYPTION_KEY_NAME)
            result = crypto_client.encrypt(EncryptionAlgorithm.rsa_oaep, f"{key_id}:{key_material}".encode())
            return base64.b64encode(result.ciphertext).decode()
        except AzureError as e:
            raise RuntimeError(f"Failed to encrypt API key with Azure Key Vault: {e}") from e

    def get_key(self, key_id: str) -> str:
        if key_id.startswith(PREFIX):
            return open_secret(key_id, self.get_key)
        try:
            ciphertext = base64.b64decode(key_id)
            crypto_client = self._get_crypto_client(Env.KEY_PROVIDER_AZURE_ENCRYPTION_KEY_NAME)
            result = crypto_client.decrypt(EncryptionAlgorithm.rsa_oaep, ciphertext)
            decrypted = result.plaintext.decode()
            return decrypted.split(":", 1)[1]
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid encrypted data format: {e}") from e
        except AzureError as e:
            raise RuntimeError(f"Failed to decrypt API key with Azure Key Vault: {e}") from e

    def delete_key(self, key_id: str):
        pass

    def health_check(self) -> bool:
        try:
            self.key_client.list_properties_of_keys()
            return True
        except AzureError:
            return False

    def _get_crypto_client(self, key_name: str) -> CryptographyClient:
        try:
            key = self.key_client.get_key(key_name)
            return CryptographyClient(key, self.credential)
        except ResourceNotFoundError:
            raise RuntimeError(
                f"Encryption key '{key_name}' not found in Azure Key Vault. "
                f"Please ensure the key exists in the specified Key Vault."
            )
        except AzureError as e:
            raise RuntimeError(f"Failed to retrieve encryption key from Azure Key Vault: {e}") from e
