"""Supplied secrets retain existing provider locators and API-key semantics."""

import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from .HashiCorpVaultProvider import HashiCorpVaultProvider
from .LocalDevVaultProvider import LocalDevVaultProvider
from .OpenBaoVaultProvider import OpenBaoVaultProvider


SECRET = "-----BEGIN PRIVATE KEY-----\nfixture:한글\n-----END PRIVATE KEY-----"


def test_local_secret_roundtrip_rotation_delete_and_private_file(tmp_path):
    provider = LocalDevVaultProvider(tmp_path)
    locator = provider.store_secret("fixture", SECRET)
    assert locator == "fixture" and provider.get_key(locator) == SECRET
    assert os.stat(tmp_path / locator).st_mode & 0o777 == 0o600
    assert provider.store_secret(locator, "rotated") == locator
    assert provider.get_key(locator) == "rotated"
    generated = provider.create_key("generated")
    assert provider.get_key("generated") == generated and generated != SECRET
    provider.delete_key(locator)
    with pytest.raises(KeyError):
        provider.get_key(locator)


@pytest.mark.parametrize("identifier", ["../escape", "/absolute", "a/b", "", ".", "a" * 257])
def test_local_locator_rejects_path_escape(tmp_path, identifier):
    provider = LocalDevVaultProvider(tmp_path)
    with pytest.raises(ValueError):
        provider.store_secret(identifier, SECRET)
    assert not list(tmp_path.iterdir())


def test_local_replacement_does_not_follow_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("unchanged")
    (tmp_path / "fixture").symlink_to(outside)
    provider = LocalDevVaultProvider(tmp_path)
    provider.store_secret("fixture", SECRET)
    assert outside.read_text() == "unchanged"
    assert not (tmp_path / "fixture").is_symlink()
    assert provider.get_key("fixture") == SECRET


@pytest.mark.parametrize("provider_type", [OpenBaoVaultProvider, HashiCorpVaultProvider])
def test_kv_storage_roundtrip_uses_existing_payload_without_disk_copy(provider_type):
    provider = object.__new__(provider_type)
    values = {}

    def write(*, path, secret, mount_point):
        assert mount_point == "apikeys"
        values[path] = secret.copy()

    kv = SimpleNamespace(
        create_or_update_secret=Mock(side_effect=write),
        read_secret_version=lambda **args: {"data": {"data": values[args["path"]]}},
        delete_metadata_and_all_versions=lambda **args: values.pop(args["path"]),
    )
    provider.client = SimpleNamespace(secrets=SimpleNamespace(kv=SimpleNamespace(v2=kv)))
    if provider_type is OpenBaoVaultProvider:
        provider._save_key_to_file = Mock(side_effect=AssertionError("Imported credential copied to disk"))
    locator = provider.store_secret("opaque-id", SECRET)
    assert locator == "opaque-id"
    assert provider.get_key(locator) == SECRET
    provider.delete_key(locator)
    assert not values


@pytest.mark.parametrize("provider_type", [OpenBaoVaultProvider, HashiCorpVaultProvider])
def test_kv_storage_denial_remains_failure(provider_type):
    from hvac.exceptions import VaultError

    provider = object.__new__(provider_type)
    write = Mock(side_effect=VaultError("permission denied"))
    provider.client = SimpleNamespace(
        secrets=SimpleNamespace(kv=SimpleNamespace(v2=SimpleNamespace(create_or_update_secret=write)))
    )
    with pytest.raises(PermissionError):
        provider.store_secret("opaque-id", SECRET)


def test_kms_envelope_preserves_large_multiline_material_and_rejects_tampering():
    from .SecretEnvelope import PREFIX, open_secret, seal_secret

    wrapped = {}

    def wrap(key):
        assert len(key.encode()) < 100
        wrapped["fixture-ciphertext"] = key
        return "fixture-ciphertext"

    locator = seal_secret(SECRET * 500, wrap)
    assert SECRET not in locator
    assert open_secret(locator, wrapped.__getitem__) == SECRET * 500
    for broken in [PREFIX + "{}", locator[:-5], PREFIX + '{"key":"langboard-secret-v1:x","payload":"x"}']:
        with pytest.raises(ValueError, match="Invalid secret envelope"):
            open_secret(broken, wrapped.__getitem__)
    with pytest.raises(PermissionError):
        open_secret(locator, Mock(side_effect=PermissionError("revoked")))


@pytest.mark.parametrize("vendor", ["aws", "azure"])
def test_actual_kms_adapter_dispatch_preserves_legacy_and_envelope(vendor, monkeypatch):
    import importlib
    import sys
    from types import ModuleType

    def module(name, **members):
        stub = ModuleType(name)
        stub.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, stub)

    if vendor == "aws":
        module("boto3")
        module(
            "botocore.exceptions",
            **{
                name: type(name, (Exception,), {})
                for name in ["BotoCoreError", "ClientError", "NoCredentialsError", "PartialCredentialsError"]
            },
        )
        provider_type = importlib.import_module(".AwsKmsVaultProvider", __package__).AwsKmsVaultProvider
        provider = object.__new__(provider_type)
        provider.key_arn = "fixture"
        captured = {}

        def encrypt(**args):
            assert len(args["Plaintext"]) < 190
            captured["material"] = args["Plaintext"]
            return {"CiphertextBlob": b"fixture-encrypted-key"}

        provider.client = SimpleNamespace(encrypt=encrypt, decrypt=lambda **_: {"Plaintext": captured["material"]})
    else:
        module(
            "azure.core.exceptions",
            **{
                name: type(name, (Exception,), {})
                for name in ["AzureError", "ClientAuthenticationError", "ResourceNotFoundError"]
            },
        )
        module("azure.identity", ClientSecretCredential=object)
        module("azure.keyvault.keys", KeyClient=object)
        module(
            "azure.keyvault.keys.crypto",
            CryptographyClient=object,
            EncryptionAlgorithm=SimpleNamespace(rsa_oaep="rsa_oaep"),
        )
        provider_type = importlib.import_module(".AzureVaultProvider", __package__).AzureVaultProvider
        provider = object.__new__(provider_type)
        captured = {}

        def encrypt(algorithm, plaintext):
            assert algorithm == "rsa_oaep" and len(plaintext) < 190
            captured["material"] = plaintext
            return SimpleNamespace(ciphertext=b"fixture-encrypted-key")

        crypto = SimpleNamespace(encrypt=encrypt, decrypt=lambda *_: SimpleNamespace(plaintext=captured["material"]))
        provider._get_crypto_client = lambda _: crypto
    generated = provider.create_key("fixture")
    assert not generated.startswith("langboard-secret-v1:")
    assert provider.get_key(generated) == captured["material"].decode().split(":", 1)[1]
    locator = provider.store_secret("fixture", SECRET * 100)
    assert locator.startswith("langboard-secret-v1:") and SECRET not in locator
    assert provider.get_key(locator) == SECRET * 100
