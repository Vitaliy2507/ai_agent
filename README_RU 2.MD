# GigaChat CI/CD Агент

AI-агент, который читает задачу в Jira, использует **GigaChat** для определения необходимых изменений в конфигурации, применяет их, делает коммит в новую ветку git, отправляет изменения в **Bitbucket** и открывает **Pull Request** — всё автоматически.

## Архитектура

```
python agent.py PROJ-123
        │
        ▼
┌─────────────────┐     description      ┌──────────────────┐
│   Jira Client   │ ──────────────────►  │  GigaChat Client │
│  (REST API v2)  │                      │  (OAuth2 + chat) │
└─────────────────┘                      └────────┬─────────┘
                                                  │ JSON patch
                                         ┌────────▼─────────┐
                                         │ Config Patcher   │
                                         │ (deep-merge JSON)│
                                         └────────┬─────────┘
                                                  │ file saved
                                         ┌────────▼─────────┐
                                         │  Git Manager     │
                                         │(subprocess only) │
                                         └────────┬─────────┘
                                                  │ branch pushed
                                         ┌────────▼─────────┐
                                         │ Bitbucket Client │
                                         └────────┬─────────┘
                                                  │ PR URL
                                         ┌────────▼─────────┐
                                         │ Jira: add comment│
                                         └──────────────────┘
```

## Структура файлов

```
gigachat_agent/
├── agent.py            # Оркестратор – точка входа
├── config.py           # Классы данных, загрузка из переменных окружения
├── gigachat_client.py  # OAuth2 + /chat/completions
├── jira_client.py      # Jira REST API v2
├── bitbucket_client.py # Bitbucket Cloud и Server REST API
├── git_manager.py      # git через subprocess (без gitpython)
├── config_patcher.py   # Глубокое слияние JSON и запись обратно
└── .env.example        # Все необходимые переменные окружения
```

## Установка

### 1. Установить зависимости

```bash
pip install requests
```

Всё — всё остальное уже включено в стандартную библиотеку Python.

### 2. Настроить переменные окружения

```bash
cp .env.example .env
# Отредактируйте .env с вашими учётными данными
source .env
```

### 3. Клонировать целевой репозиторий локально

```bash
git clone git@bitbucket.org:workspace/your-repo.git /path/to/local/repo
```

Убедитесь, что git remote настроен с учётными данными (SSH-ключ или HTTPS с менеджером учётных данных).

### 4. Запуск

```bash
python agent.py PROJ-123
```

## Как GigaChat редактирует конфигурацию

Агент отправляет **полный текущий файл конфигурации** + **описание задачи в Jira** в GigaChat и просит вернуть **только объект JSON-патча** — ключи, которые нужно добавить или изменить. Пример:

Описание задачи в Jira:
> Установить размер пула подключений в 20 и включить новый флаг функции `use_v2_api`.

Ответ GigaChat:
```json
{"db": {"pool_size": 20}, "features": {"use_v2_api": true}}
```

Этот патч глубоко объединяется с существующей конфигурацией. Изменяются только указанные ключи; всё остальное сохраняется.

## Bitbucket: Cloud и Server

| Переменная                    | Cloud                                 | Server/DC                             |
|-------------------------------|---------------------------------------|---------------------------------------|
| `BITBUCKET_BASE_URL`          | `https://api.bitbucket.org/2.0`       | `https://bb.company.com/rest/api/1.0` |
| `BITBUCKET_WORKSPACE`         | slug рабочей области                  | ключ проекта (например, `OPS`)        |
| `BITBUCKET_APP_PASSWORD`      | Пароль приложения                     | Токен личного доступа                 |