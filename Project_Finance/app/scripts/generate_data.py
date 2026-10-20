#!/usr/bin/env python3
"""Synthetic household statement generator.

Produces labelled transactions so categorisation, recurring detection and
forecasting can be measured rather than asserted. Emits the ground-truth
category alongside each row for evaluation.
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

MERCHANT_TEMPLATES = {
    "Groceries": [("KROGER #{n}", 40, 180), ("PUBLIX SUPER MARKET {n}", 35, 150),
                  ("TRADER JOES #{n}", 25, 110), ("ALDI {n}", 20, 90)],
    "Dining": [("STARBUCKS STORE #{n}", 4, 12), ("SQ *CHIPOTLE {n}", 9, 22),
               ("DOORDASH*{n}", 18, 55), ("TST* LOCAL DINER", 15, 70)],
    "Fuel": [("SHELL OIL {n}", 30, 80), ("EXXONMOBIL {n}", 28, 75)],
    "Shopping": [("AMZN MKTP US*{n}", 12, 220), ("TARGET T-{n}", 20, 160),
                 ("WAL-MART #{n}", 15, 140), ("BEST BUY #{n}", 30, 400)],
    "Transportation": [("UBER TRIP {n}", 9, 40), ("LYFT RIDE {n}", 8, 38)],
    "Health": [("CVS/PHARMACY #{n}", 10, 90), ("WALGREENS #{n}", 8, 70)],
    "Entertainment": [("AMC ONLINE #{n}", 14, 45), ("STEAM GAMES {n}", 10, 60)],
    "Home/Garden": [("THE HOME DEPOT #{n}", 20, 260), ("LOWES #{n}", 18, 220)],
}

SUBSCRIPTIONS = [
    ("NETFLIX.COM", 22.99, "Subscriptions"), ("SPOTIFY USA", 11.99, "Subscriptions"),
    ("HULU 877-8244", 17.99, "Subscriptions"), ("APPLE.COM/BILL", 9.99, "Subscriptions"),
    ("ADOBE CREATIVE CLOUD", 54.99, "Subscriptions"), ("PLANET FITNESS", 24.99, "Fitness"),
]


def build_household(rng: random.Random, months: int, profile: str) -> tuple[list[dict], dict]:
    income = {"stable": rng.uniform(4200, 7200), "variable": rng.uniform(3200, 8500),
              "tight": rng.uniform(2600, 3800)}[profile]
    volatility = {"stable": 0.02, "variable": 0.30, "tight": 0.08}[profile]

    rent = round(income * rng.uniform(0.24, 0.33), -1)
    car_loan = round(rng.uniform(280, 520), 2) if rng.random() < 0.7 else 0.0
    student_loan = round(rng.uniform(150, 400), 2) if rng.random() < 0.5 else 0.0

    end = date.today().replace(day=28)
    start = (end - timedelta(days=int(months * 30.44))).replace(day=1)
    rows: list[dict] = []
    balance = rng.uniform(2000, 22000)

    def add(day: date, description: str, amount: float, category: str) -> None:
        nonlocal balance
        balance += amount
        rows.append({"Date": day.strftime("%m/%d/%Y"), "Description": description,
                     "Amount": f"{amount:.2f}", "Balance": f"{balance:.2f}",
                     "_truth_category": category})

    cursor = start
    while cursor <= end:
        month_start = cursor.replace(day=1)

        # Semi-monthly payroll
        for day_of_month in (1, 15):
            try:
                pay_date = month_start.replace(day=day_of_month)
            except ValueError:
                continue
            if start <= pay_date <= end:
                amount = income / 2 * rng.gauss(1.0, volatility)
                add(pay_date, f"DIRECT DEP PAYROLL ACME CORP {rng.randint(1000, 9999)}",
                    round(max(amount, 0), 2), "Income")

        # Fixed commitments with realistic day drift
        for offset, description, amount, category in [
            (rng.choice([0, 0, 1, 2]), f"CHECK #{rng.randint(1000, 1999)} PROPERTY MGMT", -rent, "Rent/Mortgage"),
            (4, "GEICO AUTO INSURANCE PMT", -round(rng.uniform(95, 210), 2), "Insurance"),
            (8, "NES ELECTRIC UTILITY", -round(rng.uniform(70, 240), 2), "Utilities"),
            (11, "VERIZON WIRELESS PMT", -round(rng.uniform(55, 145), 2), "Phone/Internet"),
        ]:
            day = month_start + timedelta(days=offset)
            if start <= day <= end:
                add(day, description, amount, category)

        if car_loan:
            day = month_start + timedelta(days=6)
            if start <= day <= end:
                add(day, "ACH DEBIT AUTO LOAN PAYMENT", -car_loan, "Loan Payment")
        if student_loan:
            day = month_start + timedelta(days=18)
            if start <= day <= end:
                add(day, "NELNET STUDENT LOAN PMT", -student_loan, "Loan Payment")

        for description, amount, category in SUBSCRIPTIONS:
            if rng.random() < 0.55:
                day = month_start + timedelta(days=rng.randint(2, 26))
                if start <= day <= end:
                    add(day, description, -amount, category)

        # Variable spending
        for _ in range(rng.randint(38, 78)):
            day = month_start + timedelta(days=rng.randint(0, 29))
            if not (start <= day <= end):
                continue
            category = rng.choices(list(MERCHANT_TEMPLATES),
                                   weights=[26, 24, 10, 16, 7, 6, 6, 5])[0]
            template, low, high = rng.choice(MERCHANT_TEMPLATES[category])
            description = template.format(n=rng.randint(100, 9999))
            add(day, description, -round(rng.uniform(low, high), 2), category)

        # Occasional shocks and outliers
        if rng.random() < 0.10:
            day = month_start + timedelta(days=rng.randint(0, 27))
            if start <= day <= end:
                add(day, "URGENT CARE CLINIC PAYMENT", -round(rng.uniform(400, 2600), 2), "Health")
        if rng.random() < 0.06:
            day = month_start + timedelta(days=rng.randint(0, 27))
            if start <= day <= end:
                add(day, f"BEST BUY #{rng.randint(100, 999)}", -round(rng.uniform(900, 2400), 2), "Shopping")

        cursor = (month_start + timedelta(days=32)).replace(day=1)

    rows.sort(key=lambda r: (r["Date"][6:], r["Date"][:2], r["Date"][3:5]))
    return rows, {"income": income, "rent": rent, "car_loan": car_loan,
                  "student_loan": student_loan, "profile": profile}


def write_csv(rows: list[dict], path: Path, include_truth: bool) -> None:
    fields = ["Date", "Description", "Amount", "Balance"] + (["_truth_category"] if include_truth else [])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic bank statements.")
    parser.add_argument("--households", type=int, default=25)
    parser.add_argument("--months", type=int, default=14)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--demo", type=Path, default=Path("frontend/demo.csv"))
    args = parser.parse_args()

    rng = random.Random(args.seed)
    total = 0
    for index in range(args.households):
        profile = ["stable", "variable", "tight"][index % 3]
        rows, meta = build_household(rng, args.months, profile)
        write_csv(rows, args.out / f"household_{index:03d}_{profile}.csv", include_truth=True)
        total += len(rows)
        if index == 0:
            write_csv(rows, args.demo, include_truth=False)   # demo has no labels
            print(f"Demo statement -> {args.demo}")

    print(f"Generated {args.households} households, {total:,} transactions -> {args.out}")


if __name__ == "__main__":
    main()