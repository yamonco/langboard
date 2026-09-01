from enum import Enum
from importlib.metadata import version
from os import environ
from os.path import dirname
from pathlib import Path
from typing import Any, Literal, cast
from dotenv import load_dotenv
from .core.utils.decorators import class_instance, thread_safe_singleton


expected_env_paths = ["../../../../../", "../../../../", "../../../", "../../", "../", "./"]
for env_path in expected_env_paths:
    env_path = Path(env_path) / ".env"
    if not env_path.is_file():
        continue
    load_dotenv(env_path)
expected_env_paths.clear()


@class_instance()
@thread_safe_singleton
class Env:
    @property
    def IS_EXECUTABLE(self) -> bool:
        return self.__get_from_cache("IS_EXECUTABLE", "false") == "true"

    @property
    def IS_CLI(self) -> bool:
        return self.__get_from_cache("IS_CLI", "false") == "true"

    @property
    def ENVIRONMENT(self) -> Literal["development", "production"]:
        return cast(Any, self.__get_from_cache("ENVIRONMENT", "development"))

    @property
    def PROJECT_NAME(self) -> str:
        return self.__get_from_cache("PROJECT_NAME")

    @property
    def PROJECT_SHORT_NAME(self) -> str:
        return self.__get_from_cache("PROJECT_SHORT_NAME", self.PROJECT_NAME)

    @property
    def PROJECT_VERSION(self) -> str:
        try:
            return version(self.PROJECT_NAME)
        except Exception:
            return version(cast(str, __package__))

    @property
    def ADMIN_EMAIL(self) -> str:
        return self.__get_from_cache("ADMIN_EMAIL")

    @property
    def ADMIN_PASSWORD(self) -> str:
        return self.__get_from_cache("ADMIN_PASSWORD")

    @property
    def FULL_ADMIN_ACCESS_EMAILS(self) -> set[str]:
        emails = self.__get_from_cache("FULL_ADMIN_ACCESS_EMAILS", "")
        return set(email.strip() for email in emails.split(",") if email.strip())

    @property
    def API_PORT(self) -> int:
        return int(self.__get_from_cache("API_PORT", "5381"))

    @property
    def API_HOST(self) -> str:
        return self.__get_from_cache("API_HOST", "localhost")

    @property
    def API_INTERNAL_URL(self) -> str:
        return self.__get_from_cache("API_INTERNAL_URL", f"http://{self.API_HOST}:{self.API_PORT}").rstrip("/")

    @property
    def MCP_ALLOWED_HOSTS(self) -> list[str]:
        """Return explicitly allowed MCP Host header values."""

        hosts = self.__get_from_cache("MCP_ALLOWED_HOSTS", "")
        return [host.strip() for host in hosts.split(",") if host.strip()]

    @property
    def MCP_ALLOWED_ORIGINS(self) -> list[str]:
        """Return explicitly allowed MCP Origin header values."""

        origins = self.__get_from_cache("MCP_ALLOWED_ORIGINS", "")
        return [origin.strip().rstrip("/") for origin in origins.split(",") if origin.strip()]

    @property
    def UI_PORT(self) -> int:
        return int(self.__get_from_cache("UI_PORT", "5173"))

    @property
    def SOCKET_PORT(self) -> int:
        return int(self.__get_from_cache("SOCKET_PORT", "5690"))

    @property
    def SOCKET_INTERNAL_URL(self) -> str:
        return self.__get_from_cache("SOCKET_INTERNAL_URL", f"http://localhost:{self.SOCKET_PORT}").rstrip("/")

    @property
    def API_URL(self) -> str:
        return (
            self.__get_from_cache("API_URL", f"http://localhost:{self.API_PORT}")
            if self.ENVIRONMENT != "development"
            else f"http://localhost:{self.API_PORT}"
        )

    @property
    def PUBLIC_UI_URL(self) -> str:
        return (
            self.__get_from_cache("PUBLIC_UI_URL", f"http://localhost:{self.UI_PORT}")
            if self.ENVIRONMENT != "development"
            else f"http://localhost:{self.UI_PORT}"
        )

    @property
    def GRAPH_PORT(self) -> int:
        return int(self.__get_from_cache("GRAPH_PORT", "5020"))

    @property
    def DEFAULT_GRAPH_URL(self) -> str:
        return self.__get_from_cache("DEFAULT_GRAPH_URL", f"http://127.0.0.1:{self.GRAPH_PORT}")

    @property
    def DOMAIN(self) -> str | None:
        return self.__get_from_cache("DOMAIN", None) if self.ENVIRONMENT != "development" else "localhost"

    @property
    def UI_REDIRECT_URL(self) -> str:
        return f"{self.PUBLIC_UI_URL}/redirect"

    @property
    def OLLAMA_API_URL(self) -> str | None:
        return self.__get_from_cache("OLLAMA_API_URL", None)

    @property
    def AI_REQUEST_TIMEOUT(self) -> int:
        return int(self.__get_from_cache("AI_REQUEST_TIMEOUT", "120"))

    @property
    def AI_REQUEST_TRIALS(self) -> int:
        return int(self.__get_from_cache("AI_REQUEST_TRIALS", "5"))

    @property
    def MAX_FILE_SIZE_MB(self) -> int:
        return int(self.__get_from_cache("MAX_FILE_SIZE_MB", "50"))

    @property
    def BATCH_MAX_RESPONSE_SIZE_MB(self) -> int:
        return int(self.__get_from_cache("BATCH_MAX_RESPONSE_SIZE_MB", "10"))

    @property
    def SETTINGS_USER_LIST_MAX_ITEMS(self) -> int:
        return int(self.__get_from_cache("SETTINGS_USER_LIST_MAX_ITEMS", "5000"))

    @property
    def GRAPH_TOOL_MAX_RESPONSE_SIZE_KB(self) -> int:
        return int(self.__get_from_cache("GRAPH_TOOL_MAX_RESPONSE_SIZE_KB", "256"))

    @property
    def GRAPH_BACKGROUND_MAX_CONCURRENCY(self) -> int:
        return int(self.__get_from_cache("GRAPH_BACKGROUND_MAX_CONCURRENCY", "2"))

    @property
    def BROKER_TASK_MAX_PAYLOAD_KB(self) -> int:
        return int(self.__get_from_cache("BROKER_TASK_MAX_PAYLOAD_KB", "1024"))

    @property
    def DOCLING_CONVERSION_TIMEOUT_SECONDS(self) -> int:
        return int(self.__get_from_cache("DOCLING_CONVERSION_TIMEOUT_SECONDS", "900"))

    @property
    def MAIN_DATABASE_URL(self) -> str:
        return self.__get_from_cache(
            "MAIN_DATABASE_URL", f"sqlite:///{(self.ROOT_DIR / f'{self.PROJECT_NAME}.db').as_posix()}"
        )

    @property
    def READONLY_DATABASE_URL(self) -> str:
        return self.__get_from_cache("READONLY_DATABASE_URL", self.MAIN_DATABASE_URL)

    @property
    def DB_TIMEOUT(self) -> int:
        return int(self.__get_from_cache("DB_TIMEOUT", "120"))

    @property
    def DB_TCP_USER_TIMEOUT(self) -> int:
        return int(self.__get_from_cache("DB_TCP_USER_TIMEOUT", "30000"))

    @property
    def DB_POOL_SIZE(self) -> int:
        return int(self.__get_from_cache("DB_POOL_SIZE", "5"))

    @property
    def DB_MAX_OVERFLOW(self) -> int:
        return int(self.__get_from_cache("DB_MAX_OVERFLOW", "10"))

    @property
    def DB_POOL_TIMEOUT(self) -> int:
        return int(self.__get_from_cache("DB_POOL_TIMEOUT", "30"))

    @property
    def DB_POOL_RECYCLE(self) -> int:
        return int(self.__get_from_cache("DB_POOL_RECYCLE", "1800"))

    @property
    def DB_QUERY_CACHE_SIZE(self) -> int:
        return int(self.__get_from_cache("DB_QUERY_CACHE_SIZE", "0"))

    @property
    def DB_SELECT_RETRY_ATTEMPTS(self) -> int:
        return int(self.__get_from_cache("DB_SELECT_RETRY_ATTEMPTS", "3"))

    @property
    def DB_READONLY_FALLBACK_TO_MAIN(self) -> bool:
        return self.__get_from_cache("DB_READONLY_FALLBACK_TO_MAIN", "true").lower() == "true"

    @property
    def TERMINAL_LOGGING_LEVEL(self) -> str:
        return self.__get_from_cache("TERMINAL_LOGGING_LEVEL", "AUTO").upper()

    @property
    def FILE_LOGGING_LEVEL(self) -> str:
        return self.__get_from_cache("FILE_LOGGING_LEVEL", "AUTO").upper()

    @property
    def SENTRY_DSN(self) -> str:
        return self.__get_from_cache("SENTRY_DSN")

    @property
    def BROADCAST_TYPE(self) -> Literal["in-memory", "kafka"]:
        broadcast_type = cast(Any, self.__get_from_cache("BROADCAST_TYPE", "in-memory"))
        _available_broadcast_types = {"in-memory", "kafka"}
        if broadcast_type not in _available_broadcast_types:
            raise ValueError(f"Invalid broadcast type: {broadcast_type}. Must be one of {_available_broadcast_types}")
        return broadcast_type

    @property
    def BROADCAST_URLS(self) -> list[str]:
        urls = self.__get_from_cache("BROADCAST_URLS", "")
        return urls.split(",") if urls else []

    @property
    def CACHE_TYPE(self) -> Literal["in-memory", "redis"]:
        cache_type = cast(Any, self.__get_from_cache("CACHE_TYPE", "in-memory"))
        _available_cache_types = {"in-memory", "redis"}
        if cache_type not in _available_cache_types:
            raise ValueError(f"Invalid cache type: {cache_type}. Must be one of {_available_cache_types}")
        return cache_type

    @property
    def CACHE_URL(self) -> str:
        return self.__get_from_cache("CACHE_URL", "")

    @property
    def BROKER_URL(self) -> str:
        return self.__get_from_cache("BROKER_URL", self.CACHE_URL)

    @property
    def COMMON_SECRET_KEY(self) -> str:
        return self.__get_from_cache("COMMON_SECRET_KEY", f"{self.PROJECT_NAME}_common_key")

    @property
    def JWT_SECRET_KEY(self) -> str:
        return self.__get_from_cache("JWT_SECRET_KEY", f"{self.PROJECT_NAME}_secret_key")

    @property
    def JWT_ALGORITHM(self) -> str:
        return self.__get_from_cache("JWT_ALGORITHM", "HS256")

    @property
    def JWT_AT_EXPIRATION(self) -> int:
        return int(self.__get_from_cache("JWT_AT_EXPIRATION", 60 * 60 * 3))  # 3 hours for default

    @property
    def JWT_RT_EXPIRATION(self) -> int:
        return int(self.__get_from_cache("JWT_RT_EXPIRATION", 30))  # 30 days for default

    @property
    def AUTH_PROVIDER(self) -> Literal["local", "oidc", "hybrid"]:
        auth_provider = cast(Any, self.__get_from_cache("AUTH_PROVIDER", "local")).lower()
        _available_auth_providers = {"local", "oidc", "hybrid"}
        if auth_provider not in _available_auth_providers:
            raise ValueError(f"Invalid auth provider: {auth_provider}. Must be one of {_available_auth_providers}")
        return auth_provider

    @property
    def OIDC_ENABLED(self) -> bool:
        return self.AUTH_PROVIDER in {"oidc", "hybrid"}

    @property
    def OIDC_ISSUER(self) -> str:
        return self.__get_from_cache("OIDC_ISSUER", "")

    @property
    def OIDC_DISCOVERY_URL(self) -> str:
        return self.__get_from_cache("OIDC_DISCOVERY_URL", "")

    @property
    def OIDC_CLIENT_ID(self) -> str:
        return self.__get_from_cache("OIDC_CLIENT_ID", "")

    @property
    def OIDC_CLIENT_SECRET(self) -> str:
        return self.__get_from_cache("OIDC_CLIENT_SECRET", "")

    @property
    def OIDC_REDIRECT_URI(self) -> str:
        return f"{self.PUBLIC_UI_URL}/auth/oidc/callback"

    @property
    def OIDC_SCOPES(self) -> str:
        return self.__get_from_cache("OIDC_SCOPES", "openid profile email")

    @property
    def OIDC_EMAIL_CLAIM(self) -> str:
        return self.__get_from_cache("OIDC_EMAIL_CLAIM", "email")

    @property
    def OIDC_PROMPT(self) -> str:
        return self.__get_from_cache("OIDC_PROMPT", "")

    @property
    def OIDC_TIMEOUT_SEC(self) -> int:
        return int(self.__get_from_cache("OIDC_TIMEOUT_SEC", "10"))

    @property
    def OIDC_DISCOVERY_CACHE_SEC(self) -> int:
        return int(self.__get_from_cache("OIDC_DISCOVERY_CACHE_SEC", "3600"))

    @property
    def OIDC_JWKS_CACHE_TTL_SEC(self) -> int:
        return int(self.__get_from_cache("OIDC_JWKS_CACHE_TTL_SEC", "3600"))

    @property
    def OIDC_CLOCK_SKEW_SEC(self) -> int:
        return int(self.__get_from_cache("OIDC_CLOCK_SKEW_SEC", "60"))

    @property
    def SCIM_ENABLED(self) -> bool:
        return self.__get_from_cache("SCIM_ENABLED", "false").lower() == "true"

    @property
    def SCIM_BEARER_TOKEN(self) -> str:
        return self.__get_from_cache("SCIM_BEARER_TOKEN", "")

    @property
    def SCIM_ISSUER(self) -> str:
        return self.__get_from_cache("SCIM_ISSUER", "")

    @property
    def REFRESH_TOKEN_NAME(self) -> str:
        return f"refresh_token_{self.PROJECT_SHORT_NAME}"

    @property
    def S3_ACCESS_KEY_ID(self) -> str:
        return self.__get_from_cache("S3_ACCESS_KEY_ID")

    @property
    def S3_SECRET_ACCESS_KEY(self) -> str:
        return self.__get_from_cache("S3_SECRET_ACCESS_KEY")

    @property
    def S3_REGION_NAME(self) -> str:
        return self.__get_from_cache("S3_REGION_NAME", "us-east-1")

    @property
    def S3_BUCKET_NAME(self) -> str:
        return self.__get_from_cache("S3_BUCKET_NAME", self.PROJECT_NAME)

    @property
    def MAIL_FROM(self) -> str:
        return self.__get_from_cache("MAIL_FROM")

    @property
    def MAIL_FROM_NAME(self) -> str:
        return self.__get_from_cache("MAIL_FROM_NAME", f"{self.PROJECT_NAME.capitalize()} Team")

    @property
    def MAIL_USERNAME(self) -> str:
        return self.__get_from_cache("MAIL_USERNAME", "")

    @property
    def MAIL_PASSWORD(self) -> str:
        return self.__get_from_cache("MAIL_PASSWORD", "")

    @property
    def MAIL_SERVER(self) -> str:
        return self.__get_from_cache("MAIL_SERVER")

    @property
    def MAIL_PORT(self) -> int:
        return int(self.__get_from_cache("MAIL_PORT", "587"))

    @property
    def MAIL_STARTTLS(self) -> bool:
        return self.__get_from_cache("MAIL_STARTTLS", "true") == "true"

    @property
    def MAIL_SSL_TLS(self) -> bool:
        return self.__get_from_cache("MAIL_SSL_TLS", "false") == "true"

    @property
    def WORKER(self) -> str:
        return self.__get_from_cache("WORKER", "main")

    @property
    def ROOT_DIR(self) -> Path:
        return Path(dirname(__file__)).parent.parent.parent.parent

    @property
    def DATA_DIR(self) -> Path:
        data_dir = self.ROOT_DIR / "local" if not self.IS_EXECUTABLE else self.ROOT_DIR / "data"
        data_dir.mkdir(exist_ok=True)
        return data_dir

    @property
    def SCHEMA_DIR(self) -> Path:
        schema_dir = self.DATA_DIR / "schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        return schema_dir

    @property
    def LOCAL_STORAGE_DIR(self) -> Path:
        local_storage_dir = self.DATA_DIR / "uploads"
        local_storage_dir.mkdir(parents=True, exist_ok=True)
        return local_storage_dir

    @property
    def CRON_TAB_FILE(self) -> Path:
        cron_tab_file = Path(self.get_from_env("CRON_TAB_FILE", self.DATA_DIR / "cron.tab"))
        return cron_tab_file

    @property
    def CACHE_DIR(self) -> Path:
        cache_dir = self.DATA_DIR / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @property
    def LOGGING_DIR(self) -> Path:
        logging_dir = Path(Env.get_from_env("LOGGING_DIR", Env.DATA_DIR / "logs"))
        logging_dir.mkdir(parents=True, exist_ok=True)
        return logging_dir

    @property
    def KEY_PROVIDER_TYPE(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_TYPE", "openbao-local").lower()

    @property
    def KEY_PROVIDER_OPENBAO_URL(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_OPENBAO_URL", "http://127.0.0.1:8200")

    @property
    def KEY_PROVIDER_HASHICORP_URL(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_HASHICORP_URL", "http://127.0.0.1:8200")

    @property
    def KEY_PROVIDER_HASHICORP_ROLE_ID(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_HASHICORP_ROLE_ID", "")

    @property
    def KEY_PROVIDER_HASHICORP_SECRET_ID(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_HASHICORP_SECRET_ID", "")

    @property
    def KEY_PROVIDER_AWS_REGION(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AWS_REGION", "")

    @property
    def KEY_PROVIDER_AWS_ACCESS_KEY_ID(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AWS_ACCESS_KEY_ID", "")

    @property
    def KEY_PROVIDER_AWS_SECRET_ACCESS_KEY(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AWS_SECRET_ACCESS_KEY", "")

    @property
    def KEY_PROVIDER_AWS_KMS_KEY_ARN(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AWS_KMS_KEY_ARN", "")

    @property
    def KEY_PROVIDER_AZURE_KEYVAULT_URL(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AZURE_KEYVAULT_URL", "")

    @property
    def KEY_PROVIDER_AZURE_CLIENT_ID(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AZURE_CLIENT_ID", "")

    @property
    def KEY_PROVIDER_AZURE_CLIENT_SECRET(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AZURE_CLIENT_SECRET", "")

    @property
    def KEY_PROVIDER_AZURE_TENANT_ID(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AZURE_TENANT_ID", "")

    @property
    def KEY_PROVIDER_AZURE_ENCRYPTION_KEY_NAME(self) -> str:
        return self.__get_from_cache("KEY_PROVIDER_AZURE_ENCRYPTION_KEY_NAME", "api-key-encryption")

    def __init__(self):
        self.__envs = {}

    def get_from_env(self, name: str, default: Any = None) -> Any | str:
        is_default = name not in environ or not environ[name]
        return default if is_default else environ[name]

    def update_env(self, name: str, value: Any) -> None:
        if not hasattr(self, name):
            raise AttributeError(f"Environment variable '{name}' does not exist.")

        self.__envs[name] = value

    def __get_from_cache(self, name: str, default: Any = None) -> Any | str:
        if name not in self.__envs:
            self.__envs[name] = self.get_from_env(name, default)
        return self.__envs[name]


# UI query names
class UI_QUERY_NAMES(Enum):
    SUB_EMAIL_VERIFY_TOKEN = "bEvt"
    RECOVERY_TOKEN = "rtK"
    SIGN_UP_ACTIVATE_TOKEN = "sAVk"
    PROJCT_INVITATION_TOKEN = "PikQ"
    BOARD = "bp"
    BOARD_CARD = "BpC"
    BOARD_CARD_CHUNK = "BpCC"
    BOARD_WIKI = "bPw"
    BOARD_WIKI_CHUNK = "BpWc"
