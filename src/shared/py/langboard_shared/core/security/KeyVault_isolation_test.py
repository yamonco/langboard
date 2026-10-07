"""Verify optional provider boundaries in fresh interpreters without credentials."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path
import pytest


def run(code: str, tmp_path: Path, provider="openbao-local", environment="development", cli="false"):
    env = {
        **os.environ,
        "IS_CLI": cli,
        "KEY_PROVIDER_TYPE": provider,
        "ENVIRONMENT": environment,
        "PROJECT_NAME": "langboard",
    }
    root = Path(__file__).resolve().parents[6]
    env["PYTHONPATH"] = str(root / "src/shared/py") + os.pathsep + str(root / "src/api")
    bootstrap = f"""
from pathlib import Path
from langboard_shared.Env import Env
type(Env).DATA_DIR = property(lambda _: Path({str(tmp_path)!r}))
"""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(bootstrap) + textwrap.dedent(code)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


BLOCK_VENDORS = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'boto3', 'botocore', 'azure', 'hvac'}:
            raise ModuleNotFoundError('Optional SDK absent: ' + name)
sys.meta_path.insert(0, Block())
"""


@pytest.mark.parametrize("cli", ["true", "false"])
def test_local_keys_work_without_vendor_sdks(tmp_path, cli):
    run(
        BLOCK_VENDORS
        + """
from langboard_shared.core.security import KeyVault
assert KeyVault.is_fallback_provider and KeyVault.name() == 'openbao'
key = KeyVault.create_key('fixture')
assert KeyVault.get_key('fixture') == key
assert KeyVault.health_check()
locator = KeyVault.store_secret('imported', 'fixture:multiline\\ncredential')
assert KeyVault.get_key(locator) == 'fixture:multiline\\ncredential'
for invalid in ['', None]:
    try: KeyVault.store_secret('invalid', invalid)
    except ValueError: pass
    else: raise AssertionError('Invalid material accepted')
KeyVault.delete_key(locator)
KeyVault.delete_key('fixture')
try: KeyVault.get_key('fixture')
except KeyError: pass
else: raise AssertionError('Deleted key remains')
assert not any(name.split('.')[0] in {'boto3', 'azure', 'hvac'} for name in sys.modules)
""",
        tmp_path,
        cli=cli,
    )


@pytest.mark.parametrize("provider", ["openbao-local", "openbao", "hashicorp", "aws", "azure"])
def test_missing_selected_sdk_fails_in_production(tmp_path, provider):
    run(
        BLOCK_VENDORS
        + """
try: from langboard_shared.core.security import KeyVault
except ModuleNotFoundError as error: assert 'Optional SDK absent:' in str(error)
else: raise AssertionError('Production silently fell back')
assert not (Env.DATA_DIR / 'vault-data').exists()
""",
        tmp_path,
        provider=provider,
        environment="production",
    )


@pytest.mark.parametrize(
    "provider,class_name",
    [
        ("openbao", "OpenBaoVaultProvider"),
        ("hashicorp", "HashiCorpVaultProvider"),
        ("aws", "AwsKmsVaultProvider"),
        ("azure", "AzureVaultProvider"),
    ],
)
def test_selection_loads_only_requested_adapter_and_preserves_public_export(tmp_path, provider, class_name):
    run(
        f"""
import importlib.abc, sys, types
prefix = 'langboard_shared.core.security.vault.'
module = types.ModuleType(prefix + {class_name!r})
class Selected:
    def name(self): return {provider!r}
setattr(module, {class_name!r}, Selected)
sys.modules[module.__name__] = module
class BlockOther(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.startswith(prefix) and name.endswith('VaultProvider') and name.rsplit('.', 1)[1] not in {{'VaultProvider', 'LocalDevVaultProvider', {class_name!r}}}:
            raise AssertionError('Unselected adapter imported: ' + name)
sys.meta_path.insert(0, BlockOther())
from langboard_shared.core.security import KeyVault
assert not KeyVault.is_fallback_provider and KeyVault.name() == {provider!r}
from langboard_shared.core.security import vault
assert getattr(vault, {class_name!r}) is Selected
assert getattr(vault, {class_name!r}) is Selected
try: getattr(vault, 'UnknownProvider')
except AttributeError: pass
else: raise AssertionError('Unknown export accepted')
""",
        tmp_path,
        provider=provider,
        environment="production",
    )


def test_unknown_provider_fails_without_local_fallback(tmp_path):
    run(
        """
try: from langboard_shared.core.security import KeyVault
except ValueError as error: assert str(error) == 'Unsupported key provider type: unknown'
else: raise AssertionError('Unknown provider accepted')
""",
        tmp_path,
        provider="unknown",
    )
