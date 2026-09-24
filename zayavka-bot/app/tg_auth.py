"""
Validates Telegram Mini App `initData` so the API can trust who is
submitting/reading data. See:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from app.config import BOT_TOKEN


def parse_and_validate_init_data(init_data: str, max_age_seconds: int = 86400):
    """
    Returns the parsed user dict on success, or None if invalid/missing.
    Does not raise — callers decide how strict to be.
    """
    if not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(pairs.items())
        )
        secret_key = hmac.new(
            key=b"WebAppData", msg=BOT_TOKEN.encode(), digestmod=hashlib.sha256
        ).digest()
        computed_hash = hmac.new(
            key=secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        # Reject stale (or future-dated) data, so a captured initData can't be
        # replayed later. Telegram signs auth_date when the Mini App is opened.
        auth_date = int(pairs.get("auth_date", "0"))
        now = time.time()
        if auth_date > now + 300 or now - auth_date > max_age_seconds:
            return None

        user_raw = pairs.get("user")
        user = json.loads(user_raw) if user_raw else {}
        return user
    except Exception:
        return None
