import os
import secrets as _secrets_mod
import time
import bcrypt
from jose import jwt

_ALGORITHM = "HS256"
_ACCESS_TTL_DEFAULT = 300    # 5 minutes; not configurable via UI
_REFRESH_TTL_DEFAULT = 3600  # 60 minutes; configurable via admin settings

# Generated fresh on every container start. All refresh tokens signed with a
# previous nonce are rejected, preventing session re-use across restarts.
_STARTUP_NONCE = _secrets_mod.token_hex(16)


def _secret() -> str:
    return os.environ["JWT_SECRET"] + _STARTUP_NONCE


def _access_ttl() -> int:
    try:
        from db.database import get_setting
        v = get_setting("access_token_ttl")
        return int(v) if v else _ACCESS_TTL_DEFAULT
    except Exception:
        return _ACCESS_TTL_DEFAULT


def _refresh_ttl() -> int:
    try:
        from db.database import get_setting
        v = get_setting("refresh_token_ttl")
        return int(v) if v else _REFRESH_TTL_DEFAULT
    except Exception:
        return _REFRESH_TTL_DEFAULT


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    return bcrypt.checkpw(plaintext.encode(), hashed.encode())


def issue_access_token(user, *, mfa_enroll: bool = False) -> str:
    now = int(time.time())
    ttl = _access_ttl()
    payload: dict = {"sub": str(user.id), "username": user.username, "role": user.role,
                     "fpc": user.force_password_change, "iat": now, "exp": now + ttl}
    if mfa_enroll:
        payload["mfa_enroll"] = True
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def issue_refresh_token(user) -> str:
    now = int(time.time())
    ttl = _refresh_ttl()
    return jwt.encode(
        {"sub": str(user.id), "type": "refresh", "iat": now, "exp": now + ttl},
        _secret(), algorithm=_ALGORITHM,
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
