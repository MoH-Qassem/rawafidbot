"""Idempotency key generation to prevent duplicate financial operations."""
import uuid
import hashlib


def generate_idempotency_key(*parts: str) -> str:
    """Generate a unique deterministic key from operation parts."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def generate_uuid() -> str:
    return str(uuid.uuid4())
