import os
from pathlib import Path

# Автозагрузка .env
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
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

import json
import logging
import sys
from pathlib import Path

from config import AgentConfig, RepoConfig
from gigachat_client import GigaChatClient
from jira_client import JiraClient
from git_manager import GitManager
from bitbucket_client import BitbucketClient
from config_patcher import ConfigPatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("agent")

CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".env"}


def collect_config_files(repo_path: str) -> dict:
    repo = Path(repo_path)
    result = {}
    for p in sorted(repo.rglob("*")):
        if not p.is_file() or ".git" in p.parts or p.suffix.lower() not in CONFIG_EXTENSIONS:
            continue
        try:
            content = p.read_text(encoding="utf-8")
            result[str(p.relative_to(repo))] = content
        except (UnicodeDecodeError, PermissionError) as exc:
            log.warning("Skipping %s: %s", p, exc)
    log.info("Found %d config file(s) in repo", len(result))
    return result


def run(jira_issue_key: str):
    cfg = AgentConfig.from_env()
    giga = GigaChatClient(cfg.gigachat)
    log.info("=== GigaChat Multi-Agent Agent starting for issue %s ===", jira_issue_key)

    #  1. Стягиваем Jira task 
    jira = JiraClient(cfg.jira)
    issue = jira.get_issue(jira_issue_key)
    summary = issue["fields"]["summary"]
    description = issue["fields"].get("description") or ""
    labels = issue["fields"].get("labels", [])
    log.info("Jira issue fetched: %s", summary)
    log.info("Jira labels: %s", labels)

    #  2. Выбор репозитория по метке из .env 
    selected = None
    for label, workspace, repo_slug, main_branch, repo_path in cfg.repo_mapping:
        if label in labels:
            log.info("Matched label '%s' → using repository: %s/%s", label, workspace, repo_slug)
            selected = {
                "workspace": workspace,
                "repo_slug": repo_slug,
                "main_branch": main_branch,
                "repo_path": repo_path,
            }
            break

    if selected is None:
        log.warning("No matching label found → using fallback repository")
        fb = cfg.fallback_repo
        selected = {
            "workspace": fb.workspace,
            "repo_slug": fb.repo_slug,
            "main_branch": fb.main_branch,
            "repo_path": fb.local_path,
        }

    # Сохраняем в конфиг как текущий репозиторий
    cfg.current_repo = RepoConfig(
        workspace=selected["workspace"],
        repo_slug=selected["repo_slug"],
        main_branch=selected["main_branch"],
        local_path=selected["repo_path"],
    )

    log.info("Using repository: %s/%s, branch: %s, local path: %s",
             selected["workspace"], selected["repo_slug"], selected["main_branch"], selected["repo_path"])

    #  3. Собираем конфигурационные файлы из выбранного репозитория 
    config_files = collect_config_files(cfg.current_repo.local_path)
    if not config_files:
        log.error("No configuration files found in %s", cfg.current_repo.local_path)
        sys.exit(1)

    #  4. Step 1: Аналитик — Найти все файлы для изменения
    file_list = "\n".join(f"- {path}" for path in config_files)
    analyst_prompt = (
        f"Вы — точный аналитик конфигураций.\n\n"
        f"Задача:\n{summary}\n{description}\n\n"
        f"Доступные файлы:\n{file_list}\n\n"
        f"ИНСТРУКЦИЯ:\n"
        f"- Верните ТОЛЬКО JSON-массив путей.\n"
        f"- ВКЛЮЧИТЕ КАЖДЫЙ файл, где нужно изменить значение (например, pprbvis.apps...).\n"
        f"- Не пропускайте файлы только потому, что они похожи.\n"
        f"- Никаких пояснений, markdown или ```json.\n\n"
        f'Пример: ["apps/egress/values-psi.yaml", "apps/iit-document-supply/values-psi.yaml"]'
    )

    raw_selection = giga.chat(analyst_prompt)
    log.info("Analyst selected files:\n%s", raw_selection)

    try:
        # Убираем markdown-блоки
        clean = raw_selection.strip().strip("```json").strip("```").strip()

        # Заменяем "умные" кавычки и другие некорректные символы
        clean = (
            clean
            .replace("“", '"')           # открывающая умная кавычка
            .replace("”", '"')           # закрывающая умная кавычка
            .replace("‘", "'")           # одинарная умная
            .replace("’", "'")           # одинарная умная
            .replace("\u0093", '"')      # возможные control chars
            .replace("\u0094", '"')
            .replace("\n", "")           # убираем разрывы строк в JSON
            .replace("\r", "")
            .strip()
        )

        # Повторно пытаемся распарсить
        relevant_paths = json.loads(clean)
        if not isinstance(relevant_paths, list):
            raise ValueError("Not a JSON array")
    except json.JSONDecodeError as e:
        log.error("JSON decode error: %s at position %d", e.msg, e.pos)
        log.error("Raw cleaned response: %s", clean)
        sys.exit(1)
    except Exception as exc:
        log.error("Failed to parse analyst response: %s", exc)
        sys.exit(1)

    relevant_paths = [p for p in relevant_paths if p in config_files]
    if not relevant_paths:
        log.warning("No valid files selected — aborting.")
        sys.exit(0)
    log.info("Files for patching: %s", relevant_paths)

    #  5. Step 2: Редактор — Создание изменений 
    files_block = "\n\n".join(f"### {path}\n{config_files[path]}" for path in relevant_paths)

    def get_editor_patch() -> dict:
        editor_prompt = (
            f"Вы — точный редактор конфигураций. Ваша задача — изменить значение существующего ключа.\n\n"
            f"Задача:\n{description}\n\n"
            f"Файлы:\n{files_block}\n\n"
            f"ИНСТРУКЦИЯ:\n"
            f"1. Верните ТОЛЬКО валидный JSON-объект.\n"
            f"2. Ключи объекта — пути к файлам.\n"
            f"3. Значения — {{\"ТОЧНЫЙ_КЛЮЧ\": \"НОВОЕ_ЗНАЧЕНИЕ\"}}, где НОВОЕ_ЗНАЧЕНИЕ — ДОСЛОВНО из задачи.\n"
            f"4. Если в задаче написано 'something_test_ai_agent' — используйте именно это.\n"
            f"   Никаких сокращений до '_test_ai'!\n"
            f"5. Никаких доменов в ключах.\n"
            f"6. Никаких пояснений, markdown, ```json.\n\n"
            f"Пример:\n"
            f'{{\n'
            f'  "apps/egress/values-psi.yaml": {{\n'
            f'    "PPRB_VIS_CLIENT_URL": "http://something_test_ai_agent.apps.url.ru:9415/something"\n'
            f'  }}\n'
            f'}}'
        )
        raw = giga.chat(editor_prompt)
        log.info("Editor patch response:\n%s", raw)
        try:
            clean = raw.strip().strip("```json").strip("```").strip()
            data = json.loads(clean)
            if not isinstance(data, dict):
                raise ValueError("Not a JSON object")
            return data
        except Exception as exc:
            log.error("Failed to parse editor patch: %s", exc)
            return {}

    #  6. Step 3: Валидатор — Проверка изменений 
    def validate_patch(patches: dict) -> bool:
        validator_prompt = (
            f"Вы — строгий валидатор патчей. Проверьте корректность.\n\n"
            f"Описание задачи:\n{description}\n\n"
            f"Все доступные файлы:\n" + "\n".join(f"- {p}" for p in config_files.keys()) + "\n\n"
            f"Предложенный патч:\n{json.dumps(patches, indent=2)}\n\n"
            f"Проверьте:\n"
            f"1. Содержится ли в новых значениях строка 'pprbvis_test_ai_agent'? (НЕ 'test_ai')\n"
            f"2. Все ли целевые файлы включены? (egress, iit-document-supply, iit-report-aggregator)\n"
            f"3. Нет ли в ключах доменов (например, 'pprbvis.apps...')?\n\n"
            f"Если всё верно — верните {{\"valid\": true}}\n"
            f"Если нет — верните {{\"valid\": false, \"reason\": \"причина\"}}\n"
            f"Только JSON, без пояснений."
        )
        raw = giga.chat(validator_prompt)
        log.info("Validator response:\n%s", raw)
        try:
            clean = raw.strip().strip("```json").strip("```").strip()
            result = json.loads(clean)
            return result.get("valid", False)
        except Exception as exc:
            log.error("Failed to parse validator response: %s", exc)
            return False

    #  7. Цикл: Редактор + Валидатор (до 3 попыток) 
    patches = {}
    for attempt in range(3):
        log.info("Attempt %d: Editor → Validator", attempt + 1)
        patches = get_editor_patch()
        if not patches:
            log.warning("Editor returned empty patch.")
            continue
        if validate_patch(patches):
            log.info("✅ Patch validated successfully.")
            break
        log.warning("❌ Patch validation failed. Retrying...")
    else:
        log.error("❌ All attempts failed. Aborting.")
        sys.exit(1)

    log.info("Final patches to apply:\n%s", json.dumps(patches, indent=2, ensure_ascii=False))

    #  8. Применение изменений 
    repo = Path(cfg.current_repo.local_path)
    applied = {}
    for relative_path, patch in patches.items():
        full_path = repo / relative_path
        if not full_path.exists():
            log.warning("Skipping unknown path: %s", relative_path)
            continue
        try:
            patcher = ConfigPatcher(str(full_path))
            patcher.apply(patch)
            applied[relative_path] = patch
            log.info("Patched: %s → %s", relative_path, patch)
        except Exception as exc:
            log.error("Failed to patch %s: %s", relative_path, exc)

    if not applied:
        log.warning("No files were patched — aborting.")
        sys.exit(0)

    #  9. Git: создание ветки и коммит
    branch_name = f"feature/{jira_issue_key.lower()}-auto-config"
    git = GitManager(cfg.current_repo.local_path)
    git.create_branch(branch_name, from_branch=cfg.current_repo.main_branch)
    git.commit_all(f"[{jira_issue_key}] Auto-update config: {summary}")
    git.push(branch_name)
    log.info("Pushed branch: %s", branch_name)

    #  10. Bitbucket: открыть Pull Request 
    changes_summary = "\n".join(
        f"- `{path}`:\n```json\n{json.dumps(patch, indent=2)}\n```"
        for path, patch in applied.items()
    )

    # Обновляем cfg.bitbucket на лету — добавляем workspace и repo_slug
    bb_cfg = cfg.bitbucket
    bb_cfg.workspace = cfg.current_repo.workspace
    bb_cfg.repo_slug = cfg.current_repo.repo_slug

    bb = BitbucketClient(bb_cfg)
    pr = bb.create_pull_request(
        title=f"[{jira_issue_key}] {summary}",
        description=(
            f"Automated config update by multi-agent GigaChat system.\n\n"
            f"Jira: {jira_issue_key}\n\n"
            f"Files changed:\n{changes_summary}"
        ),
        source_branch=branch_name,
        destination_branch=cfg.current_repo.main_branch,
    )

    # Извлекаем URL из ответа Bitbucket
    pr_url = pr.get("links", {}).get("self", [{}])[0].get("href", "URL not available")

    log.info("Pull request created: %s", pr_url)

    #  11. Добавление комментария в Jira 
    comment_lines = [f"✅ Automated PR created by GigaChat Multi-Agent:\n{pr_url}\n"]
    for path, patch in applied.items():
        comment_lines.append(
            f"*{path}*\n{{code:json}}\n{json.dumps(patch, indent=2)}\n{{code}}"
        )
    jira.add_comment(jira_issue_key, "\n\n".join(comment_lines))

    log.info("=== Pipeline completed successfully ===")
    return pr_url

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python agent.py <JIRA-ISSUE-KEY>")
        sys.exit(1)
    run(sys.argv[1])