"""
Security token utilities.

Provides HMAC-signed tokens for two purposes:
- ``generate_signed_payload_token`` / ``verify_signed_payload_token``: short-lived
  browser-flow state tokens (e.g. Steam OpenID callback round-trip).
- ``generate_secure_download_token`` / ``verify_secure_download_token``: stateless
  tamper-proof download links with expiry (e.g. CSV export).

All tokens are signed with the API_KEY from SecuritySettings. No JWT lib needed.
"""
import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from typing import Any

from wardogs_config import ENVIRONMENT_SETTINGS

logger = logging.getLogger("wardogs.security.tokens")


def generate_signed_payload_token(payload: dict[str, Any], expires_in_seconds: int = 300) -> str:
    """Generates a short-lived signed token for browser flow state."""
    token_payload = {**payload, "exp": int(time.time()) + expires_in_seconds}
    payload_bytes = json.dumps(token_payload, separators=(",", ":")).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    secret = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY.encode("utf-8")
    signature = hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{encoded_payload}.{encoded_signature}"


def verify_signed_payload_token(token: str) -> dict[str, Any] | None:
    """Returns a signed browser-flow payload when it is authentic and unexpired."""
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        secret = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY.encode("utf-8")
        expected_signature = hmac.new(
            secret, encoded_payload.encode("ascii"), hashlib.sha256
        ).digest()
        actual_signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        if not hmac.compare_digest(expected_signature, actual_signature):
            return None

        payload_bytes = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
            return None
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error):
        return None


def generate_secure_download_token(filename: str, expires_in_seconds: int = 1800) -> str:
    """Generates a stateless, tamper-proof HMAC-SHA256 download token for any file."""
    expires_at = int(time.time()) + expires_in_seconds
    message = f"{filename}:{expires_at}".encode()
    secret = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY.encode("utf-8")
    sig = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{sig}"


def verify_secure_download_token(filename: str, token: str) -> bool:
    """Verifies that an HMAC download token is authentic and unexpired."""
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False
        expires_at_str, sig = parts
        expires_at = int(expires_at_str)
        if time.time() > expires_at:
            return False
        message = f"{filename}:{expires_at}".encode()
        secret = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS.API_KEY.encode("utf-8")
        expected_sig = hmac.new(secret, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, sig)
    except Exception:
        logger.warning("Error verifying download token for %s", filename)
        return False
