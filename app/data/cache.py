"""Small disk cache with a time-to-live. Stores only data this app fetched itself."""
import hashlib
import pickle
import time

from ..config import CACHE_DIR


def cached(key: str, ttl_seconds: float, fn):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".pkl")
    if path.exists() and time.time() - path.stat().st_mtime < ttl_seconds:
        try:
            return pickle.loads(path.read_bytes())
        except Exception:
            pass
    value = fn()
    try:
        path.write_bytes(pickle.dumps(value))
    except Exception:
        pass
    return value
