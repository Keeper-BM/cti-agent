import hashlib
import secrets


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024
    )
    return "scrypt$32768$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, cost, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or cost != "32768" or len(password) > 256:
            return False
        salt = bytes.fromhex(salt)
        if len(salt) != 16 or len(expected) != 128:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024
        )
        return secrets.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False
