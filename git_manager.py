import logging
import subprocess
from pathlib import Path

log = logging.getLogger("git")


class GitManager:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        if not (self.repo_path / ".git").exists():
            raise FileNotFoundError(
                f"No .git directory found at {self.repo_path}. "
                "Make sure the repository is cloned first."
            )

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        cmd = ["git", *args]
        log.debug("git %s", " ".join(args))
        result = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (rc={result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return result

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def fetch(self, remote: str = "origin") -> None:
        self._run("fetch", remote)
        log.info("Fetched from %s", remote)

    def create_branch(
        self,
        branch_name: str,
        from_branch: str,
        remote: str = "origin",
    ) -> None:
        """Fetch latest, then create a new branch from the remote base branch."""
        log.info("Creating branch '%s' from '%s/%s'", branch_name, remote, from_branch)
        self.fetch(remote)
        self._run("checkout", f"{remote}/{from_branch}", "-B", from_branch)
        self._run("checkout", "-b", branch_name)
        log.info("Branch '%s' created", branch_name)

    def commit_all(self, message: str) -> None:
        self._run("add", "-A")
        status = self._run("status", "--porcelain")
        if not status.stdout.strip():
            log.warning("Nothing to commit — config file was not modified.")
            return
        self._run("commit", "-m", message)
        log.info("Committed: %s", message)

    def push(self, branch_name: str, remote: str = "origin") -> None:
        self._run("push", "--set-upstream", remote, branch_name)
        log.info("Pushed '%s' to '%s'", branch_name, remote)