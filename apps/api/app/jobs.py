import json
from typing import Any

from redis import Redis

from .config import get_settings

JOB_QUEUE = "video-ai:render-jobs"
DEAD_LETTER = "video-ai:render-dead-letter"


def enqueue(job: dict[str, Any]) -> bool:
    """Pushes a typed job for the worker; False means there is no queue and the caller must run it inline."""
    settings = get_settings()
    if not settings.redis_url:
        return False
    Redis.from_url(settings.redis_url).rpush(JOB_QUEUE, json.dumps(job))
    return True
