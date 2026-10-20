#!/usr/bin/env python3
"""Train the Tier-3 ML classifier on synthetic labels plus real user corrections."""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.categorization.classifier import build_model_frame
from app.categorization.feedback import training_examples
from app.ingestion.normalizer import clean_description, merchant_guess

NUMERIC = ["amount_abs", "amount_log", "is_round", "day_of_week", "day_of_month", "is_weekend"]


def load_labelled(directory: Path) -> pd.DataFrame:
    files = sorted(directory.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSVs in {directory}. Run scripts/generate_data.py first.")
    frames = [pd.read_csv(path) for path in files]
    data = pd.concat(frames, ignore_index=True)
    if "_truth_category" not in data:
        raise SystemExit("Training data must include a _truth_category column.")

    data["date"] = pd.to_datetime(data["Date"], format="%m/%d/%Y")
    data["amount"] = data["Amount"].astype(float)
    data["clean_description"] = data["Description"].map(clean_description)
    data["merchant"] = data["clean_description"].map(merchant_guess)
    data["category"] = data["_truth_category"]

    # Income is decided by sign, not by the model.
    return data[data["amount"] < 0].reset_index(drop=True)


def append_corrections(data: pd.DataFrame) -> pd.DataFrame:
    corrections = training_examples()
    if not corrections:
        return data
    extra = pd.DataFrame(corrections)
    extra["date"] = pd.Timestamp.today()
    extra["amount"] = -50.0
    print(f"Adding {len(extra)} user correction(s) to the training set.")
    # Upweight real corrections: they encode genuine misclassifications.
    return pd.concat([data] + [extra] * 3, ignore_index=True)


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("features", ColumnTransformer([
            ("text", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                     min_df=2, max_features=40_000, sublinear_tf=True), "text"),
            ("numeric", StandardScaler(), NUMERIC),
        ])),
        ("model", HistGradientBoostingClassifier(max_iter=300, learning_rate=0.12,
                                                 max_depth=None, random_state=7)),
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--out", type=Path, default=Path("app/categorization/model.joblib"))
    parser.add_argument("--test-size", type=float, default=0.2)
    args = parser.parse_args()

    data = append_corrections(load_labelled(args.data))
    keep = data["category"].value_counts()
    data = data[data["category"].isin(keep[keep >= 10].index)]

    features = build_model_frame(data)
    labels = data["category"]
    print(f"Training on {len(features):,} rows across {labels.nunique()} categories.")

    x_train, x_test, y_train, y_test = train_test_split(
        features, labels, test_size=args.test_size, stratify=labels, random_state=7
    )
    pipeline = build_pipeline().fit(x_train, y_train)
    predictions = pipeline.predict(x_test)

    macro = f1_score(y_test, predictions, average="macro")
    weighted = f1_score(y_test, predictions, average="weighted")
    print("\n" + classification_report(y_test, predictions, zero_division=0))
    print(f"Macro F1: {macro:.4f}   Weighted F1: {weighted:.4f}")
    print("\nNOTE: these figures are measured on synthetic data. Do not present them as "
          "real-world accuracy — report the dataset alongside the number.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, args.out)
    print(f"\nModel saved -> {args.out}")


if __name__ == "__main__":
    main()