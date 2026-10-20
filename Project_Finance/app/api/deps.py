from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, Header, Request

from app.analytics.events import new_session_id
from app.core.dataset import Dataset
from app.core.store import store


def get_dataset(dataset_id: str) -> Dataset:
    return store.get(dataset_id)


DatasetDep = Annotated[Dataset, Depends(get_dataset)]


def get_session(x_session_id: str | None = Header(default=None)) -> str:
    return x_session_id or new_session_id()


SessionDep = Annotated[str, Depends(get_session)]


class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self.start) * 1000

    @property
    def elapsed_ms(self) -> float:
        return round(getattr(self, "ms", (time.perf_counter() - self.start) * 1000), 1)