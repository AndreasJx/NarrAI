import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings

SIGNATURE_BYTES = hashlib.sha256().digest_size


class OAuthService:
    def __init__(self, settings: Settings):
        self.settings = settings
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.credential_secret.encode()).digest())
        self.cipher = Fernet(key)

    def _state(self, platform: str, project_id: int) -> str:
        payload = json.dumps(
            {"platform": platform, "project_id": project_id, "expires": int(time.time()) + 600},
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(self.settings.credential_secret.encode(), payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + b"." + signature).decode()

    def verify_state(self, state: str, platform: str) -> int:
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
        return int(data["project_id"])

    def authorization_url(self, platform: str, project_id: int) -> str:
        state = self._state(platform, project_id)
        redirect_uri = f"{self.settings.oauth_redirect_base}/{platform}"
        if platform == "youtube":
            if not self.settings.youtube_client_id:
                raise ValueError("YouTube OAuth is not configured")
            params = {
                "client_id": self.settings.youtube_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/yt-analytics.readonly",
                "state": state,
            }
            return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        if platform == "tiktok":
            if not self.settings.tiktok_client_key:
                raise ValueError("TikTok OAuth is not configured")
            params = {
                "client_key": self.settings.tiktok_client_key,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "user.info.basic,video.list,video.upload,video.publish",
                "state": state,
            }
            return f"https://www.tiktok.com/v2/auth/authorize/?{urlencode(params)}"
        raise ValueError("Unsupported OAuth platform")

    def exchange(self, platform: str, code: str) -> dict[str, str]:
        redirect_uri = f"{self.settings.oauth_redirect_base}/{platform}"
        if platform == "youtube":
            response = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.settings.youtube_client_id,
                    "client_secret": self.settings.youtube_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                timeout=30,
            )
        elif platform == "tiktok":
            response = httpx.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key": self.settings.tiktok_client_key,
                    "client_secret": self.settings.tiktok_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
        else:
            raise ValueError("Unsupported OAuth platform")
        response.raise_for_status()
        return response.json()

    def encrypt(self, value: str) -> str:
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Stored credential cannot be decrypted") from exc
