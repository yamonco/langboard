"""Disabled optional OAuth must not import its provider or start discovery."""

import os
import subprocess
import sys
import textwrap


def test_disabled_transport_does_not_load_optional_oauth_module():
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""
            import importlib.abc, sys
            from langboard.mcp_integration.Server import McpServer
            from langboard_shared.Env import Env
            assert "langboard.mcp_integration.OAuth" not in sys.modules
            class RejectOAuth(importlib.abc.MetaPathFinder):
                def find_spec(self, name, path=None, target=None):
                    if name == "langboard.mcp_integration.OAuth":
                        raise AssertionError("Disabled OAuth provider was imported")
            sys.meta_path.insert(0, RejectOAuth())
            type(Env).MCP_OAUTH_ENABLED = property(lambda _: False)
            McpServer.oauth_discovery_routes = ["stale fixture discovery"]
            assert McpServer.get_oauth_http_app() is None
            assert McpServer.oauth_discovery_routes == []
            assert "langboard.mcp_integration.OAuth" not in sys.modules
        """)],
        env={**os.environ, "PROJECT_NAME": "langboard", "MCP_OAUTH_ENABLED": "false"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
