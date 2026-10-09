"""
Authentication and authorization guards for FastAPI.

Provides:
- ``verify_api_key_guard``: Validates incoming requests using the API key header.
"""
import logging
import secrets

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from wardogs_config import ENVIRONMENT_SETTINGS

logger = logging.getLogger("wardogs.security.guard")

_settings = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS
api_key_header = APIKeyHeader(name=_settings.API_KEY_NAME, auto_error=False)


async def verify_api_key_guard(
    api_key: str | None = Security(api_key_header),
) -> str:
    """
    FastAPI dependency validating access via Valid X-API-Key header.
    Raises HTTPException 403 when credential is not valid.
    """
    if api_key and secrets.compare_digest(api_key, _settings.API_KEY):
        return api_key

    raise HTTPException(status_code=403, detail="Could not validate credentials")
