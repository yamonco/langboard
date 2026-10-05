"""Exercise the shipped environment generator and durable Compose mount."""

import os
import shutil
import subprocess
from pathlib import Path
import pytest
import yaml
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("configured", [False, True])
def test_standard_environment_generator_forwards_native_oauth(tmp_path, configured):
    scripts = tmp_path / "scripts" / "utils"
    scripts.mkdir(parents=True)
    for name in ("utils.sh", "update-docker-envs.sh"):
        shutil.copyfile(ROOT / "scripts" / "utils" / name, scripts / name)
    shutil.copytree(ROOT / "docker" / "envs", tmp_path / "docker" / "envs", ignore=shutil.ignore_patterns(".*"))
    values = {
        "MCP_OAUTH_ENABLED": "true",
        "MCP_OAUTH_BASE_URL": "https://board.example/api/mcp/oauth",
        "MCP_OAUTH_DISCOVERY_URL": "https://id.example/.well-known/openid-configuration",
        "MCP_OAUTH_CLIENT_ID": "fixture-client",
        "MCP_OAUTH_CLIENT_SECRET": "fixture secret with spaces",
        "MCP_OAUTH_SIGNING_KEY": "fixture-signing-key-at-least-32-characters",
        "MCP_OAUTH_SCOPES": "openid profile mcp:access",
        "MCP_OAUTH_PROMPT": "select_account",
        "MCP_EMPLOYEE_GROUP_IDS": "fixture-group-1,fixture-group-2",
    }
    (tmp_path / ".env").write_text(
        "PROJECT_NAME=langboard\n" + "".join(f'{name}="{value}"\n' for name, value in values.items() if configured)
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("MCP_", "OIDC_", "POSTGRES_EXTERNAL_"))
    }
    result = subprocess.run(
        ["bash", str(scripts / "update-docker-envs.sh")], env=environment, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    generated = dotenv_values(tmp_path / "docker" / "envs" / ".api.env")
    if configured:
        assert {name: generated[name] for name in values} == values
    else:
        assert generated["MCP_OAUTH_ENABLED"] == "false"
        assert generated["MCP_OAUTH_SCOPES"] == "openid profile mcp:access"
        assert generated["MCP_OAUTH_SIGNING_KEY"] == ""
        assert generated["MCP_EMPLOYEE_GROUP_IDS"] == ""


def test_standard_compose_persists_fastmcp_home_outside_container():
    compose = yaml.safe_load((ROOT / "docker" / "docker-compose.server.yaml").read_text())
    api = compose["services"]["api"]
    assert api["environment"]["FASTMCP_HOME"] == "/app/.fastmcp"
    assert "mcp-oauth-state:/app/.fastmcp" in api["volumes"]
    assert compose["volumes"]["mcp-oauth-state"] == {"driver": "local"}
