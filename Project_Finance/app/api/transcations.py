from __future__ import annotations

from fastapi import APIRouter, File, Query, UploadFile
from pydantic import BaseModel, Field

from app.analytics.events import track
from app.api.deps import DatasetDep, SessionDep, Timer
from app.categorization.classifier import categorize_frame, reset_engine
from app.categorization.feedback import record_correction
from app.categorization.rules import CATEGORY_NAMES
from app.core.dataset import Dataset, transactions_to_frame
from app.core.store import store
from app.ingestion.parser import parse_statement

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class CorrectionRequest(BaseModel):
    transaction_id: str
    category: str
    subcategory: str | None = None
    apply_to_merchant: bool = True


class BalanceRequest(BaseModel):
    liquid_savings: float = Field(ge=0)


@router.post("/upload", status_code=201)
async def upload(
    session: SessionDep,
    file: UploadFile = File(...),
    keep_duplicates: bool = Query(default=False),
):
    with Timer() as timer:
        payload = await file.read()
        transactions, report = parse_statement(
            payload, filename=file.filename or "upload.csv", keep_duplicates=keep_duplicates
        )
        frame = categorize_frame(transactions_to_frame(transactions))
        dataset = store.put(Dataset(df=frame, report=report))
        recurring = dataset.recurring()

    review_rate = float((frame["category"] == "Needs Review").mean())
    track("csv_uploaded", session, columns_strategy=report.detected_columns.strategy,
          duration_ms=timer.elapsed_ms)
    track("transactions_processed", session, transaction_count=len(frame),
          months_covered=report.months_covered, review_rate=round(review_rate, 4))
    track("recurring_detected", session, recurring_count=recurring.detected_count)

    return {
        "dataset_id": dataset.dataset_id,
        "session_id": session,
        "ingestion": report.model_dump(mode="json"),
        "counts": {
            "transactions": len(frame),
            "active": len(dataset.active),
            "needs_review": int((frame["category"] == "Needs Review").sum()),
            "review_rate": round(review_rate, 4),
        },
        "processing_ms": timer.elapsed_ms,
    }


@router.get("/{dataset_id}")
def list_transactions(
    dataset: DatasetDep,
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    category: str | None = None,
    needs_review: bool = False,
    search: str | None = None,
    sort: str = Query(default="date", pattern="^(date|amount|merchant|confidence)$"),
    descending: bool = True,
):
    frame = dataset.df
    if category:
        frame = frame[frame["category"] == category]
    if needs_review:
        frame = frame[frame["category"] == "Needs Review"]
    if search:
        needle = search.lower()
        frame = frame[
            frame["merchant"].str.lower().str.contains(needle, na=False)
            | frame["clean_description"].str.lower().str.contains(needle, na=False)
        ]

    total = len(frame)
    frame = frame.sort_values(sort, ascending=not descending).iloc[offset:offset + limit]
    records = frame.assign(date=frame["date"].dt.date.astype(str)).to_dict(orient="records")
    return {"total": total, "limit": limit, "offset": offset, "transactions": records}


@router.get("/{dataset_id}/summary")
def summary(dataset: DatasetDep):
    features = dataset.features()
    return {
        "dataset_id": dataset.dataset_id,
        "ingestion": dataset.report.model_dump(mode="json"),
        "features": features.to_dict(),
    }


@router.get("/{dataset_id}/categories")
def categories(dataset: DatasetDep):
    spend = dataset.spending
    total = float(spend["outflow"].sum())
    grouped = (
        spend.groupby("category")
        .agg(total=("outflow", "sum"), count=("outflow", "size"),
             average=("outflow", "mean"), confidence=("confidence", "mean"))
        .sort_values("total", ascending=False)
        .reset_index()
    )
    months = max(dataset.features().complete_months, 1)
    return {
        "total_outflow": round(total, 2),
        "available_categories": CATEGORY_NAMES,
        "categories": [
            {
                "category": row.category,
                "total": round(row.total, 2),
                "monthly_average": round(row.total / months, 2),
                "share": round(row.total / total, 4) if total else 0.0,
                "transactions": int(row.count),
                "average_transaction": round(row.average, 2),
                "mean_confidence": round(float(row.confidence), 3),
            }
            for row in grouped.itertuples(index=False)
        ],
    }


@router.get("/{dataset_id}/recurring")
def recurring(dataset: DatasetDep):
    return dataset.recurring().to_dict()


@router.post("/{dataset_id}/corrections")
def correct(dataset: DatasetDep, body: CorrectionRequest, session: SessionDep):
    row = dataset.df[dataset.df["transaction_id"] == body.transaction_id]
    if row.empty:
        from app.core.exceptions import ValidationFailure

        raise ValidationFailure("Transaction not found in this dataset.",
                                {"transaction_id": body.transaction_id})
    previous = row.iloc[0]

    record_correction(
        merchant=previous["merchant"] if body.apply_to_merchant else "",
        clean_description=previous["clean_description"],
        amount=float(previous["amount"]),
        predicted_category=str(previous["category"]),
        corrected_category=body.category,
        subcategory=body.subcategory,
    )
    reset_engine()
    updated = dataset.apply_correction(body.transaction_id, body.category, body.subcategory)
    track("category_corrected", session)

    return {
        "transaction_id": body.transaction_id,
        "previous_category": str(previous["category"]),
        "new_category": body.category,
        "merchant_rule_created": body.apply_to_merchant,
        "transaction": {
            **{k: (str(v) if k == "date" else v) for k, v in updated.to_dict().items()},
            "date": str(updated["date"].date()),
        },
    }


@router.put("/{dataset_id}/balance")
def set_balance(dataset: DatasetDep, body: BalanceRequest, session: SessionDep):
    dataset.liquid_savings_override = body.liquid_savings
    dataset.invalidate()
    track("balance_provided", session)
    return {"liquid_savings": body.liquid_savings, "features": dataset.features().to_dict()}


@router.delete("/{dataset_id}", status_code=204)
def delete(dataset_id: str):
    store.delete(dataset_id)