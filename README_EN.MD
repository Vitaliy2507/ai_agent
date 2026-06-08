# GigaChat CI/CD Agent

An AI agent that reads a Jira task, uses **GigaChat** to determine what config changes are needed, applies them, commits to a new git branch, pushes to **Bitbucket**, and opens a **Pull Request** — all automatically.

## Architecture

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

## File layout

```
gigachat_agent/
├── agent.py            # Orchestrator – entry point
├── config.py           # Dataclasses, loads from env vars
├── gigachat_client.py  # OAuth2 + /chat/completions
├── jira_client.py      # Jira REST API v2
├── bitbucket_client.py # Bitbucket Cloud & Server REST API
├── git_manager.py      # git via subprocess (no gitpython)
├── config_patcher.py   # JSON deep-merge & write-back
└── .env.example        # All required environment variables
```

## Setup

### 1. Install dependencies

```bash
pip install requests
```

That's it — everything else is Python stdlib.

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
source .env
```

### 3. Clone your target repository locally

```bash
git clone git@bitbucket.org:workspace/your-repo.git /path/to/local/repo
```

Make sure the git remote is configured with credentials (SSH key or HTTPS with credential helper).

### 4. Run

```bash
python agent.py PROJ-123
```

## How GigaChat edits the config

The agent sends the **full current config file** + the **Jira task description** to GigaChat and asks it to return **only a JSON patch object** — the keys that need to be added or changed. Example:

Jira description:
> Set the connection pool size to 20 and enable the new feature flag `use_v2_api`.

GigaChat response:
```json
{"db": {"pool_size": 20}, "features": {"use_v2_api": true}}
```

This patch is deep-merged into the existing config. Only specified keys are changed; everything else is preserved.

## Bitbucket: Cloud vs Server

| Variable                      | Cloud                                 | Server/DC                             |
|-------------------------------|---------------------------------------|---------------------------------------|
| `BITBUCKET_BASE_URL`          | `https://api.bitbucket.org/2.0`       | `https://bb.company.com/rest/api/1.0` |
| `BITBUCKET_WORKSPACE`         | workspace slug                        | project key (e.g. `OPS`)              |
| `BITBUCKET_APP_PASSWORD`      | App password                          | Personal access token                 |