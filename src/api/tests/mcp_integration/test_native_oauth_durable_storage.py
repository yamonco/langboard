"""The production provider factory uses encrypted FastMCP disk across processes."""

import json
import os
import subprocess
import sys
from pathlib import Path


WORKER = Path(__file__).with_name("fixtures") / "native_oauth_disk_worker.py"


def test_native_oauth_default_disk_survives_process_restart(tmp_path):
    environment = {**os.environ, "FASTMCP_HOME": str(tmp_path)}

    def run(mode):
        result = subprocess.run(
            [sys.executable, str(WORKER), mode], env=environment, capture_output=True, text=True, timeout=30
        )
        # Output contains booleans only; never echo child logs that may contain tokens.
        assert result.returncode == 0, f"OAuth disk fixture failed in {mode} (exit {result.returncode})"
        payload = json.loads(result.stdout.splitlines()[-1])
        assert payload["mode"] == mode
        return payload

    first = run("write")
    assert run("read") == {**first, "mode": "read"}
    files = [path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()]
    assert files
    for marker in [b"isolated-upstream-access-marker", b"isolated-upstream-refresh-marker", b"isolated-subject"]:
        assert all(marker not in data for data in files)
    wrong = run("wrong-key")
    assert all(value is False for key, value in wrong.items() if key != "mode")
    assert run("read") == {**first, "mode": "read"}
    missing = run("missing-mapping")
    assert missing["client_restored"] and missing["upstream_restored"] and missing["refresh_metadata_restored"]
    assert not missing["access_validated"]
