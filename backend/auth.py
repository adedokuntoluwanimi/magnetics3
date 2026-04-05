from __future__ import annotations

from functools import lru_cache

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _firebase_app() -> firebase_admin.App:
    # On Cloud Run, ADC (attached service account) is used automatically.
    # No credentials file needed.
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app()


def _get_firebase_app() -> firebase_admin.App:
    return _firebase_app()


def verify_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """FastAPI dependency that verifies a Firebase ID token.

    Returns the decoded token claims dict on success.
    Raises HTTP 401 on missing or invalid token.
    """
    _get_firebase_app()
    token = None
    if creds and creds.credentials:
        token = creds.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        decoded = firebase_auth.verify_id_token(token)
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication failed.")
    return decoded


# Convenience alias used in route Depends()
AuthUser = Depends(verify_token)
