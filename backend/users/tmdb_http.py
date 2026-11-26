"""
TMDB requests whose errors never carry the API key.

TMDB v3 takes the key in the query string (?api_key=...), and requests puts the full URL in its
error messages ("404 Client Error: Not Found for url: ...?api_key=..."). The jobs print those
messages, and they end up in the job logs, JobRun summaries (admin dashboard) and check-up emails.
"""
import re

import requests

_KEY_IN_URL = re.compile(r"(api_key=)[^&\s'\"]+")


def redact(text) -> str:
    """The text with any api_key=... value replaced by ***."""
    return _KEY_IN_URL.sub(r"\1***", str(text))


def get_json(session, url: str, params: dict, timeout, path: str) -> dict:
    """GET a TMDB URL; errors name the path and status only (same exception types as requests)."""
    try:
        r = session.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise requests.RequestException(f"{type(exc).__name__} for {path}: {redact(exc)}") from None
    if not r.ok:
        raise requests.HTTPError(f"{r.status_code} {r.reason} for {path}", response=r)
    return r.json()
