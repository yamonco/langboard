import secrets
from hvac import Client
from hvac.exceptions import VaultError
from ....Env import Env
from .VaultProvider import VaultProvider


class OpenBaoVaultProvider(VaultProvider):
    def __init__(self):
        self.addr = Env.KEY_PROVIDER_OPENBAO_URL

        role_id, secret_id = self._load_vault_credentials()

        if not role_id or not secret_id:
            raise ValueError(
                "Vault credentials not found in .vault-credentials file. "
                "Please ensure VAULT_ROLE_ID and VAULT_SECRET_ID are set."
            )

        try:
            self.client = Client(url=self.addr)
            resp = self.client.auth.approle.login(role_id, secret_id)
            self.client.token = resp["auth"]["client_token"]
        except VaultError as e:
            raise RuntimeError(f"Failed to authenticate or connect to OpenBao: {e}")

    def name(self) -> str:
        return "openbao"

    def create_key(self, key_id: str) -> str:
        key_material = secrets.token_urlsafe(32)
        self.store_secret(key_id, key_material)
        # Preserve the legacy development API-key copy, not imported credentials.
        if Env.ENVIRONMENT != "production":
            self._save_key_to_file(key_id, key_material)
        return key_material

    def store_secret(self, key_id: str, key_material: str) -> str:
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=key_id, secret={"key_material": key_material}, mount_point="apikeys"
            )
        except VaultError as e:
            if "permission denied" in str(e).lower():
                raise PermissionError(
                    f"Insufficient permissions to create API key in OpenBao. "
                    f"Ensure the AppRole has write access to 'apikeys' KV v2 secrets engine. "
                    f"OpenBao error: {e}"
                ) from e
            elif "Invalid path" in str(e):
                raise RuntimeError(
                    f"KV v2 secrets engine 'apikeys' not found in OpenBao. "
                    f"Please enable it with: vault secrets enable -path=apikeys kv-v2. "
                    f"OpenBao error: {e}"
                ) from e
            else:
                raise RuntimeError(f"Failed to create API key in OpenBao: {e}") from e

        return key_id

    def get_key(self, key_id: str) -> str:
        try:
            secret = self.client.secrets.kv.v2.read_secret_version(path=key_id, mount_point="apikeys")
            return secret["data"]["data"]["key_material"]
        except VaultError as e:
            if "permission denied" in str(e).lower():
                raise PermissionError(
                    f"Insufficient permissions to read API key from OpenBao. "
                    f"Ensure the AppRole has read access to 'apikeys' KV v2 secrets engine. "
                    f"OpenBao error: {e}"
                ) from e
            elif "Invalid path" in str(e):
                raise KeyError(f"API key '{key_id}' not found in OpenBao") from e
            else:
                raise RuntimeError(f"Failed to read API key from OpenBao: {e}") from e

    def delete_key(self, key_id: str):
        try:
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(path=key_id, mount_point="apikeys")
        except VaultError as e:
            if "permission denied" in str(e).lower():
                raise PermissionError(
                    f"Insufficient permissions to delete API key from OpenBao. "
                    f"Ensure the AppRole has delete access to 'apikeys' KV v2 secrets engine. "
                    f"OpenBao error: {e}"
                ) from e
            elif "Invalid path" in str(e):
                pass
            else:
                raise RuntimeError(f"Failed to delete API key from OpenBao: {e}") from e

    def health_check(self) -> bool:
        try:
            return self.client.is_authenticated()
        except VaultError:
            return False

    def _load_vault_credentials(self) -> tuple[str | None, str | None]:
        vault_creds_path = Env.ROOT_DIR / ".vault-credentials"

        if not vault_creds_path.exists():
            return None, None

        role_id = None
        secret_id = None

        try:
            with open(vault_creds_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("VAULT_ROLE_ID="):
                        role_id = line.split("=", 1)[1].strip()
                    elif line.startswith("VAULT_SECRET_ID="):
                        secret_id = line.split("=", 1)[1].strip()
        except Exception:
            pass

        return role_id, secret_id

    def _save_key_to_file(self, key_id: str, key_material: str):
        """Save key material to a file in non-production environments."""
        vault_data_dir = Env.DATA_DIR / "vault-data"
        vault_data_dir.mkdir(parents=True, exist_ok=True)

        key_file_path = vault_data_dir / key_id
        try:
            with open(key_file_path, "w") as f:
                f.write(key_material)
        except Exception as e:
            # Log warning but don't fail the key creation
            import warnings

            warnings.warn(f"Failed to save key material to file {key_file_path}: {e}")
