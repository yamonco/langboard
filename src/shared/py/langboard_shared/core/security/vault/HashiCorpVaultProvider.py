import secrets
from hvac import Client
from hvac.exceptions import VaultError
from ....Env import Env
from .VaultProvider import VaultProvider


class HashiCorpVaultProvider(VaultProvider):
    def __init__(self):
        self.addr = Env.KEY_PROVIDER_HASHICORP_URL

        # For external HashiCorp Vault, use environment variables directly
        role_id = Env.KEY_PROVIDER_HASHICORP_ROLE_ID
        secret_id = Env.KEY_PROVIDER_HASHICORP_SECRET_ID

        if not role_id or not secret_id:
            raise ValueError(
                "HashiCorp Vault credentials not found. "
                "Please ensure KEY_PROVIDER_HASHICORP_ROLE_ID and "
                "KEY_PROVIDER_HASHICORP_SECRET_ID are set in .env file."
            )

        try:
            self.client = Client(url=self.addr)
            resp = self.client.auth.approle.login(role_id, secret_id)
            self.client.token = resp["auth"]["client_token"]
        except VaultError as e:
            raise RuntimeError(f"Failed to authenticate or connect to Vault: {e}")

    def name(self) -> str:
        return "hashicorp"

    def create_key(self, key_id: str) -> str:
        key_material = secrets.token_urlsafe(32)
        self.store_secret(key_id, key_material)
        return key_material

    def store_secret(self, key_id: str, key_material: str) -> str:
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=key_id, secret={"key_material": key_material}, mount_point="apikeys"
            )
        except VaultError as e:
            if "permission denied" in str(e).lower():
                raise PermissionError(
                    f"Insufficient permissions to create API key in Vault. "
                    f"Ensure the AppRole has write access to 'apikeys' KV v2 secrets engine. "
                    f"Vault error: {e}"
                ) from e
            elif "Invalid path" in str(e):
                raise RuntimeError(
                    f"KV v2 secrets engine 'apikeys' not found in Vault. "
                    f"Please enable it with: vault secrets enable -path=apikeys kv-v2. "
                    f"Vault error: {e}"
                ) from e
            else:
                raise RuntimeError(f"Failed to create API key in Vault: {e}") from e
        return key_id

    def get_key(self, key_id: str) -> str:
        try:
            secret = self.client.secrets.kv.v2.read_secret_version(path=key_id, mount_point="apikeys")
            return secret["data"]["data"]["key_material"]
        except VaultError as e:
            if "permission denied" in str(e).lower():
                raise PermissionError(
                    f"Insufficient permissions to read API key from Vault. "
                    f"Ensure the AppRole has read access to 'apikeys' KV v2 secrets engine. "
                    f"Vault error: {e}"
                ) from e
            elif "Invalid path" in str(e):
                raise KeyError(f"API key '{key_id}' not found in Vault") from e
            else:
                raise RuntimeError(f"Failed to read API key from Vault: {e}") from e

    def delete_key(self, key_id: str):
        try:
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(path=key_id, mount_point="apikeys")
        except VaultError as e:
            if "permission denied" in str(e).lower():
                raise PermissionError(
                    f"Insufficient permissions to delete API key from Vault. "
                    f"Ensure the AppRole has delete access to 'apikeys' KV v2 secrets engine. "
                    f"Vault error: {e}"
                ) from e
            elif "Invalid path" in str(e):
                pass
            else:
                raise RuntimeError(f"Failed to delete API key from Vault: {e}") from e

    def health_check(self) -> bool:
        try:
            return self.client.is_authenticated()
        except VaultError:
            return False
