import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# =============================
# CONFIG
# =============================
st.set_page_config(page_title="💰 Personal Budget Tracker", layout="wide")

CATEGORIES = [
    "Food", "Transport", "Rent", "Utilities", "Trips", "Clothes",
    "Books", "Shopping", "DMart Shopping", "Electricity Bill",
    "Train Tickets", "Entertainment", "Healthcare", "Recharge",
    "Food Related", "Home expenses", "Others"
]

SPREADSHEET_ID = "1qWYggVhlSYx-EtHhLGPucOeUCBJugHdujczubtFff58"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# =============================
# GOOGLE SHEETS SERVICE
# =============================
def get_sheets_service():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)

# =============================
# DATA FUNCTIONS
# =============================
def load_transactions():
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="Transactions"
    ).execute()

    values = result.get("values", [])
    if len(values) < 2:
        return pd.DataFrame(columns=["Date", "Amount", "Category", "Description", "Mode"])

    df = pd.DataFrame(values[1:], columns=values[0])
    df["Amount"] = df["Amount"].astype(float)
    return df

def save_transaction(date, amount, category, description, mode):
    service = get_sheets_service()
    row = [[date, amount, category, description, mode]]

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Transactions!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": row}
    ).execute()

def load_budgets():
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="Budgets"
    ).execute()

    values = result.get("values", [])
    if len(values) < 2:
        return pd.DataFrame(columns=["Month", "Category", "Budget"])

    df = pd.DataFrame(values[1:], columns=values[0])
    df["Budget"] = df["Budget"].astype(float)
    return df

def save_budget(month, category, budget):
    df = load_budgets()
    df = df[~((df["Month"] == month) & (df["Category"] == category))]
    df = pd.concat(
        [df, pd.DataFrame([[month, category, budget]], columns=df.columns)],
        ignore_index=True
    )

    service = get_sheets_service()
    values = [df.columns.tolist()] + df.astype(str).values.tolist()

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="Budgets!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

def calculate_remaining(month, transactions, budgets):
    transactions["Date_dt"] = pd.to_datetime(transactions["Date"], dayfirst=True)
    transactions["Month"] = transactions["Date_dt"].dt.to_period("M").astype(str)
    month_tx = transactions[transactions["Month"] == month]

    spent = (
        month_tx.groupby("Category")["Amount"]
        .sum()
        .reset_index()
        .rename(columns={"Amount": "Spent"})
    )

    month_budgets = budgets[budgets["Month"] == month]
    summary = pd.merge(month_budgets, spent, on="Category", how="left").fillna(0)
    summary["Remaining"] = summary["Budget"] - summary["Spent"]
    return summary

# =============================
# UI
# =============================
st.title("💰 Personal Budget Tracker")

menu = st.sidebar.radio(
    "Navigate",
    [
        "Add Transaction",
        "View Transactions",
        "Category Totals",
        "Date Range Report",
        "Set Budgets",
        "Summary"
    ]
)

# =============================
# ADD TRANSACTION
# =============================
if menu == "Add Transaction":
    st.header("➕ Add a New Transaction")

    with st.form("transaction_form", clear_on_submit=True):
        date = st.date_input("Date", datetime.today()).strftime("%d/%m/%Y")
        amount = st.number_input("Amount (Rs.)", min_value=1.0, step=0.5)
        category = st.selectbox("Category", CATEGORIES)
        description = st.text_input("Description")
        mode = st.selectbox("Payment Mode", ["UPI", "Cash", "Card", "Bank Transfer"])
        submitted = st.form_submit_button("Save Transaction")

        if submitted:
            save_transaction(date, amount, category, description, mode)
            st.success("✅ Transaction added successfully!")

# =============================
# VIEW TRANSACTIONS
# =============================
elif menu == "View Transactions":
    st.header("📜 All Transactions")
    df = load_transactions()

    if df.empty:
        st.warning("No transactions found.")
    else:
        st.dataframe(df, use_container_width=True)

        st.subheader("📈 Expense Trend")
        df["Date_dt"] = pd.to_datetime(df["Date"], dayfirst=True)
        daily = df.groupby("Date_dt")["Amount"].sum()
        st.line_chart(daily)

# =============================
# CATEGORY TOTALS
# =============================
elif menu == "Category Totals":
    st.header("📊 Expenses by Category")
    df = load_transactions()

    if df.empty:
        st.warning("No transactions found.")
    else:
        totals = df.groupby("Category")["Amount"].sum().sort_values(ascending=False)
        st.dataframe(totals.reset_index(), use_container_width=True)

        fig, ax = plt.subplots()
        ax.pie(totals, labels=totals.index, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
        st.pyplot(fig)

# =============================
# DATE RANGE REPORT
# =============================
elif menu == "Date Range Report":
    st.header("📅 Expenses Between Dates")
    df = load_transactions()

    if df.empty:
        st.warning("No transactions found.")
    else:
        df["Date_dt"] = pd.to_datetime(df["Date"], dayfirst=True)

        start_date = st.date_input("Start Date", df["Date_dt"].min().date())
        end_date = st.date_input("End Date", df["Date_dt"].max().date())
        category_filter = st.selectbox("Category (optional)", ["All"] + CATEGORIES)

        mask = (df["Date_dt"].dt.date >= start_date) & (df["Date_dt"].dt.date <= end_date)
        filtered = df[mask]

        if category_filter != "All":
            filtered = filtered[filtered["Category"] == category_filter]

        filtered["Date"] = filtered["Date_dt"].dt.strftime("%d/%m/%Y")
        st.dataframe(filtered.drop(columns=["Date_dt"]), use_container_width=True)
        st.success(f"Total Expenses: Rs. {filtered['Amount'].sum():,.2f}")

# =============================
# SET BUDGETS
# =============================
elif menu == "Set Budgets":
    st.header("💵 Set Monthly Budgets")

    month = st.text_input("Month (YYYY-MM)", datetime.today().strftime("%Y-%m"))
    category = st.selectbox("Category", CATEGORIES)
    budget = st.number_input("Budget Amount (Rs.)", min_value=0.0, step=500.0)

    if st.button("Save Budget"):
        save_budget(month, category, budget)
        st.success("✅ Budget saved")

    st.subheader("📜 All Budgets")
    st.dataframe(load_budgets(), use_container_width=True)

# =============================
# SUMMARY
# =============================
elif menu == "Summary":
    st.header("📊 Monthly Summary")

    df = load_transactions()
    budgets = load_budgets()
    month = st.text_input("Enter Month (YYYY-MM)", datetime.today().strftime("%Y-%m"))

    if st.button("Show Summary"):
        summary = calculate_remaining(month, df, budgets)

        if summary.empty:
            st.warning("No budgets found for this month.")
        else:
            st.dataframe(summary, use_container_width=True)
            st.subheader("📊 Remaining Budget")
            st.bar_chart(summary.set_index("Category")["Remaining"])
