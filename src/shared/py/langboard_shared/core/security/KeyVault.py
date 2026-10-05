from ...Env import Env
from ..utils.decorators.ClassInstance import class_instance
from .vault.LocalDevVaultProvider import LocalDevVaultProvider
from .vault.VaultProvider import VaultProvider


@class_instance()
class KeyVault(VaultProvider):
    def __init__(self):
        self.provider_type = Env.KEY_PROVIDER_TYPE
        self.is_fallback_provider = False

        if Env.IS_CLI:
            self.provider = LocalDevVaultProvider(Env.DATA_DIR / "vault-data")
            self.is_fallback_provider = True
            return

        try:
            if self.provider_type.startswith("openbao"):
                from .vault.OpenBaoVaultProvider import OpenBaoVaultProvider

                self.provider = OpenBaoVaultProvider()
            elif self.provider_type == "hashicorp":
                from .vault.HashiCorpVaultProvider import HashiCorpVaultProvider

                self.provider = HashiCorpVaultProvider()
            elif self.provider_type == "aws":
                from .vault.AwsKmsVaultProvider import AwsKmsVaultProvider

                self.provider = AwsKmsVaultProvider()
            elif self.provider_type == "azure":
                from .vault.AzureVaultProvider import AzureVaultProvider

                self.provider = AzureVaultProvider()
            else:
                raise ValueError(f"Unsupported key provider type: {self.provider_type}")
        except Exception:
            if Env.ENVIRONMENT == "development" and self.provider_type == "openbao-local":
                self.provider = LocalDevVaultProvider(Env.DATA_DIR / "vault-data")
                self.is_fallback_provider = True
                return
            raise

    def _normalized_name(self) -> str:
        if self.provider_type.startswith("openbao"):
            return "openbao"
        return self.provider_type

    def name(self) -> str:
        if not self.is_fallback_provider:
            return self.provider.name()
        return self._normalized_name()

    def create_key(self, key_id: str) -> str:
        return self.provider.create_key(key_id)

    def get_key(self, key_id: str) -> str:
        return self.provider.get_key(key_id)

    def delete_key(self, key_id: str):
        return self.provider.delete_key(key_id)

    def health_check(self) -> bool:
        return self.provider.health_check()
