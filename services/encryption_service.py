"""Key rotation service — shared by the API endpoint and startup auto-rotation."""

import binascii
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from db.database import get_engine, get_session, get_setting, set_setting
from db.models import TenantConfig
from lib.crypto import (
    CryptoAlgorithm,
    FIPS_ALLOWED,
    decrypt,
    encrypt,
    generate_key,
    load_key,
    save_key,
)

log = logging.getLogger(__name__)


def _sqlcipher_rekey(new_raw_key: bytes) -> None:
    """Issue PRAGMA rekey on one raw connection from the pool.

    Re-encrypts the entire SQLCipher database file with the new 32-byte key.
    Must be called after the new key file has been written (so subsequent
    creator-based connections use the new key) but before session.commit().
    """
    engine = get_engine()
    hex_key = binascii.hexlify(new_raw_key).decode()
    with engine.connect() as conn:
        conn.execute(text(f"PRAGMA rekey = \"x'{hex_key}'\""))
        conn.commit()


def _derive_new_sqlcipher_key(new_algorithm: str, new_key: bytes) -> bytes:
    """Derive the 32-byte SQLCipher key from newly generated key material."""
    import base64

    if new_algorithm == CryptoAlgorithm.FERNET:
        # Fernet key is 44 base64url chars encoding exactly 32 bytes total.
        decoded = base64.urlsafe_b64decode(new_key)  # 32 bytes
        return decoded[0:32]
    else:
        # aes256gcm and chacha20poly1305: raw 32 bytes
        return new_key[:32]


def rotate_key(new_algorithm: str) -> dict:
    """Re-encrypt all TenantConfig secrets with a freshly generated key.

    Also re-encrypts the SQLCipher database file via PRAGMA rekey so the
    full-database encryption key is rotated atomically alongside the column
    encryption key.

    Returns {"rotated": N, "algorithm": ..., "rotated_at": "..."}.
    Raises ValueError on validation failure, RuntimeError on partial failure.
    """
    valid = {CryptoAlgorithm.FERNET, CryptoAlgorithm.AES256GCM, CryptoAlgorithm.CHACHA20POLY1305}
    if new_algorithm not in valid:
        raise ValueError(f"Unknown algorithm: {new_algorithm!r}")

    fips_on = (get_setting("fips_mode") or "false") == "true"
    if fips_on and new_algorithm not in FIPS_ALLOWED:
        raise ValueError(
            f"Algorithm {new_algorithm!r} is not FIPS-compliant. "
            "Disable FIPS mode or choose fernet / aes256gcm."
        )

    current_algorithm = get_setting("encryption_algorithm") or CryptoAlgorithm.FERNET
    current_key = load_key(current_algorithm)

    with get_session() as session:
        rows = session.query(TenantConfig).all()

        # Decrypt everything first — abort entirely if any row fails
        plaintext_map: list[tuple[int, str]] = []
        for row in rows:
            pt = decrypt(row.client_secret_enc, current_algorithm, current_key)
            plaintext_map.append((row.id, pt))

        new_key = generate_key(new_algorithm)

        # Re-encrypt with the new key
        new_enc_map = [(rid, encrypt(pt, new_algorithm, new_key)) for rid, pt in plaintext_map]

        # Write new ciphertext to DB rows (flush, don't commit yet)
        enc_lookup = dict(new_enc_map)
        for row in rows:
            row.client_secret_enc = enc_lookup[row.id]
        session.flush()

        # Resolve the key file path (mirrors logic in lib/crypto.save_key)
        key_path = Path.home() / ".config" / "zs-config" / "secret.key"
        db_path_env = os.environ.get("ZSCALER_DB_PATH")
        if db_path_env:
            key_path = Path(db_path_env).parent / "secret.key"

        bak_path = key_path.with_suffix(".key.bak")
        if key_path.exists():
            shutil.copy2(key_path, bak_path)

        rekey_attempted = False
        try:
            # Write the new key file atomically
            save_key(new_key, new_algorithm)

            # Re-encrypt the SQLCipher DB file with the derived key.
            # This must happen after save_key() so that the creator callable
            # (which reads the key file) will use the new key on subsequent
            # connections. PRAGMA rekey is issued before session.commit().
            new_sqlcipher_key = _derive_new_sqlcipher_key(new_algorithm, new_key)
            _sqlcipher_rekey(new_sqlcipher_key)
            rekey_attempted = True

            # Commit the column re-encryption changes
            session.commit()
        except Exception:
            if not rekey_attempted:
                # rekey hasn't run yet — restore the old key file and roll back
                if bak_path.exists():
                    os.replace(bak_path, key_path)
                session.rollback()
                raise RuntimeError(
                    "Key file replaced but SQLCipher rekey failed — old key restored from backup. "
                    "Re-run rotation."
                )
            else:
                # rekey succeeded but session.commit() failed.
                # The DB file is now encrypted with the new key.
                # The new key file is already in place.
                # Rolling back only undoes the column changes; re-run rotation to fix.
                session.rollback()
                raise RuntimeError(
                    "SQLCipher database re-encrypted with new key, but column commit failed. "
                    "Key file and DB encryption are consistent. Re-run rotation to re-encrypt columns."
                )
        finally:
            if bak_path.exists():
                bak_path.unlink(missing_ok=True)

    # Drain the connection pool so subsequent connections use the new key
    get_engine().dispose()

    rotated_at = datetime.utcnow().isoformat()
    set_setting("encryption_algorithm", new_algorithm)
    set_setting("key_last_rotated_at", rotated_at)

    return {"rotated": len(new_enc_map), "algorithm": new_algorithm, "rotated_at": rotated_at}


def rotate_key_if_due() -> None:
    """Called at startup — rotate if auto-rotation interval has elapsed."""
    try:
        interval = int(get_setting("key_rotation_interval_days") or "0")
        if interval == 0:
            return

        last_str = get_setting("key_last_rotated_at") or ""
        if last_str:
            last_dt = datetime.fromisoformat(last_str)
            if datetime.utcnow() - last_dt < timedelta(days=interval):
                return

        algorithm = get_setting("encryption_algorithm") or CryptoAlgorithm.FERNET
        result = rotate_key(algorithm)
        log.info(
            "Auto key rotation: rotated %d secrets, algorithm=%s, at=%s",
            result["rotated"],
            result["algorithm"],
            result["rotated_at"],
        )
    except Exception as exc:
        log.error("Auto key rotation failed: %s — server will continue to start.", exc)
