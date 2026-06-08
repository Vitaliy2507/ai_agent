import logging
import requests

from config import JiraConfig

log = logging.getLogger("jira")


class JiraClient:
    def __init__(self, cfg: JiraConfig):
        self.cfg = cfg
        self._auth_header = f"Bearer {cfg.api_token}"

    def _headers(self) -> dict:
        return {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.cfg.base_url}/rest/api/2/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._url(path)
        log.info("→ %s %s", method.upper(), url)
        resp = requests.request(
            method,
            url,
            headers=self._headers(),
            timeout=30,
            verify=False,
            **kwargs,
        )
        log.info("← HTTP %s | body: %r", resp.status_code, resp.text[:300] or "<empty>")
        resp.raise_for_status()
        return resp

    #  Таски 

    def get_issue(self, issue_key: str) -> dict:
        resp = self._request("get", f"issue/{issue_key}")

        # Обработка пустого ответа
        if not resp.text.strip():
            raise ValueError(
                f"Jira returned HTTP {resp.status_code} but empty body for issue {issue_key}. "
                "Check that the issue key exists and the token has read permission."
            )

        issue = resp.json()

        raw_desc = issue["fields"].get("description")
        if isinstance(raw_desc, dict):
            issue["fields"]["description"] = _adf_to_text(raw_desc)
        elif raw_desc is None:
            issue["fields"]["description"] = ""

        log.info("Fetched Jira issue %s: %s", issue_key, issue["fields"]["summary"])
        return issue

    def add_comment(self, issue_key: str, text: str) -> dict:
        resp = self._request("post", f"issue/{issue_key}/comment", json={"body": text})
        log.info("Comment added to %s", issue_key)
        return resp.json() if resp.text.strip() else {}

    def transition_issue(self, issue_key: str, transition_name: str) -> None:
        resp = self._request("get", f"issue/{issue_key}/transitions")
        transitions = resp.json().get("transitions", [])
        match = next(
            (t for t in transitions if t["name"].lower() == transition_name.lower()),
            None,
        )
        if not match:
            available = [t["name"] for t in transitions]
            raise ValueError(
                f"Transition '{transition_name}' not found. Available: {available}"
            )
        self._request(
            "post",
            f"issue/{issue_key}/transitions",
            json={"transition": {"id": match["id"]}},
        )
        log.info("Issue %s transitioned to '%s'", issue_key, transition_name)


#  ADF → plain text helper (fallback)  

def _adf_to_text(node: dict) -> str:
    if node.get("type") == "text":
        return node.get("text", "")
    parts = []
    for child in node.get("content", []):
        parts.append(_adf_to_text(child))
    sep = "\n" if node.get("type") in ("paragraph", "heading", "listItem") else ""
    return sep.join(parts)