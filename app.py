import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ---------------- CONFIG ----------------
SPREADSHEET_ID = st.secrets["google_sheets"]["spreadsheet_id"]

TRANSACTION_SHEET = "transactions"
BUDGET_SHEET = "budgets"

CATEGORIES = [
    "Food", "Transport", "Rent", "Utilities", "Trips",
    "Shopping", "Entertainment", "Healthcare",
    "Recharge", "Home Expenses", "Others"
]

# ---------------- GOOGLE SHEETS SERVICE ----------------
def get_sheets_service():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

# ---------------- SHEET HELPERS ----------------
def read_sheet(sheet_name):
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=sheet_name
    ).execute()

    values = result.get("values", [])
    if len(values) < 2:
        return pd.DataFrame(columns=values[0] if values else [])

    return pd.DataFrame(values[1:], columns=values[0])

def append_row(sheet_name, row):
    service = get_sheets_service()
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=sheet_name,
        valueInputOption="USER_ENTERED",
        body={"values": [row]}
    ).execute()

def overwrite_sheet(sheet_name, df):
    service = get_sheets_service()
    body = {
        "values": [df.columns.tolist()] + df.astype(str).values.tolist()
    }
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=sheet_name,
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

# ---------------- DATA FUNCTIONS ----------------
def load_transactions():
    df = read_sheet(TRANSACTION_SHEET)
    if not df.empty:
        df["Amount"] = df["Amount"].astype(float)
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    return df

def save_transaction(date, amount, category, description, mode):
    append_row(
        TRANSACTION_SHEET,
        [
            date.strftime("%d/%m/%Y"),
            amount,
            category,
            description,
            mode
        ]
    )

def load_budgets():
    df = read_sheet(BUDGET_SHEET)
    if not df.empty:
        df["Budget"] = df["Budget"].astype(float)
    return df

def save_budget(month, category, budget):
    df = load_budgets()

    if df.empty:
        df = pd.DataFrame(columns=["Month", "Category", "Budget"])

    df = df[~((df["Month"] == month) & (df["Category"] == category))]
    df = pd.concat(
        [df, pd.DataFrame([[month, category, budget]], columns=df.columns)],
        ignore_index=True
    )
    overwrite_sheet(BUDGET_SHEET, df)

# ---------------- UI ----------------
st.set_page_config(page_title="💰 Personal Finance", layout="wide")
st.title("💰 Personal Finance Tracker")

menu = st.sidebar.radio(
    "Menu",
    ["Add Transaction", "View Transactions", "Category Summary", "Budgets"]
)

# -------- ADD TRANSACTION --------
if menu == "Add Transaction":
    st.header("➕ Add Transaction")

    with st.form("add_tx", clear_on_submit=True):
        date = st.date_input("Date", datetime.today())
        amount = st.number_input("Amount", min_value=1.0, step=1.0)
        category = st.selectbox("Category", CATEGORIES)
        description = st.text_input("Description")
        mode = st.selectbox("Payment Mode", ["UPI", "Cash", "Card", "Bank"])

        if st.form_submit_button("Save"):
            save_transaction(date, amount, category, description, mode)
            st.success("✅ Transaction saved")

# -------- VIEW TRANSACTIONS --------
elif menu == "View Transactions":
    st.header("📜 Transactions")
    df = load_transactions()

    st.dataframe(df, use_container_width=True)

    if not df.empty:
        daily = df.groupby("Date")["Amount"].sum().reset_index()
        fig = px.line(daily, x="Date", y="Amount", title="Daily Expenses")
        st.plotly_chart(fig, use_container_width=True)

# -------- CATEGORY SUMMARY --------
elif menu == "Category Summary":
    st.header("📊 Category Summary")
    df = load_transactions()

    if not df.empty:
        cat = df.groupby("Category")["Amount"].sum().reset_index()
        fig = px.pie(cat, names="Category", values="Amount", title="Expenses by Category")
        st.plotly_chart(fig, use_container_width=True)

# -------- BUDGETS --------
elif menu == "Budgets":
    st.header("💵 Budgets")

    month = st.text_input("Month (YYYY-MM)", datetime.today().strftime("%Y-%m"))
    category = st.selectbox("Category", CATEGORIES)
    budget = st.number_input("Budget Amount", min_value=0.0, step=500.0)

    if st.button("Save Budget"):
        save_budget(month, category, budget)
        st.success("✅ Budget saved")

    st.subheader("📋 All Budgets")
    st.dataframe(load_budgets(), use_container_width=True)
