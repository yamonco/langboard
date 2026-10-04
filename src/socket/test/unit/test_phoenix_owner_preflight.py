import os
import shutil
import subprocess
from pathlib import Path
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]


def _usable_bash() -> str | None:
    for directory in os.get_exec_path():
        candidate = Path(directory) / ("bash.exe" if os.name == "nt" else "bash")
        if (
            candidate.is_file()
            and subprocess.run([str(candidate), "-c", "true"], capture_output=True, timeout=5, check=False).returncode
            == 0
        ):
            return str(candidate)
    return None


@pytest.mark.parametrize("trace_endpoint", ["", "http://127.0.0.1:4318/v1/traces"])
@pytest.mark.parametrize("with_otel", ["false", "true"])
@pytest.mark.parametrize("shell", ["bash", "powershell"])
def test_trace_export_overlay_is_opt_in(tmp_path: Path, trace_endpoint: str, with_otel: str, shell: str) -> None:
    executable = _usable_bash() if shell == "bash" else shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} is unavailable")

    (tmp_path / ".env").write_text(
        f"PROJECT_NAME=fixture\nSOCKET_PHOENIX_OTEL_TRACES_ENDPOINT={trace_endpoint}\n", encoding="utf-8"
    )
    suffix = "sh" if shell == "bash" else "ps1"
    script = ROOT / "scripts" / "utils" / f"get-compose-args.{suffix}"
    command = (
        [executable, str(script)]
        if shell == "bash"
        else [executable, "-NoProfile", "-File", str(script), "-WithOtel", with_otel]
    )
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "WITH_OTEL": with_otel},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert ("docker-compose.phoenix-otel-traces.yaml" in result.stdout) is (
        bool(trace_endpoint) and with_otel == "true"
    )


def test_phoenix_is_the_only_socket_service() -> None:
    compose = yaml.safe_load((ROOT / "docker" / "docker-compose.server.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert "socket" not in services
    assert services["server"]["depends_on"]["socket-phoenix"]["condition"] == "service_healthy"
    nginx = (ROOT / "docker" / "server" / "conf.template").read_text(encoding="utf-8")
    assert nginx.count("proxy_pass http://socket_server;") == 2
    assert "SOCKET_JSON_CANARY" not in nginx


def test_production_preflight_requires_trace_endpoint(tmp_path: Path) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is unavailable")

    shutil.copyfile(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / ".env").write_text("PROJECT_NAME=fixture\n", encoding="utf-8")
    environment = {**os.environ, "WITH_OTEL": "true"}
    environment.pop("SOCKET_PHOENIX_OTEL_TRACES_ENDPOINT", None)
    result = subprocess.run(
        [make, "prepare_socket_phoenix_owner", "COMPOSE_ARGS="],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "SOCKET_PHOENIX_OTEL_TRACES_ENDPOINT must be an OTLP/HTTP traces URL" in result.stdout + result.stderr
