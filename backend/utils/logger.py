import json
import logging
import os
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


_LOCK = threading.Lock()
_SESSION_ID = os.getenv("RUN_SESSION_ID", uuid.uuid4().hex[:12])
_TOTAL_WRITTEN = 0
_LAST_SEQ = 0
_TYPE_COUNTS = {}


def _default_log_path():
    env_path = os.getenv("ACTION_LOG_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[1] / "store" / "actions.jsonl"


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class EventBuffer(list):
    """
    Bounded in-memory event buffer with append-only JSONL persistence.
    Every append is enriched with seq/timestamps/session metadata.
    """

    def __init__(self, max_items=5000, log_path=None, initial=None):
        super().__init__()
        self.max_items = max(200, int(max_items))
        self.log_path = Path(log_path or _default_log_path())
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if initial:
            for item in initial:
                self.append(item)

    def _enrich_event(self, event):
        global _LAST_SEQ
        now = datetime.now(timezone.utc)
        with _LOCK:
            _LAST_SEQ += 1
            seq = _LAST_SEQ
        base = event if isinstance(event, dict) else {"type": "raw_event", "value": str(event)}
        enriched = dict(base)
        enriched.setdefault("type", "event")
        enriched["_seq"] = seq
        enriched["_session"] = _SESSION_ID
        enriched["_ts"] = now.isoformat()
        enriched["_ts_epoch"] = round(now.timestamp(), 6)
        return enriched

    def _persist(self, event):
        global _TOTAL_WRITTEN
        line = json.dumps(event, ensure_ascii=True) + "\n"
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception:
            return
        with _LOCK:
            _TOTAL_WRITTEN += 1
            event_type = str(event.get("type", "event"))
            _TYPE_COUNTS[event_type] = _TYPE_COUNTS.get(event_type, 0) + 1

    def append(self, event):
        enriched = self._enrich_event(event)
        super().append(enriched)
        if len(self) > self.max_items:
            overflow = len(self) - self.max_items
            del self[:overflow]
        self._persist(enriched)

    def extend(self, iterable):
        for item in iterable:
            self.append(item)


def create_event_buffer(initial=None):
    max_items = int(os.getenv("EVENT_BUFFER_MAX", "6000"))
    return EventBuffer(max_items=max_items, initial=initial)


def get_logger(name):
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    return logging.getLogger(name)


def log_event(message):
    return {"logged": True, "message": message, "session": _SESSION_ID}


def get_action_log_stats(memory_events=0):
    log_path = _default_log_path()
    exists = log_path.exists()
    return {
        "session_id": _SESSION_ID,
        "path": str(log_path),
        "exists": exists,
        "size_bytes": log_path.stat().st_size if exists else 0,
        "total_written": _TOTAL_WRITTEN,
        "last_seq": _LAST_SEQ,
        "memory_events": int(memory_events),
        "event_type_counts": dict(sorted(_TYPE_COUNTS.items(), key=lambda item: item[0])),
    }


def read_action_logs(limit=200, after_seq=None):
    """
    Read recent persisted action logs from JSONL.
    """
    log_path = _default_log_path()
    if not log_path.exists():
        return []

    limit = max(1, min(int(limit), 2000))
    after = None
    if after_seq is not None:
        try:
            after = int(after_seq)
        except (TypeError, ValueError):
            after = None

    if after is None:
        tail = deque(maxlen=limit)
        with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    tail.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return list(tail)

    # Incremental fetch from disk: scan and keep only new rows.
    rows = []
    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            seq = int(item.get("_seq", 0))
            if seq > after:
                rows.append(item)
    if len(rows) > limit:
        rows = rows[-limit:]
    return rows
