import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import uuid

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

# ---------------- AUTH ----------------
def get_sheets_service():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

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
        "values": [df.columns.tolist()] +
                  df.astype(str).fillna("").values.tolist()
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
        df["Date_dt"] = pd.to_datetime(df["Date"], dayfirst=True)
    return df

def save_transaction(date, amount, category, description, mode):
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

    df["Date_dt"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.sort_values("Date_dt", ascending=False)
    df = df.drop(columns=["Date_dt"])


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
    df = pd.concat(
        [df, pd.DataFrame([[month, category, budget]],
        columns=["Month", "Category", "Budget"])]
    )
    write_sheet(BUDGETS_SHEET, df)

# ---------------- UI ----------------
st.set_page_config("💰 Personal Finance", layout="wide")
st.title(f"💰 Personal Finance Tracker ({st.session_state.user})")

menu = st.sidebar.radio(
    "Menu",
    [
        "Add Transaction",
        "View Transactions",
        "Edit Transaction",
        "Category Summary",
        "Date Range Report",
        "Budgets",
        "Monthly Summary"
    ]
)

# -------- ADD TRANSACTION --------
if menu == "Add Transaction":
    with st.form("add_tx", clear_on_submit=True):
        date = st.date_input("Date", datetime.today())
        amount = st.number_input("Amount", min_value=1.0)
        category = st.selectbox("Category", CATEGORIES)
        description = st.text_input("Description")
        mode = st.selectbox("Payment Mode", ["UPI", "Cash", "Card", "Bank"])
        submitted = st.form_submit_button("Save")

        if submitted:
            save_transaction(date, amount, category, description, mode)
            st.success("✅ Transaction saved")

# -------- VIEW TRANSACTIONS --------
elif menu == "View Transactions":
    st.header("📜 All Transactions")

    df = load_transactions()

    if df.empty:
        st.warning("No transactions found.")
    else:
        st.dataframe(
            df.drop(columns=["TransactionID"]),
            use_container_width=True
        )


# -------- EDIT TRANSACTION --------

elif menu == "Edit Transaction":
    st.header("✏️ Edit / Delete Transaction")

    df = load_transactions()

    if df.empty:
        st.warning("No transactions available.")
    else:
        df["Label"] = (
            df["Date"] + " | ₹" + df["Amount"].astype(str) +
            " | " + df["Category"]
        )

        selected_label = st.selectbox(
            "Select a transaction",
            df["Label"]
        )

        selected_row = df[df["Label"] == selected_label].iloc[0]

        with st.form("edit_tx"):
            date = st.date_input(
                "Date",
                datetime.strptime(selected_row["Date"], "%d/%m/%Y")
            )
            amount = st.number_input(
                "Amount",
                value=float(selected_row["Amount"])
            )
            category = st.selectbox(
                "Category",
                CATEGORIES,
                index=CATEGORIES.index(selected_row["Category"])
            )
            description = st.text_input(
                "Description",
                selected_row["Description"]
            )
            mode = st.selectbox(
                "Payment Mode",
                ["UPI", "Cash", "Card", "Bank"],
                index=["UPI", "Cash", "Card", "Bank"].index(selected_row["Mode"])
            )

            col1, col2, col3 = st.columns(3)

            with col1:
                save = st.form_submit_button("💾 Save Changes")
            with col2:
                delete = st.form_submit_button("🗑️ Delete")
            with col3:
                cancel = st.form_submit_button("❌ Cancel")

        # -------- SAVE --------
        if save:
            df.loc[df["TransactionID"] == selected_row["TransactionID"], [
                "Date", "Amount", "Category", "Description", "Mode"
            ]] = [
                date.strftime("%d/%m/%Y"),
                amount,
                category,
                description,
                mode
            ]

            write_sheet(TRANSACTIONS_SHEET, df)
            st.success("Transaction updated")
            st.rerun()

        # -------- DELETE --------
        if delete:
            df = df[df["TransactionID"] != selected_row["TransactionID"]]
            write_sheet(TRANSACTIONS_SHEET, df)
            st.success("Transaction deleted")
            st.rerun()


# -------- CATEGORY SUMMARY --------
elif menu == "Category Summary":
    df = load_transactions()
    if not df.empty:
        summary = df.groupby("Category")["Amount"].sum().sort_values(ascending=False)
        st.dataframe(summary.reset_index())
        st.bar_chart(summary)

# -------- DATE RANGE --------
elif menu == "Date Range Report":
    df = load_transactions()
    if not df.empty:
        start = st.date_input("Start Date", df["Date_dt"].min().date())
        end = st.date_input("End Date", df["Date_dt"].max().date())

        mask = (df["Date_dt"].dt.date >= start) & (df["Date_dt"].dt.date <= end)
        filtered = df[mask]
        st.dataframe(filtered.drop(columns=["Date_dt"]))
        st.success(f"Total: ₹{filtered['Amount'].sum():,.2f}")

# -------- BUDGETS --------
elif menu == "Budgets":
    month = st.text_input("Month (YYYY-MM)", datetime.today().strftime("%Y-%m"))
    category = st.selectbox("Category", CATEGORIES)
    budget = st.number_input("Budget", min_value=0.0)

    if st.button("Save Budget"):
        save_budget(month, category, budget)
        st.success("Budget saved")

    st.dataframe(load_budgets())

# -------- SUMMARY --------
elif menu == "Monthly Summary":
    df = load_transactions()
    budgets = load_budgets()
    month = st.text_input("Month (YYYY-MM)", datetime.today().strftime("%Y-%m"))

    if not df.empty and not budgets.empty:
        df["Month"] = df["Date_dt"].dt.to_period("M").astype(str)
        spent = df[df["Month"] == month].groupby("Category")["Amount"].sum()
        summary = budgets[budgets["Month"] == month].copy()
        summary["Spent"] = summary["Category"].map(spent).fillna(0)
        summary["Remaining"] = summary["Budget"] - summary["Spent"]
        st.dataframe(summary)
        st.bar_chart(summary.set_index("Category")["Remaining"])
