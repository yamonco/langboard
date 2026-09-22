import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    shell = sys.argv[1]
    source = Path(__file__).resolve().parent / "utils"
    for secret in (None, "too-short", "s" * 32):
        with tempfile.TemporaryDirectory(prefix="phoenix-config-") as directory:
            root = Path(directory)
            scripts = root / "scripts" / "utils"
            scripts.mkdir(parents=True)
            for name in ("update-docker-envs.sh", "utils.sh"):
                shutil.copyfile(source / name, scripts / name)
            output = root / "docker" / "envs"
            output.mkdir(parents=True)
            sentinel = output / ".api.env"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            for template in ("server-common", "server", "db-backup"):
                (output / f"{template}.env.template").write_text(
                    "SOCKET_HOST=${SOCKET_HOST}\nMAX_REQUEST_BODY_SIZE_BYTES=${MAX_REQUEST_BODY_SIZE_BYTES}\n",
                    encoding="utf-8",
                )
            settings = {
                "PROJECT_NAME": "fixture",
                "MAX_FILE_SIZE_MB": "50",
                "SOCKET_OWNER": "phoenix",
                "SOCKET_RUNTIME": "phoenix",
                "SOCKET_PHOENIX_KAFKA_ENABLED": "true",
                "NOTIFICATION_EMAIL_OUTBOX_ENABLED": "true",
                "MAIL_SERVER": "localhost",
                "MAIL_FROM": "fixture@example.invalid",
                "MAIL_PORT": "1025",
                "BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP": "fixture-phoenix",
                "SOCKET_PHOENIX_BOARD_CHAT_SEND_ENABLED": "true",
                "SOCKET_PHOENIX_BOARD_CHAT_RESUME_ENABLED": "true",
                "SOCKET_PHOENIX_BOARD_CHAT_RECOVERY_ENABLED": "true",
                "SOCKET_PHOENIX_EDITOR_AI_ENABLED": "true",
                "EDITOR_SYNC_OWNER": "phoenix",
                "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED": "true",
                "SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES": "1",
                "SOCKET_PHOENIX_INTERNAL_SECRET": secret or "",
            }
            (root / ".env").write_text("\n".join(f"{key}={value}" for key, value in settings.items()), encoding="utf-8")
            command = f"cd {shlex.quote(root.as_posix())} && exec ./scripts/utils/update-docker-envs.sh"
            result = subprocess.run(
                [shell, "-lc", command],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if secret is None or len(secret) < 32:
                assert result.returncode != 0, result.stderr
                assert "SOCKET_PHOENIX_INTERNAL_SECRET" in result.stderr, result.stderr
                assert sentinel.read_text(encoding="utf-8") == "unchanged\n"
            else:
                assert result.returncode == 0, result.stderr
                rendered = sentinel.read_text(encoding="utf-8")
                assert "SOCKET_HOST=fixture_socket_phoenix" in rendered
                assert "MAX_REQUEST_BODY_SIZE_BYTES=53477376" in rendered
            if secret:
                assert secret not in result.stdout + result.stderr
    print("Phoenix cutover rejects missing/short credentials before writes and accepts a valid credential.")


if __name__ == "__main__":
    main()
