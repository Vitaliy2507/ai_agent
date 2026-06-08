import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Optional


# Автоматическая загрузка .env
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                os.environ.setdefault(key, value)


@dataclass
class GigaChatConfig:
    client_id: str
    client_secret: str
    scope: str = "GIGACHAT_API_PERS"
    auth_url: str = "https://sm-auth-sd.prom-88-89-apps.ocp-geo.ocp.sigma.sbrf.ru/api/v2/oauth"
    api_url: str = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    model: str = "GigaChat"
    verify_ssl: bool = False
    ca_bundle: str = ""


@dataclass
class JiraConfig:
    base_url: str
    api_token: str


@dataclass
class BitbucketConfig:
    """
    Только параметры подключения к Bitbucket.
    Работа с конкретным репозиторием — вне этого класса.
    """
    base_url: str
    username: str
    app_password: str


@dataclass
class RepoConfig:
    """
    Конфигурация одного репозитория.
    """
    workspace: str
    repo_slug: str
    main_branch: str
    local_path: str


@dataclass
class AgentConfig:
    gigachat: GigaChatConfig
    jira: JiraConfig
    bitbucket: BitbucketConfig
    repo_mapping: List[Tuple[str, str, str, str, str]]  # label, ws, slug, branch, path
    fallback_repo: RepoConfig
    current_repo: Optional[RepoConfig] = None  # будет установлен после выбора по метке

    @classmethod
    def from_env(cls) -> "AgentConfig":
        def req(key: str) -> str:
            val = os.environ.get(key, "")
            if not val:
                raise EnvironmentError(f"Required env var '{key}' is not set.")
            return val

        gigachat = GigaChatConfig(
            client_id=req("GIGACHAT_CLIENT_ID"),
            client_secret=req("GIGACHAT_CLIENT_SECRET"),
            scope=os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            auth_url=os.environ.get(
                "GIGACHAT_AUTH_URL",
                "https://sm-auth-sd.prom-88-89-apps.ocp-geo.ocp.sigma.sbrf.ru/api/v2/oauth",
            ),
            api_url=os.environ.get(
                "GIGACHAT_API_URL",
                "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            ),
            model=os.environ.get("GIGACHAT_MODEL", "GigaChat"),
            verify_ssl=os.environ.get("GIGACHAT_VERIFY_SSL", "false").lower() == "true",
            ca_bundle=os.environ.get("GIGACHAT_CA_BUNDLE", ""),
        )

        jira = JiraConfig(
            base_url=req("JIRA_BASE_URL").rstrip("/"),
            api_token=req("JIRA_API_TOKEN"),
        )

        bitbucket = BitbucketConfig(
            base_url=req("BITBUCKET_BASE_URL").rstrip("/"),
            username=req("BITBUCKET_USERNAME"),
            app_password=req("BITBUCKET_APP_PASSWORD"),
        )

        # Парсинг маппинга
        mapping_str = os.environ.get("BITBUCKET_REPO_MAPPING", "")
        repo_mapping = []
        if mapping_str.strip():
            cleaned = mapping_str.replace("\\\n", "").replace("\\", "").strip()
            entries = cleaned.split(",")
            for entry in entries:
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split(":")
                if len(parts) != 5:
                    raise RuntimeError(f"Invalid format in BITBUCKET_REPO_MAPPING: expected 5 fields, got {len(parts)} in '{entry}'")
                label, workspace, repo_slug, main_branch, local_path = parts
                repo_mapping.append((label, workspace, repo_slug, main_branch, local_path))

        # Fallback репозиторий
        fallback_repo = RepoConfig(
            workspace=req("BITBUCKET_FALLBACK_WORKSPACE"),
            repo_slug=req("BITBUCKET_FALLBACK_REPO_SLUG"),
            main_branch=req("BITBUCKET_FALLBACK_MAIN_BRANCH"),
            local_path=req("BITBUCKET_FALLBACK_REPO_PATH"),
        )

        return cls(
            gigachat=gigachat,
            jira=jira,
            bitbucket=bitbucket,
            repo_mapping=repo_mapping,
            fallback_repo=fallback_repo,
        )