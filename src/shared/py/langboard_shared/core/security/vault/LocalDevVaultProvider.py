import os
import re
import secrets
import tempfile
from pathlib import Path
from .VaultProvider import VaultProvider


class LocalDevVaultProvider(VaultProvider):
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def name(self) -> str:
        return "local-dev"

    def create_key(self, key_id: str) -> str:
        key_material = secrets.token_urlsafe(32)
        self.store_secret(key_id, key_material)
        return key_material

    def store_secret(self, key_id: str, key_material: str) -> str:
        target = self._get_key_path(key_id)
        # Replace atomically; never truncate a symlink target or expose partial material.
        fd, temporary = tempfile.mkstemp(dir=self.base_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(key_material)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return key_id

    def get_key(self, key_id: str) -> str:
        key_path = self._get_key_path(key_id)
        if not key_path.exists():
            raise KeyError(f"API key '{key_id}' not found in local dev vault")
        return key_path.read_text(encoding="utf-8")

    def delete_key(self, key_id: str):
        key_path = self._get_key_path(key_id)
        if key_path.exists():
            key_path.unlink()

    def health_check(self) -> bool:
        return self.base_dir.exists() and self.base_dir.is_dir()

    def _get_key_path(self, key_id: str) -> Path:
        if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key_id):
            raise ValueError("Invalid local vault identifier")
        return self.base_dir / key_id
