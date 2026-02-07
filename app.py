import streamlit as st
import pandas as pd
import uuid
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime

# ================= CONFIG =================
# ---------------- CONFIG ----------------
CATEGORIES = [
    "Food",
    "Transport",
    "Rent",
    "Electricity Bill",
    "Utilities",
    "Recharge",
    "Home Expenses",
    "Shopping",
    "Entertainment",
    "Healthcare",
    "Trips",
    "Others"
]

TRANSACTIONS_SHEET = "Transactions"
BUDGETS_SHEET = "Budgets"


SERVICE_ACCOUNT_INFO = st.secrets["gcp_service_account"]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ================= AUTH =================
creds = Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)
service = build("sheets", "v4", credentials=creds)

# ---------------- LOGIN ----------------
if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("🔐 Login")

    username = st.text_input("Enter username")

    if st.button("Login"):
        users = st.secrets["users"]
        if username in users:
            st.session_state.user = username
            st.session_state.sheet_id = users[username]
            st.success(f"Welcome, {username} 👋")
            st.rerun()
        else:
            st.error("User not found")

    st.stop()

SHEET_ID = st.session_state.sheet_id


# ================= SHEETS HELPERS =================
def read_sheet(sheet_name):
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=sheet_name
    ).execute()

    values = result.get("values", [])
    if not values:
        return pd.DataFrame()

    return pd.DataFrame(values[1:], columns=values[0])


def write_sheet(sheet_name, df):
    # 🔒 Ensure helper columns never get saved
    df = df.drop(columns=["Label", "Date_dt"], errors="ignore")

    body = {
        "values": [df.columns.tolist()] + df.astype(str).values.tolist()
    }

    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body=body
    ).execute()


# ================= DATA HELPERS =================
def load_transactions():
    df = read_sheet(TRANSACTIONS_SHEET)
    if df.empty:
        return df

    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    return df


def sort_latest_first(df):
    df["Date_dt"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.sort_values("Date_dt", ascending=False)
    return df.drop(columns=["Date_dt"])


# ================= CRUD OPERATIONS =================
def add_transaction(date, amount, category, description, mode):
    df = load_transactions()

    new_row = {
        "TransactionID": str(uuid.uuid4()),
        "Date": date.strftime("%d/%m/%Y"),
        "Amount": amount,
        "Category": category,
        "Description": description,
        "Mode": mode
    }

    df = pd.concat([pd.DataFrame([new_row]), df], ignore_index=True)
    df = sort_latest_first(df)

    write_sheet(TRANSACTIONS_SHEET, df)


def update_transaction(txn_id, date, amount, category, description, mode):
    df = load_transactions()

    df.loc[df["TransactionID"] == txn_id, [
        "Date", "Amount", "Category", "Description", "Mode"
    ]] = [
        date.strftime("%d/%m/%Y"),
        amount,
        category,
        description,
        mode
    ]

    df = sort_latest_first(df)
    write_sheet(TRANSACTIONS_SHEET, df)


def delete_transaction(txn_id):
    df = load_transactions()
    deleted_row = df[df["TransactionID"] == txn_id]

    st.session_state["last_deleted"] = deleted_row

    df = df[df["TransactionID"] != txn_id]
    write_sheet(TRANSACTIONS_SHEET, df)


def undo_delete():
    if "last_deleted" not in st.session_state:
        return

    df = load_transactions()
    df = pd.concat([st.session_state["last_deleted"], df], ignore_index=True)
    df = sort_latest_first(df)

    write_sheet(TRANSACTIONS_SHEET, df)
    del st.session_state["last_deleted"]


# ================= UI =================
st.title("💰 Personal Finance Tracker")

tab1, tab2 = st.tabs(["➕ Add / Edit Transaction", "📄 View Transactions"])

# ================= ADD / EDIT TAB =================
with tab1:
    df = load_transactions()

    st.subheader("Transaction Details")

    date = st.date_input("Date", datetime.today())
    amount = st.number_input("Amount", min_value=0.0, step=0.01)
    category = st.text_input("Category")
    description = st.text_input("Description")
    mode = st.selectbox("Mode", ["Cash", "UPI", "Card", "Bank Transfer"])

    txn_to_edit = None

    if not df.empty:
        df = sort_latest_first(df)

        # 🔹 Temporary label (never saved)
        df["Label"] = (
            df["Date"] + " | ₹" +
            df["Amount"].astype(str) + " | " +
            df["Category"]
        )

        selected = st.selectbox(
            "Edit existing transaction (optional)",
            ["New Transaction"] + df["Label"].tolist()
        )

        if selected != "New Transaction":
            txn_to_edit = df[df["Label"] == selected].iloc[0]

            date = datetime.strptime(txn_to_edit["Date"], "%d/%m/%Y")
            amount = txn_to_edit["Amount"]
            category = txn_to_edit["Category"]
            description = txn_to_edit["Description"]
            mode = txn_to_edit["Mode"]

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("💾 Save"):
            if txn_to_edit is None:
                add_transaction(date, amount, category, description, mode)
                st.success("Transaction added")
            else:
                update_transaction(
                    txn_to_edit["TransactionID"],
                    date, amount, category, description, mode
                )
                st.success("Transaction updated")
            st.rerun()

    with col2:
        if txn_to_edit is not None and st.button("🗑️ Delete"):
            delete_transaction(txn_to_edit["TransactionID"])
            st.warning("Transaction deleted")
            st.rerun()

    with col3:
        if "last_deleted" in st.session_state and st.button("↩️ Undo Delete"):
            undo_delete()
            st.success("Delete undone")
            st.rerun()


# ================= VIEW TAB =================
with tab2:
    st.subheader("All Transactions")

    df = load_transactions()

    if df.empty:
        st.info("No transactions yet.")
    else:
        df = sort_latest_first(df)

        st.dataframe(
            df.drop(columns=["TransactionID"], errors="ignore"),
            use_container_width=True
        )
