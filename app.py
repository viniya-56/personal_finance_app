import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ---------------- CONFIG ----------------
CATEGORIES = [
    "Food", "Transport", "Rent", "Utilities", "Trips",
    "Shopping", "Entertainment", "Healthcare",
    "Recharge", "Home Expenses", "Others"
]

TRANSACTIONS_SHEET = "Transactions"
BUDGETS_SHEET = "Budgets"

# ---------------- AUTH ----------------
def get_sheets_service():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

SHEET_ID = st.secrets["sheets"]["spreadsheet_id"]

# ---------------- DATA HELPERS ----------------
def read_sheet(sheet_name):
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=sheet_name
    ).execute()

    values = result.get("values", [])
    if len(values) < 2:
        return pd.DataFrame(columns=values[0] if values else [])

    return pd.DataFrame(values[1:], columns=values[0])

def write_sheet(sheet_name, df):
    service = get_sheets_service()
    body = {
        "values": [df.columns.tolist()] + df.astype(str).fillna("").values.tolist()
    }
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body=body
    ).execute()

# ---------------- TRANSACTIONS ----------------
def load_transactions():
    df = read_sheet(TRANSACTIONS_SHEET)
    if not df.empty:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    return df

def save_transaction(date, amount, category, description, mode):
    df = load_transactions()
    new_row = {
        "Date": date.strftime("%d/%m/%Y"),
        "Amount": amount,
        "Category": category,
        "Description": description,
        "Mode": mode
    }
    df = pd.concat([pd.DataFrame([new_row]), df], ignore_index=True)
    write_sheet(TRANSACTIONS_SHEET, df)

# ---------------- BUDGETS ----------------
def load_budgets():
    df = read_sheet(BUDGETS_SHEET)
    if not df.empty:
        df["Budget"] = pd.to_numeric(df["Budget"], errors="coerce")
    return df

def save_budget(month, category, budget):
    df = load_budgets()
    df = df[~((df["Month"] == month) & (df["Category"] == category))]
    df = pd.concat([df, pd.DataFrame([[month, category, budget]], columns=df.columns)])
    write_sheet(BUDGETS_SHEET, df)

# ---------------- UI ----------------
st.set_page_config("💰 Personal Finance", layout="wide")
st.title("💰 Personal Finance Tracker")

menu = st.sidebar.radio(
    "Menu",
    ["Add Transaction", "View Transactions", "Category Summary", "Budgets"]
)

# -------- ADD TRANSACTION --------
if menu == "Add Transaction":
    with st.form("add_tx"):
        date = st.date_input("Date", datetime.today())
        amount = st.number_input("Amount", min_value=1.0)
        category = st.selectbox("Category", CATEGORIES)
        description = st.text_input("Description")
        mode = st.selectbox("Payment Mode", ["UPI", "Cash", "Card", "Bank"])
        if st.form_submit_button("Save"):
            save_transaction(date, amount, category, description, mode)
            st.success("Transaction saved!")

# -------- VIEW TRANSACTIONS --------
elif menu == "View Transactions":
    df = load_transactions()
    st.dataframe(df, use_container_width=True)

# -------- CATEGORY SUMMARY --------
elif menu == "Category Summary":
    df = load_transactions()
    if not df.empty:
        summary = df.groupby("Category")["Amount"].sum().reset_index()
        st.bar_chart(summary.set_index("Category"))

# -------- BUDGETS --------
elif menu == "Budgets":
    month = st.text_input("Month (YYYY-MM)", datetime.today().strftime("%Y-%m"))
    category = st.selectbox("Category", CATEGORIES)
    budget = st.number_input("Budget", min_value=0.0)

    if st.button("Save Budget"):
        save_budget(month, category, budget)
        st.success("Budget saved")

    st.dataframe(load_budgets())
