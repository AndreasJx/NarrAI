import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings

SIGNATURE_BYTES = hashlib.sha256().digest_size

SCOPES = {
    "youtube": " ".join(
        [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ]
    ),
    "tiktok": "user.info.basic,video.list,video.upload,video.publish",
}
CONSOLES = {
    "youtube": "https://console.cloud.google.com/apis/credentials",
    "tiktok": "https://developers.tiktok.com/apps",
}


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str
    source: str  # "organization" or "env"


def env_client(settings: Settings, platform: str) -> OAuthClient | None:
    pairs = {
        "youtube": (settings.youtube_client_id, settings.youtube_client_secret),
        "tiktok": (settings.tiktok_client_key, settings.tiktok_client_secret),
    }
    client_id, client_secret = pairs.get(platform, (None, None))
    if client_id and client_secret:
        return OAuthClient(client_id, client_secret, "env")
    return None


class OAuthService:
    def __init__(self, settings: Settings):
        self.settings = settings
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.credential_secret.encode()).digest())
        self.cipher = Fernet(key)

    def redirect_uri(self, platform: str) -> str:
        return f"{self.settings.oauth_redirect_base.rstrip('/')}/{platform}"

    def _state(self, platform: str, organization_id: int, project_id: int | None = None) -> str:
        payload = json.dumps(
            {
                "platform": platform,
                "organization_id": organization_id,
                "project_id": project_id,
                "expires": int(time.time()) + 600,
            },
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(self.settings.credential_secret.encode(), payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + b"." + signature).decode()

    def verify_state(self, state: str, platform: str) -> tuple[int, int | None]:
        """Returns (organization_id, project_id); project_id is None when the login started in Settings."""
        try:
            raw = base64.urlsafe_b64decode(state.encode())
            # The binary signature may itself contain b".", so split at its fixed length instead of the separator.
            payload, separator, signature = raw[:-SIGNATURE_BYTES - 1], raw[-SIGNATURE_BYTES - 1 : -SIGNATURE_BYTES], raw[-SIGNATURE_BYTES:]
            if separator != b".":
                raise ValueError("malformed state")
            expected = hmac.new(self.settings.credential_secret.encode(), payload, hashlib.sha256).digest()
            data = json.loads(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid OAuth state") from exc
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid OAuth state signature")
        if data["platform"] != platform or int(data["expires"]) < int(time.time()):
            raise ValueError("Expired or mismatched OAuth state")
        project_id = data.get("project_id")
        return int(data["organization_id"]), int(project_id) if project_id is not None else None

    def authorization_url(self, platform: str, client: OAuthClient, organization_id: int, project_id: int | None = None) -> str:
        state = self._state(platform, organization_id, project_id)
        if platform == "youtube":
            params = {
                "client_id": client.client_id,
                "redirect_uri": self.redirect_uri(platform),
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "scope": SCOPES["youtube"],
                "state": state,
            }
            return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        if platform == "tiktok":
            params = {
                "client_key": client.client_id,
                "redirect_uri": self.redirect_uri(platform),
                "response_type": "code",
                "scope": SCOPES["tiktok"],
                "state": state,
            }
            return f"https://www.tiktok.com/v2/auth/authorize/?{urlencode(params)}"
        raise ValueError("Unsupported OAuth platform")

    def _token_request(self, platform: str, client: OAuthClient, grant: dict[str, str]) -> dict:
        if platform == "youtube":
            response = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={"client_id": client.client_id, "client_secret": client.client_secret, **grant},
                timeout=30,
            )
        elif platform == "tiktok":
            response = httpx.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={"client_key": client.client_id, "client_secret": client.client_secret, **grant},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
        else:
            raise ValueError("Unsupported OAuth platform")
        response.raise_for_status()
        return response.json()

    def exchange(self, platform: str, code: str, client: OAuthClient) -> dict:
        return self._token_request(
            platform,
            client,
            {"code": code, "grant_type": "authorization_code", "redirect_uri": self.redirect_uri(platform)},
        )

    def refresh(self, platform: str, refresh_token: str, client: OAuthClient) -> dict:
        return self._token_request(platform, client, {"refresh_token": refresh_token, "grant_type": "refresh_token"})

    def profile(self, platform: str, access_token: str) -> tuple[str | None, str]:
        """Best effort (external id, display name) of the authorized channel."""
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            if platform == "youtube":
                response = httpx.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "snippet", "mine": "true"},
                    headers=headers,
                    timeout=30,
                )
                response.raise_for_status()
                items = response.json().get("items") or []
                if items:
                    return items[0]["id"], items[0].get("snippet", {}).get("title", "")
            elif platform == "tiktok":
                response = httpx.get(
                    "https://open.tiktokapis.com/v2/user/info/",
                    params={"fields": "open_id,display_name"},
                    headers=headers,
                    timeout=30,
                )
                response.raise_for_status()
                user = response.json().get("data", {}).get("user", {})
                return user.get("open_id"), user.get("display_name", "")
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        return None, ""

    def encrypt(self, value: str) -> str:
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Stored credential cannot be decrypted") from exc
