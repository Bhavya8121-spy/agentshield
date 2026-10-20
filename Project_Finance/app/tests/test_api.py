import pytest


# ------------------------------------------------------------------ meta
def test_health_endpoint(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert "version" in payload


def test_session_endpoint(client):
    assert len(client.get("/api/session").json()["session_id"]) == 16


def test_openapi_schema_generates(client):
    schema = client.get("/openapi.json").json()
    assert "/api/transactions/upload" in schema["paths"]
    assert "/api/simulation/{dataset_id}/monte-carlo" in schema["paths"]


# ------------------------------------------------------------- ingestion
def test_upload_returns_dataset(client, synthetic_csv):
    response = client.post("/api/transactions/upload",
                           files={"file": ("s.csv", synthetic_csv, "text/csv")})
    assert response.status_code == 201
    payload = response.json()
    assert payload["dataset_id"].startswith("ds_")
    assert payload["counts"]["transactions"] > 100
    assert payload["ingestion"]["detected_columns"]["strategy"] == "signed_amount"


def test_upload_garbage_returns_422_with_code(client):
    response = client.post("/api/transactions/upload",
                           files={"file": ("x.csv", b"not,a,statement\n1,2,3\n", "text/csv")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ingestion_error"


def test_unknown_dataset_returns_404(client):
    response = client.get("/api/transactions/ds_doesnotexist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dataset_not_found"


# ---------------------------------------------------------- transactions
def test_list_and_paginate(client, uploaded):
    first = client.get(f"/api/transactions/{uploaded}?limit=10&offset=0").json()
    second = client.get(f"/api/transactions/{uploaded}?limit=10&offset=10").json()
    assert len(first["transactions"]) == 10
    assert first["transactions"][0] != second["transactions"][0]
    assert first["total"] == second["total"]


def test_filter_needs_review(client, uploaded):
    payload = client.get(f"/api/transactions/{uploaded}?needs_review=true").json()
    assert all(t["category"] == "Needs Review" for t in payload["transactions"])


def test_search_filter(client, uploaded):
    payload = client.get(f"/api/transactions/{uploaded}?search=kroger").json()
    if payload["total"]:
        assert any("kroger" in t["merchant"].lower() or "kroger" in t["clean_description"].lower()
                   for t in payload["transactions"])


def test_categories_shares_sum_to_one(client, uploaded):
    payload = client.get(f"/api/transactions/{uploaded}/categories").json()
    assert sum(c["share"] for c in payload["categories"]) == pytest.approx(1.0, abs=0.01)
    assert payload["available_categories"]


def test_correction_updates_transaction_and_creates_rule(client, uploaded):
    listing = client.get(f"/api/transactions/{uploaded}?limit=1").json()
    transaction_id = listing["transactions"][0]["transaction_id"]

    response = client.post(f"/api/transactions/{uploaded}/corrections", json={
        "transaction_id": transaction_id, "category": "Travel", "apply_to_merchant": True})
    assert response.status_code == 200
    payload = response.json()
    assert payload["new_category"] == "Travel"
    assert payload["merchant_rule_created"]
    assert payload["transaction"]["confidence"] == 1.0
    assert payload["transaction"]["classifier"] == "user"


def test_correction_rejects_unknown_category(client, uploaded):
    listing = client.get(f"/api/transactions/{uploaded}?limit=1").json()
    response = client.post(f"/api/transactions/{uploaded}/corrections", json={
        "transaction_id": listing["transactions"][0]["transaction_id"],
        "category": "Cryptocurrency Moonshots"})
    assert response.status_code == 400


def test_correction_rejects_unknown_transaction(client, uploaded):
    response = client.post(f"/api/transactions/{uploaded}/corrections", json={
        "transaction_id": "txn_nope", "category": "Dining"})
    assert response.status_code == 400


def test_balance_override_changes_runway(client, uploaded):
    before = client.get(f"/api/insights/{uploaded}").json()["headline"]
    client.put(f"/api/transactions/{uploaded}/balance", json={"liquid_savings": 90_000})
    after = client.get(f"/api/insights/{uploaded}").json()["headline"]
    assert after["balance"] == 90_000
    assert after["runway_months"] > before["runway_months"]
    assert after["balance_source"] == "user_provided"


# ------------------------------------------------------------- analytics
def test_forecast_endpoint(client, uploaded):
    payload = client.get(f"/api/forecast/{uploaded}?days=30&days=90").json()
    assert set(payload["horizons"]) == {"30_day", "90_day"}
    assert payload["assumptions"]


def test_backtest_endpoint(client, uploaded):
    payload = client.get(f"/api/forecast/{uploaded}/backtest").json()
    assert "markdown" in payload
    assert payload["months_available"] > 0


def test_affordability_endpoint(client, uploaded):
    payload = client.post(f"/api/risk/{uploaded}/affordability", json={
        "loan_amount": 35_000, "down_payment": 5_000,
        "annual_rate_percent": 6.9, "term_months": 60, "goal_name": "Car"}).json()
    assert 0 <= payload["score"] <= 100
    assert payload["loan"]["monthly_payment"] > 0
    assert payload["explanation"]["factors"]


def test_affordability_rejects_negative_loan(client, uploaded):
    response = client.post(f"/api/risk/{uploaded}/affordability", json={"loan_amount": -5})
    assert response.status_code == 422


def test_health_endpoint_components(client, uploaded):
    payload = client.get(f"/api/risk/{uploaded}/health").json()
    assert len(payload["components"]) == 6
    assert payload["band"]


def test_monte_carlo_endpoint(client, uploaded):
    payload = client.post(f"/api/simulation/{uploaded}/monte-carlo",
                          json={"months": 12, "runs": 2_000}).json()
    assert payload["runs"] == 2_000
    assert len(payload["percentile_paths"]) == 12


def test_monte_carlo_run_cap_enforced(client, uploaded):
    response = client.post(f"/api/simulation/{uploaded}/monte-carlo",
                           json={"runs": 10_000_000})
    assert response.status_code == 422


def test_stress_presets_listed(client):
    keys = {p["key"] for p in client.get("/api/simulation/presets").json()["presets"]}
    assert "job_loss" in keys and "new_car" in keys


def test_stress_preset_endpoint(client, uploaded):
    payload = client.post(f"/api/simulation/{uploaded}/stress-test/preset/job_loss").json()
    assert payload["scenario"]["key"] == "job_loss"
    assert payload["monthly_path"]


def test_unknown_preset_rejected(client, uploaded):
    response = client.post(f"/api/simulation/{uploaded}/stress-test/preset/apocalypse")
    assert response.status_code == 400


def test_anomalies_endpoint(client, uploaded):
    payload = client.get(f"/api/anomalies/{uploaded}").json()
    assert "disclaimer" in payload
    assert "summary" in payload


def test_insights_aggregate(client, uploaded):
    payload = client.get(f"/api/insights/{uploaded}").json()
    for key in ("headline", "health", "forecast", "recurring", "insights"):
        assert key in payload
    assert payload["insights"]


def test_analytics_summary_has_no_transaction_data(client, uploaded):
    client.get(f"/api/forecast/{uploaded}")
    payload = client.get("/api/analytics/summary").json()
    text = str(payload).lower()
    for leak in ("kroger", "starbucks", "payroll", "description", "merchant_name"):
        assert leak not in text
    assert payload["usage"]["statements_analyzed"] >= 1


def test_delete_dataset(client, uploaded):
    assert client.delete(f"/api/transactions/{uploaded}").status_code == 204
    assert client.get(f"/api/transactions/{uploaded}").status_code == 404


def test_timing_header_present(client):
    assert "X-Process-Time-Ms" in client.get("/api/health").headers