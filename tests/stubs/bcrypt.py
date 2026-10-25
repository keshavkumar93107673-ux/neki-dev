"""Test stand-in used ONLY if the real bcrypt is not installed in the sandbox (same API subset)."""
import hashlib, os, base64
def gensalt(rounds=12): return b"$2b$12$" + base64.b64encode(os.urandom(12))[:16]
def hashpw(pw, salt):
    if salt.startswith(b"$2b$12$") and len(salt) > 23: salt = salt[:23]
    return salt + hashlib.sha256(salt + pw).hexdigest().encode()
def checkpw(pw, hashed):
    return hashpw(pw, hashed[:23]) == hashed
