import logging
import time
import uuid
import requests

# Suppress the InsecureRequestWarning when verify=False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import GigaChatConfig

log = logging.getLogger("gigachat")


class GigaChatClient:
    def __init__(self, cfg: GigaChatConfig):
        self.cfg = cfg
        self._token: str = ""
        self._token_expires_at: float = 0.0

    def _ssl_verify(self):
        """
        Return the correct value for requests' `verify` parameter:
          - a CA bundle path (str) if provided
          - True / False (bool) based on config
        Never returns an empty string (which requests treats as an invalid path).
        """
        if self.cfg.ca_bundle:
            return self.cfg.ca_bundle   # path to .pem file
        return self.cfg.verify_ssl      # bool True or False

    #  Auth 

    def _get_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        log.info("Requesting new GigaChat token...")
        resp = requests.post(
            self.cfg.auth_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": f"Basic {self._basic_credentials()}",
            },
            data={"scope": self.cfg.scope},
            verify=self.cfg.verify_ssl if self.cfg.verify_ssl else False,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # GigaChat returns expires_at in milliseconds
        self._token_expires_at = data.get("expires_at", 0) / 1000 or (
            time.time() + 1800
        )
        log.info("GigaChat token refreshed, expires at %s", self._token_expires_at)
        return self._token

    def _basic_credentials(self) -> str:
        import base64
        raw = f"{self.cfg.client_id}:{self.cfg.client_secret}"
        return base64.b64encode(raw.encode()).decode()

    #  Chat 

    def chat(self, user_message: str, system_message: str = "") -> str:
        """Send a single-turn message and return the assistant text."""
        token = self._get_token()

        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 8192
        }

        resp = requests.post(
            self.cfg.api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            verify=self._ssl_verify(),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip()