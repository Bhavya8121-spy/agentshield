from flask import Flask, render_template, request
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from datetime import datetime

app = Flask(__name__)

GOAL_NAME = "Tesla Model 3"
TARGET_PRICE = 35000
TARGET_MONTHLY_PAYMENT = 600
MANUAL_DEBT = 0

def get_image_base64(fig):
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    data = base64.b64encode(buf.getbuffer()).decode("ascii")
    plt.close(fig)
    return f"data:image/png;base64,{data}"

def classify_transaction(desc, debit):
    desc = str(desc).upper()
    debit = float(debit)
    if debit == 0: 
        return "Income", "Income"
    if "CHECK" in desc: 
        return "Rent/Mortgage", "Fixed"
    if "LOAN" in desc or "INSURANCE" in desc: 
        return "Loans/Insurance", "Fixed"
    if "POS" in desc or "PURCHASE" in desc: 
        return "Daily Spending", "Variable"
    if "ATM" in desc: 
        return "Cash Withdrawal", "Variable"
    if "SERVICE CHARGE" in desc or "FEE" in desc: 
        return "Bank Fees", "Variable"
    return "Uncategorized", "Variable"

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files["file"]
        if file:
            try:
                df = pd.read_csv(file, skipinitialspace=True)
                df.columns = df.columns.str.strip()
                
                for col in ["Debit", "Credit"]:
                    df[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0)
                
                # FIXED: Detect year from data, don't hard-code 2025
                if "Date" in df.columns:
                    df["Date"] = pd.to_datetime(df["Date"].astype(str), format="%m/%d/%Y", errors="coerce")
                    # If all dates are missing year, infer it
                    if df["Date"].isna().all():
                        current_year = datetime.now().year
                        df["Date"] = pd.to_datetime(df["Date"].astype(str) + f"/{current_year}", format="%m/%d/%Y", errors="coerce")
                
                df[["Category", "Type"]] = df.apply(
                    lambda x: pd.Series(classify_transaction(x.get("Description", ""), x.get("Debit", 0))), axis=1
                )
                
                # Metrics
                months_active = max((df["Date"].max() - df["Date"].min()).days / 30.0, 1.0)
                total_in = df["Credit"].sum()
                total_out = df["Debit"].sum()
                monthly_income = total_in / months_active
                monthly_out = total_out / months_active  # FIXED: monthly average, not total
                net_saved = monthly_income - monthly_out  # FIXED: monthly net, not total
                
                # DTI Logic
                fixed_cost = df[df["Type"] == "Fixed"]["Debit"].sum() / months_active
                total_debt = fixed_cost + MANUAL_DEBT + TARGET_MONTHLY_PAYMENT
                dti = (total_debt / monthly_income) * 100 if monthly_income > 0 else 0
                
                # Chart with rollover for >5 categories
                expenses = df[df["Debit"] > 0]
                cat_group = expenses.groupby("Category")["Debit"].sum().sort_values(ascending=False)
                
                # Keep top 5, sum rest as "Other"
                if len(cat_group) > 5:
                    top_5 = cat_group.head(5)
                    other = cat_group.iloc[5:].sum()
                    cat_group = pd.concat([top_5, pd.Series({"Other": other})])
                
                fig1, ax1 = plt.subplots(figsize=(7, 5))
                colors = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#845ef7']
                wedges, texts, autotexts = ax1.pie(
                    cat_group, labels=cat_group.index, autopct='%1.1f%%', 
                    startangle=90, colors=colors[:len(cat_group)], pctdistance=0.85
                )
                centre_circle = plt.Circle((0,0), 0.70, fc='white')
                fig1.gca().add_artist(centre_circle)
                
                img_pie = get_image_base64(fig1)
                
                return render_template("index.html", 
                                       report=True,
                                       total_in=total_in,
                                       total_out=total_out,
                                       net_saved=net_saved,
                                       monthly_income=monthly_income,
                                       monthly_out=monthly_out,
                                       dti=dti,
                                       goal_name=GOAL_NAME,
                                       img_pie=img_pie)
            except Exception as e:
                return render_template("index.html", report=False, error=str(e))
    
    return render_template("index.html", report=False)

if __name__ == "__main__":
    app.run(debug=True)