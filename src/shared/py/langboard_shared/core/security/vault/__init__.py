"""Load optional provider SDKs only when their provider is explicitly requested."""

from importlib import import_module
from .LocalDevVaultProvider import LocalDevVaultProvider
from .VaultProvider import VaultProvider


__all__ = [
    "AwsKmsVaultProvider",
    "AzureVaultProvider",
    "HashiCorpVaultProvider",
    "LocalDevVaultProvider",
    "OpenBaoVaultProvider",
    "VaultProvider",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    provider = getattr(import_module(f".{name}", __name__), name)
    globals()[name] = provider
    return provider
