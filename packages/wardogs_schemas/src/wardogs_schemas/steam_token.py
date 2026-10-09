import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any


def create_steam_link_token(
    discord_id: str,
    secret_key: str,
    guild_id: str | None = None,
    expires_in: int = 600,
    discord_username: str | None = None,
    discord_tag: str | None = None,
    discord_avatar: str | None = None,
    **extra
) -> str:
    """
    Genera un token seguro firmado con HMAC-SHA256 para el flujo de vinculación de Steam OpenID.
    Por defecto expira en 10 minutos (600 segundos).
    """
    payload: dict[str, Any] = {
        "purpose": "steam_link",
        "jti": secrets.token_urlsafe(32),
        "discord_id": str(discord_id),
        "guild_id": str(guild_id) if guild_id else None,
        "exp": int(time.time()) + expires_in
    }
    if discord_username:
        payload["discord_username"] = str(discord_username)
    if discord_tag:
        payload["discord_tag"] = str(discord_tag)
    if discord_avatar:
        payload["discord_avatar"] = str(discord_avatar)
    for k, v in extra.items():
        if v is not None:
            payload[k] = v
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode('ascii').rstrip('=')
    
    sig = hmac.new(secret_key.encode('utf-8'), payload_b64.encode('ascii'), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode('ascii').rstrip('=')
    
    return f"{payload_b64}.{sig_b64}"

def verify_steam_link_token(token: str, secret_key: str) -> dict[str, Any] | None:
    """
    Verifica la autenticidad y vigencia de un token de vinculación de Steam.
    Devuelve el payload con discord_id y guild_id si es válido, o None si expiró o fue alterado.
    """
    try:
        parts = token.split('.')
        if len(parts) != 2:
            return None
        payload_b64, sig_b64 = parts
        
        expected_sig = hmac.new(secret_key.encode('utf-8'), payload_b64.encode('ascii'), hashlib.sha256).digest()
        
        pad_sig = len(sig_b64) % 4
        sig_b64_padded = sig_b64 + ('=' * (4 - pad_sig) if pad_sig else '')
        actual_sig = base64.urlsafe_b64decode(sig_b64_padded)
        
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        
        pad_payload = len(payload_b64) % 4
        payload_b64_padded = payload_b64 + ('=' * (4 - pad_payload) if pad_payload else '')
        payload_bytes = base64.urlsafe_b64decode(payload_b64_padded)
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        if (not isinstance(payload, dict) or payload.get("purpose") != "steam_link"
                or not isinstance(payload.get("jti"), str) or len(payload["jti"]) < 32
                or not str(payload.get("discord_id", "")).isdigit()
                or payload.get("exp", 0) < time.time()):
            return None
            
        return payload
    except Exception:
        return None
