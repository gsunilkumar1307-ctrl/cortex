from __future__ import annotations

import hmac
import os
import secrets
import stat
from pathlib import Path
from fastapi import Request, HTTPException, status

SESSION_SECRET_ENV = "CORTEX_SESSION_SECRET"
_session_secret: str | None = None


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_or_create_session_secret() -> str:
    """
    Retrieve or initialize the cryptographic local session secret.
    The secret is stored in .session_secret with 0600 (user-only) permissions.
    """
    global _session_secret
    if _session_secret:
        return _session_secret

    env_val = os.getenv(SESSION_SECRET_ENV)
    if env_val and len(env_val.strip()) >= 32:
        _session_secret = env_val.strip()
        return _session_secret

    secret_file = get_project_root() / ".session_secret"
    if secret_file.exists():
        try:
            val = secret_file.read_text(encoding="utf-8").strip()
            if len(val) >= 32:
                _session_secret = val
                os.environ[SESSION_SECRET_ENV] = val
                return _session_secret
        except Exception:
            pass

    # Generate new cryptographically random 256-bit token
    new_secret = secrets.token_hex(32)
    try:
        secret_file.write_text(new_secret, encoding="utf-8")
        # Restrict permissions to owner-only read/write
        os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass

    _session_secret = new_secret
    os.environ[SESSION_SECRET_ENV] = new_secret
    return _session_secret


def verify_session_token(token: str | None) -> bool:
    """Verify session token using constant-time comparison."""
    if not token:
        return False
    expected = get_or_create_session_secret()
    return hmac.compare_digest(token.strip(), expected.strip())


async def require_session_auth(request: Request) -> str:
    """
    FastAPI dependency for protecting privileged endpoints.
    Allows public access to health and schema documentation.
    """
    path = request.url.path
    if path in {"/", "/health", "/ping", "/docs", "/openapi.json", "/redoc"}:
        return ""

    # Allow disabling in isolated local testing when explicitly configured via environment
    if os.getenv("CORTEX_DISABLE_AUTH", "0") == "1":
        return ""

    auth_header = request.headers.get("X-Cortex-Session")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing X-Cortex-Session token",
        )

    if not verify_session_token(auth_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid X-Cortex-Session token",
        )

    return auth_header
