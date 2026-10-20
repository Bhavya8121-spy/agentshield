from __future__ import annotations

import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.categorization.classifier import categorize_frame
from app.core.dataset import Dataset, transactions_to_frame
from app.forecasting.features import build_features
from app.ingestion.parser import parse_statement
from app.main import app
from app.recurring.detector import detect_recurring

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from generate_data import build_household, write_csv  # noqa: E402


@pytest.fixture(scope="session")
def synthetic_csv(tmp_path_factory) -> bytes:
    rows, _ = build_household(random.Random(11), months=14, profile="stable")
    path = tmp_path_factory.mktemp("data") / "household.csv"
    write_csv(rows, path, include_truth=False)
    return path.read_bytes()


@pytest.fixture
def parsed(synthetic_csv):
    return parse_statement(synthetic_csv, "household.csv")


@pytest.fixture
def frame(parsed):
    return categorize_frame(transactions_to_frame(parsed[0]))


@pytest.fixture
def dataset(frame, parsed) -> Dataset:
    return Dataset(df=frame, report=parsed[1])


@pytest.fixture
def active(dataset):
    return dataset.active


@pytest.fixture
def features(active):
    return build_features(active, detect_recurring(active))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "analytics_path", str(tmp_path / "events.jsonl"))
    monkeypatch.setattr(settings, "feedback_path", str(tmp_path / "corrections.jsonl"))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def uploaded(client, synthetic_csv):
    response = client.post(
        "/api/transactions/upload",
        files={"file": ("household.csv", synthetic_csv, "text/csv")},
    )
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]