"""身份与安全原语：PBKDF2 口令散列、会话令牌。标准库实现（零三方依赖内核纪律）。"""
import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 120_000


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, stored: str, salt_hex: str) -> bool:
    try:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS)
        return hmac.compare_digest(digest.hex(), stored)
    except ValueError:
        return False


def new_session_token() -> str:
    return secrets.token_hex(32)
