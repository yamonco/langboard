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


def test_production_preflight_does_not_require_otel_before_release(tmp_path: Path) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is unavailable")

    shutil.copyfile(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / ".env").write_text("PROJECT_NAME=fixture\n", encoding="utf-8")
    environment = {**os.environ, "WITH_OTEL": "false", "SOCKET_PHOENIX_INTERNAL_SECRET": ""}
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
    assert "SOCKET_PHOENIX_INTERNAL_SECRET must contain at least 32 characters" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "flag",
    [
        "SOCKET_PHOENIX_BOARD_CHAT_SEND_ENABLED",
        "SOCKET_PHOENIX_BOARD_CHAT_RESUME_ENABLED",
        "SOCKET_PHOENIX_BOARD_CHAT_RECOVERY_ENABLED",
        "SOCKET_PHOENIX_EDITOR_AI_ENABLED",
        "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED",
    ],
)
def test_owner_preflight_rejects_disabled_features(tmp_path: Path, flag: str) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is unavailable")

    shutil.copyfile(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / ".env").write_text("PROJECT_NAME=fixture\n", encoding="utf-8")
    result = subprocess.run(
        [make, "prepare_socket_phoenix_owner", "COMPOSE_ARGS="],
        cwd=tmp_path,
        env={**os.environ, flag: "false"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert f"{flag} must be true for complete Phoenix ownership" in result.stdout + result.stderr


def test_owner_preflight_rejects_disabled_feature_from_env_file(tmp_path: Path) -> None:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is unavailable")

    flag = "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED"
    shutil.copyfile(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / ".env").write_text(f"PROJECT_NAME=fixture\n{flag}=false\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop(flag, None)
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
    assert f"{flag} must be true for complete Phoenix ownership" in result.stdout + result.stderr


def test_owner_preflight_checks_short_gates_without_waiting_for_soak() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nprepare_socket_phoenix_owner:", 1)[1].split("\n.PHONY: test_socket_protocol", 1)[0]
    assert recipe.index("$(MAKE) check_socket_phoenix_cutover") < recipe.index("$(MAKE) require_socket_phoenix_group")
    assert recipe.index("$(MAKE) require_socket_phoenix_group") < recipe.index(
        "$(MAKE) check_socket_phoenix_editor_restore"
    )
    assert "$(MAKE) validate_socket_phoenix_cutover_evidence" not in recipe


def test_deployment_checks_host_published_phoenix_identity() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    ingress = makefile.split("\ncheck_socket_phoenix_ingress:", 1)[1].split("\nrecord_socket_phoenix_otel_soak:", 1)[0]
    assert "/health/ready" in ingress
    assert "^HTTP/[0-9.]+ 204" in ingress
    assert "^x-langboard-socket-runtime: phoenix" in ingress
    assert "^x-langboard-socket-version:" in ingress
    for target, next_target in (
        ("start_docker", "rebuild_docker"),
        ("rebuild_docker", "clean_docker_images"),
        ("update_docker", "stop_docker"),
    ):
        recipe = makefile.split(f"\n{target}:", 1)[1].split(f"\n{next_target}:", 1)[0]
        assert "$(MAKE) check_socket_phoenix_ingress" in recipe
        assert recipe.index("$(MAKE) prepare_socket_phoenix_owner") < recipe.index(
            "$(MAKE) prepare_socket_phoenix_otel"
        )
        if target != "update_docker":
            assert recipe.index("$(MAKE) prepare_socket_phoenix_owner") < recipe.index(
                "docker compose $(COMPOSE_ARGS) build"
            )
