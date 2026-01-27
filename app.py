import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ---------------- CONFIG ----------------
TRANSACTION_FILE = "transactions.csv"
BUDGET_FILE = "budgets.csv"

CATEGORIES = [
    "Food", "Transport", "Rent", "Utilities", "Trips",
    "Shopping", "Entertainment", "Healthcare",
    "Recharge", "Home Expenses", "Others"
]

# ---------------- GOOGLE DRIVE HELPERS ----------------
@st.cache_resource
def get_drive_service():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)


def get_file_id(filename):
    service = get_drive_service()
    folder_id = st.secrets["drive"]["folder_id"]

    query = (
        f"name='{filename}' and "
        f"'{folder_id}' in parents and trashed=false"
    )

    result = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    files = result.get("files", [])
    return files[0]["id"] if files else None


def load_csv(filename, columns):
    service = get_drive_service()
    folder_id = st.secrets["drive"]["folder_id"]
    file_id = get_file_id(filename)

    # If file does NOT exist → create it
    if not file_id:
        df = pd.DataFrame(columns=columns)
        buffer = io.BytesIO()
        df.to_csv(buffer, index=False)
        buffer.seek(0)

        service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=MediaIoBaseUpload(buffer, mimetype="text/csv"),
            supportsAllDrives=True
        ).execute()

        return df

    # If file exists → download it
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    fh.seek(0)
    return pd.read_csv(fh)


def save_csv(filename, df):
    service = get_drive_service()
    file_id = get_file_id(filename)

    buffer = io.BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)

    service.files().update(
        fileId=file_id,
        media_body=MediaIoBaseUpload(buffer, mimetype="text/csv"),
        supportsAllDrives=True
    ).execute()

# ---------------- DATA FUNCTIONS ----------------
def load_transactions():
    df = load_csv(
        TRANSACTION_FILE,
        ["Date", "Amount", "Category", "Description", "Mode"]
    )
    if not df.empty:
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    return df


def save_transaction(date, amount, category, description, mode):
    df = load_transactions()

    new_row = pd.DataFrame([{
        "Date": date.strftime("%d/%m/%Y"),
        "Amount": amount,
        "Category": category,
        "Description": description,
        "Mode": mode
    }])

    df = pd.concat([new_row, df], ignore_index=True)
    save_csv(TRANSACTION_FILE, df)


def load_budgets():
    return load_csv(BUDGET_FILE, ["Month", "Category", "Budget"])


def save_budget(month, category, budget):
    df = load_budgets()

    df = df[~((df["Month"] == month) & (df["Category"] == category))]

    new_row = pd.DataFrame([{
        "Month": month,
        "Category": category,
        "Budget": budget
    }])

    df = pd.concat([df, new_row], ignore_index=True)
    save_csv(BUDGET_FILE, df)

# ---------------- UI ----------------
st.set_page_config(
    page_title="💰 Personal Finance",
    layout="wide"
)

st.title("💰 Personal Finance Tracker")

menu = st.sidebar.radio(
    "Menu",
    ["Add Transaction", "View Transactions", "Category Summary", "Budgets"]
)

# -------- ADD TRANSACTION --------
if menu == "Add Transaction":
    st.subheader("➕ Add Transaction")

    with st.form("add_tx"):
        date = st.date_input("Date", datetime.today())
        amount = st.number_input("Amount", min_value=1.0, step=1.0)
        category = st.selectbox("Category", CATEGORIES)
        description = st.text_input("Description")
        mode = st.selectbox("Payment Mode", ["UPI", "Cash", "Card", "Bank"])

        submitted = st.form_submit_button("Save Transaction")

        if submitted:
            save_transaction(date, amount, category, description, mode)
            st.success("✅ Transaction saved")

# -------- VIEW TRANSACTIONS --------
elif menu == "View Transactions":
    st.subheader("📄 Transactions")

    df = load_transactions()
    st.dataframe(df, use_container_width=True)

    if not df.empty:
        daily = (
            df.groupby("Date")["Amount"]
            .sum()
            .reset_index()
            .sort_values("Date")
        )

        fig = px.line(
            daily,
            x="Date",
            y="Amount",
            title="Daily Expenses"
        )
        st.plotly_chart(fig, use_container_width=True)

# -------- CATEGORY SUMMARY --------
elif menu == "Category Summary":
    st.subheader("📊 Category Summary")

    df = load_transactions()

    if not df.empty:
        cat = (
            df.groupby("Category")["Amount"]
            .sum()
            .reset_index()
        )

        fig = px.pie(
            cat,
            names="Category",
            values="Amount",
            title="Expenses by Category"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No transactions yet")

# -------- BUDGETS --------
elif menu == "Budgets":
    st.subheader("💼 Monthly Budgets")

    month = st.text_input(
        "Month (YYYY-MM)",
        datetime.today().strftime("%Y-%m")
    )
    category = st.selectbox("Category", CATEGORIES)
    budget = st.number_input("Budget Amount", min_value=0.0, step=500.0)

    if st.button("Save Budget"):
        save_budget(month, category, budget)
        st.success("✅ Budget saved")

    st.markdown("### 📋 All Budgets")
    st.dataframe(load_budgets(), use_container_width=True)
