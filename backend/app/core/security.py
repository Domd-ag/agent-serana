from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
from typing import Optional
from .config import get_settings

settings = get_settings()


def get_encryption_key() -> bytes:
    key = settings.ENCRYPTION_KEY.encode()
    if len(key) < 32:
        key = key.ljust(32, b'0')
    elif len(key) > 32:
        key = key[:32]
    return base64.urlsafe_b64encode(key)


_cipher: Optional[Fernet] = None


def get_cipher() -> Fernet:
    global _cipher
    if _cipher is None:
        key = get_encryption_key()
        _cipher = Fernet(key)
    return _cipher


def encrypt_data(data: str) -> str:
    cipher = get_cipher()
    encrypted = cipher.encrypt(data.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_data(encrypted_data: str) -> str:
    cipher = get_cipher()
    decoded = base64.urlsafe_b64decode(encrypted_data.encode())
    return cipher.decrypt(decoded).decode()
