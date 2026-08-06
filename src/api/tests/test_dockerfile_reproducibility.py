import re
from pathlib import Path


ROOT = Path(__file__).parents[3]


def test_python_and_uv_images_are_digest_pinned_without_remote_installer() -> None:
    """The API image uses immutable runtime/tool inputs and no mutable install script."""

    dockerfile = (ROOT / "Dockerfile").read_text()
    lines = dockerfile.splitlines()

    assert re.fullmatch(
        r"FROM ghcr\.io/astral-sh/uv:0\.11\.28@sha256:[0-9a-f]{64} AS uv",
        lines[0],
    )
    assert re.fullmatch(
        r"FROM python:3\.12@sha256:[0-9a-f]{64} AS base",
        lines[1],
    )
    assert "astral.sh/uv/install.sh" not in dockerfile
    assert "RUN cron" not in dockerfile
    assert dockerfile.count("uv sync --locked") == 4
    assert dockerfile.count("uv sync --locked --no-dev") == 4


def test_api_runtime_excludes_document_processing_extra() -> None:
    """Install Docling only in the broker worker image, never in API workers."""

    pyproject = (ROOT / "pyproject.toml").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "docker" / "docker-compose.server.yaml").read_text()
    example_environment = (ROOT / ".env.example").read_text()

    required, optional = pyproject.split("[project.optional-dependencies]", maxsplit=1)
    assert '"docling>=2.105.0"' not in required
    assert 'document-processing = [' in optional
    assert '"docling>=2.105.0"' in optional
    assert "FROM base AS with-document-processing" in dockerfile
    assert "uv sync --locked --no-dev --extra document-processing" in dockerfile
    assert "target: with-document-processing" in compose
    assert "API_WORKERS_COUNT=2" in example_environment


def test_compose_cron_target_uses_safe_dockerfile_default() -> None:
    """The cron image installs a valid empty table without a phantom build argument."""

    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "docker" / "docker-compose.server.yaml").read_text()

    assert "ARG CRON_TAB_FILE" not in dockerfile
    assert "printf '' | crontab -" in dockerfile
    assert "RUN cron" not in dockerfile
    assert "target: with-cron" in compose
    assert "CRON_TAB_FILE:" not in compose


def test_environment_renderer_is_release_worktree_safe() -> None:
    """Resolve the repository root from the script, not its checkout basename."""

    renderer = (ROOT / "scripts" / "utils" / "update-docker-envs.sh").read_text()

    assert renderer.startswith("#!/bin/bash\nset -e\n")
    assert 'ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"' in renderer
    assert 'cd "$ROOT_DIR"' in renderer
    assert 'CURRENT_DIR=$(basename "$PWD")' not in renderer
    assert '== "langboard"' not in renderer
