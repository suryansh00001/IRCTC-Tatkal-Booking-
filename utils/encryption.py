# utils/encryption.py — AES-256 encryption for sensitive data

import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from utils.logger import get_logger

log = get_logger("Encryption")

def generate_key() -> str:
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key().decode()

def get_fernet(key: str = None) -> Fernet:
    """Get Fernet instance from key or env."""
    k = key or os.getenv("ENCRYPTION_KEY", "")
    if not k:
        # Generate ephemeral key for session
        k = Fernet.generate_key().decode()
        log.warning("No ENCRYPTION_KEY set — using ephemeral session key.")
    return Fernet(k.encode() if isinstance(k, str) else k)

def encrypt(data: str, key: str = None) -> str:
    """Encrypt a string and return base64 token."""
    f = get_fernet(key)
    return f.encrypt(data.encode()).decode()

def decrypt(token: str, key: str = None) -> str:
    """Decrypt a base64 token and return plaintext."""
    f = get_fernet(key)
    return f.decrypt(token.encode()).decode()

class SecureStore:
    """In-memory secure store for credentials during bot session."""
    def __init__(self):
        self._key = Fernet.generate_key()
        self._store = {}
        self._f = Fernet(self._key)

    def set(self, field: str, value: str):
        self._store[field] = self._f.encrypt(value.encode())

    def get(self, field: str) -> str:
        if field not in self._store:
            return ""
        return self._f.decrypt(self._store[field]).decode()

    def clear(self):
        self._store.clear()
        log.info("SecureStore cleared — all credentials wiped from memory.")

# Global secure store instance
secure_store = SecureStore()
