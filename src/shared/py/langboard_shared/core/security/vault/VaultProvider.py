from abc import ABC, abstractmethod


class VaultProvider(ABC):
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def create_key(self, key_id: str) -> str:
        pass

    def store_secret(self, secret_id: str, value: str) -> str:
        """Store supplied material and return an internal locator for get_key.

        Locators may be encrypted ciphertext on KMS providers. They are not
        public Secret URIs and must never be returned to models or MCP clients.
        Existing third-party providers fail explicitly until they support writes.
        """
        raise NotImplementedError("Selected vault provider cannot store supplied secrets")

    @abstractmethod
    def get_key(self, key_id: str) -> str:
        pass

    @abstractmethod
    def delete_key(self, key_id: str):
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass
