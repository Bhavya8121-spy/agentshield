import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.dataset import Dataset
from app.core.exceptions import DatasetNotFound


class SessionStore:
    """In-memory, TTL + LRU bounded dataset store. Nothing is persisted to disk."""

    def __init__(self, ttl_minutes: int | None = None, max_items: int | None = None):
        self._items: OrderedDict[str, Dataset] = OrderedDict()
        self._ttl = timedelta(minutes=ttl_minutes or settings.session_ttl_minutes)
        self._max = max_items or settings.max_sessions
        self._lock = threading.Lock()

    def put(self, dataset: Dataset) -> Dataset:
        with self._lock:
            self._evict()
            self._items[dataset.dataset_id] = dataset
            self._items.move_to_end(dataset.dataset_id)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return dataset

    def get(self, dataset_id: str) -> Dataset:
        with self._lock:
            self._evict()
            ds = self._items.get(dataset_id)
            if ds is None:
                raise DatasetNotFound(
                    "Dataset not found or expired. Please re-upload your statement.",
                    {"dataset_id": dataset_id},
                )
            self._items.move_to_end(dataset_id)
            return ds

    def delete(self, dataset_id: str) -> None:
        with self._lock:
            self._items.pop(dataset_id, None)

    def _evict(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._ttl
        for key in [k for k, v in self._items.items() if v.created_at < cutoff]:
            self._items.pop(key, None)

    def __len__(self) -> int:
        return len(self._items)


store = SessionStore()