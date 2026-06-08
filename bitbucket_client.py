import base64
import logging
import requests

from config import BitbucketConfig

log = logging.getLogger("bitbucket")


class BitbucketClient:
    def __init__(self, cfg: BitbucketConfig):
        self.cfg = cfg
        raw = f"{cfg.username}:{cfg.app_password}"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()

    def _headers(self) -> dict:
        return {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _server_pr_url(self) -> str:
        return (
            f"{self.cfg.base_url}/projects/"
            f"{self.cfg.workspace}/repos/{self.cfg.repo_slug}/pull-requests"
        )

    def _create_pr_server(
        self, title: str, description: str, source_branch: str, destination_branch: str
    ) -> dict:
        payload = {
            "title": title,
            "description": description,
            "fromRef": {
                "id": f"refs/heads/{source_branch}",
                "repository": {
                    "slug": self.cfg.repo_slug,
                    "project": {"key": self.cfg.workspace},
                },
            },
            "toRef": {
                "id": f"refs/heads/{destination_branch}",
                "repository": {
                    "slug": self.cfg.repo_slug,
                    "project": {"key": self.cfg.workspace},
                },
            },
            "reviewers": [],
        }
        resp = requests.post(
            self._server_pr_url(),
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    #  Public API 

    def create_pull_request(
        self,
        title: str,
        description: str,
        source_branch: str,
        destination_branch: str,
    ) -> dict:
        pr = self._create_pr_server(title, description, source_branch, destination_branch)

        log.info(
            "Pull request created: %s → %s",
            source_branch,
            destination_branch,
        )
        return pr

    def list_pull_requests(self, state: str = "OPEN") -> list:
        """List PRs (Cloud only for now)."""
        resp = requests.get(
            self._cloud_pr_url(),
            headers=self._headers(),
            params={"state": state},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("values", [])
