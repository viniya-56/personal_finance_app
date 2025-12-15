import streamlit as st
import pandas as pd
from datetime import datetime
import os
import csv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# plotting libraries
import plotly.express as px
import altair as alt

# -------------------------
# Config & Constants
# -------------------------
st.set_page_config(page_title="💰 Personal Budget Tracker", layout="wide")
TRANSACTION_FILE = "transactions.csv"
BUDGET_FILE = "budgets.csv"

CATEGORIES = ["Food", "Transport", "Rent", "Utilities", "Trips", "Clothes",
              "Books", "Shopping", "DMart Shopping", "Electricity Bill",
              "Train Tickets", "Entertainment", "Healthcare", "Recharge",
              "Food Related", "Home expenses", "Others"]

# -------------------------
# Initialization
# -------------------------
def initialize_files():
    # Ensure transactions file has GroupName column
    if not os.path.exists(TRANSACTION_FILE):
        with open(TRANSACTION_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Amount", "Category", "Description", "Mode", "GroupName"])

    if not os.path.exists(BUDGET_FILE):
        with open(BUDGET_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Month", "Category", "Budget"])

initialize_files()


def get_drive_service():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)


def get_drive_file_id(filename):
    service = get_drive_service()
    folder_id = st.secrets["drive"]["folder_id"]

    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]
    return None


# -------------------------
# Data Utilities
# -------------------------
def _ensure_transaction_columns(df):
    expected = ["Date", "Amount", "Category", "Description", "Mode", "GroupName"]
    for col in expected:
        if col not in df.columns:
            df[col] = "" if col != "Amount" else 0
    return df[expected]


def load_transactions():
    service = get_drive_service()
    folder_id = st.secrets["drive"]["folder_id"]
    query = f"'{folder_id}' in parents and name='transactions.csv'"
    results = service.files().list(q=query).execute()
    files = results.get("files", [])

    if not files:
        return pd.DataFrame(columns=["Date","Amount","Category","Description","Mode","GroupName"])

    file_id = files[0]["id"]
    request = service.files().get_media(fileId=file_id)
    data = io.BytesIO(request.execute())

    return pd.read_csv(data)


def save_transaction(date, amount, category, description, mode, group_name):
    df = load_transactions()

    new_row = pd.DataFrame([{
        "Date": date,
        "Amount": amount,
        "Category": category,
        "Description": description,
        "Mode": mode,
        "GroupName": group_name
    }])

    df = pd.concat([df, new_row], ignore_index=True)

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date", ascending=False)
    df["Date"] = df["Date"].dt.strftime("%d/%m/%Y")

    # Upload back to Drive
    service = get_drive_service()
    folder_id = st.secrets["drive"]["folder_id"]

    csv_bytes = io.BytesIO()
    df.to_csv(csv_bytes, index=False)
    csv_bytes.seek(0)

    media = MediaIoBaseUpload(csv_bytes, mimetype="text/csv")

    query = f"'{folder_id}' in parents and name='transactions.csv'"
    results = service.files().list(q=query).execute()
    files = results.get("files", [])

    if files:
        service.files().update(
            fileId=files[0]["id"],
            media_body=media
        ).execute()
    else:
        service.files().create(
            body={"name": "transactions.csv", "parents": [folder_id]},
            media_body=media
        ).execute()


def load_budgets():
    service = get_drive_service()
    folder_id = st.secrets["drive"]["folder_id"]
    file_id = get_drive_file_id(BUDGET_FILE)

    if not file_id:
        # Create empty budgets.csv in Drive
        df = pd.DataFrame(columns=["Month", "Category", "Budget"])
        csv_buffer = io.BytesIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        media = MediaIoBaseUpload(csv_buffer, mimetype="text/csv")
        service.files().create(
            body={"name": BUDGET_FILE, "parents": [folder_id]},
            media_body=media
        ).execute()
        return df

    # Download existing file
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    fh.seek(0)
    return pd.read_csv(fh)


def save_budget(month, category, budget):
    service = get_drive_service()
    folder_id = st.secrets["drive"]["folder_id"]
    file_id = get_drive_file_id(BUDGET_FILE)

    df = load_budgets()

    # Remove old budget for same month & category
    df = df[~((df["Month"] == month) & (df["Category"] == category))]

    # Add new row
    new_row = pd.DataFrame(
        [[month, category, budget]],
        columns=["Month", "Category", "Budget"]
    )
    df = pd.concat([df, new_row], ignore_index=True)

    # Upload back to Drive
    csv_buffer = io.BytesIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    media = MediaIoBaseUpload(csv_buffer, mimetype="text/csv")

    if file_id:
        service.files().update(
            fileId=file_id,
            media_body=media
        ).execute()
    else:
        service.files().create(
            body={"name": BUDGET_FILE, "parents": [folder_id]},
            media_body=media
        ).execute()


def calculate_remaining(month, transactions, budgets):
    # transactions is DataFrame with Date_dt
    tx = transactions.copy()
    tx["Month"] = tx["Date_dt"].dt.to_period("M").astype(str)
    month_tx = tx[tx["Month"] == month]
    spent = month_tx.groupby("Category")["Amount"].sum().reset_index().rename(columns={"Amount": "Spent"})
    month_budgets = budgets[budgets["Month"] == month]
    summary = pd.merge(month_budgets, spent, on="Category", how="left").fillna(0)
    summary["Remaining"] = summary["Budget"] - summary["Spent"]
    return summary


def get_existing_groups(df):
    if "GroupName" not in df.columns:
        return []
    # Convert to string and strip spaces
    groups = df["GroupName"].fillna("").astype(str).str.strip()
    # Remove empty values
    groups = groups[groups != ""]
    return sorted(groups.unique())



# -------------------------
# Utility: Export CSV to download
# -------------------------
def convert_df_to_csv_bytes(df):
    return df.to_csv(index=False).encode('utf-8')

# -------------------------
# UI: Sidebar Navigation
# -------------------------
st.title("💰 Personal Budget Tracker")
menu = st.sidebar.radio("Navigate", 
    ["Add Transaction", "View Transactions", "Category Totals", 
     "Date Range Report", "Group Overview", "Set Budgets", "Summary"])

# Mobile note
st.sidebar.markdown("**Tip:** On mobile, use the browser menu → Add to Home screen for app-like behavior.")

# -------------------------
# Add Transaction
# -------------------------
if menu == "Add Transaction":
    st.header("➕ Add a New Transaction")
    transactions_df = load_transactions()
    groups = ["(none)"] + get_existing_groups(transactions_df)

    with st.form("transaction_form", clear_on_submit=True):
        # Two column form for mobile readability
        c1, c2 = st.columns([1,1])
        with c1:
            date_input = st.date_input("Date", datetime.today())
            date_str = date_input.strftime("%d/%m/%Y")
            amount = st.number_input("Amount (Rs.)", min_value=0.0, step=0.5, value=0.0)
            category = st.selectbox("Category", CATEGORIES)
        with c2:
            group_selection = st.selectbox("Group (optional)", groups)
            description = st.text_input("Description")
            mode = st.selectbox("Payment Mode", ["UPI", "Cash", "Card", "Bank Transfer"])
        submitted = st.form_submit_button("Save Transaction")
        if submitted:
            chosen_group = None if group_selection == "(none)" else group_selection
            save_transaction(date_str, amount, category, description, mode, chosen_group)
            st.success("✅ Transaction added successfully!")

    st.markdown("---")
    st.subheader("Quick group actions")
    col1, col2 = st.columns(2)
    with col1:
        new_group_name = st.text_input("Create new group (e.g., 'Goa Trip')", key="new_group")
        if st.button("Create Group"):
            # create an empty placeholder transaction? No — simply ensure group exists by adding hidden metadata row? Simpler: create a group by adding a zero-amount transaction with Description 'GROUP: create'
            if new_group_name.strip() != "":
                save_transaction(datetime.today().strftime("%d/%m/%Y"), 0.0, "Others", f"__GROUP_CREATED__:{new_group_name.strip()}", "System", new_group_name.strip())
                st.success(f"Group '{new_group_name.strip()}' created. Add expenses to it from Add Transaction.")
            else:
                st.warning("Enter a group name.")

    with col2:
        # Export all transactions
        if st.button("Export all transactions CSV"):
            df_export = load_transactions().copy()
            df_export["Date"] = df_export["Date_dt"].dt.strftime("%d/%m/%Y")
            csv_bytes = convert_df_to_csv_bytes(df_export[["Date","Amount","Category","Description","Mode","GroupName"]])
            st.download_button("Download CSV", data=csv_bytes, file_name="transactions_export.csv", mime="text/csv")

# -------------------------
# View Transactions
# -------------------------
elif menu == "View Transactions":
    st.header("📜 All Transactions")
    df = load_transactions()
    if df.empty:
        st.warning("No transactions found.")
    else:
        # Show filters
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            text_search = st.text_input("Search description / mode")
        with c2:
            group_filter = st.selectbox("Filter by Group", ["All"] + ["(none)"] + get_existing_groups(df))
        with c3:
            category_filter = st.selectbox("Category", ["All"] + CATEGORIES)

        # apply filters
        df_show = df.copy()
        if text_search:
            df_show = df_show[df_show["Description"].str.contains(text_search, case=False, na=False) | df_show["Mode"].str.contains(text_search, case=False, na=False)]
        if group_filter != "All":
            if group_filter == "(none)":
                df_show = df_show[df_show["GroupName"].astype(str).str.strip() == ""]
            else:
                df_show = df_show[df_show["GroupName"] == group_filter]
        if category_filter != "All":
            df_show = df_show[df_show["Category"] == category_filter]

        # Format for display
        df_display = df_show.copy()
        df_display["Date"] = df_display["Date_dt"].dt.strftime("%d/%m/%Y")
        df_display = df_display[["Date","Amount","Category","Description","Mode","GroupName"]]

        st.dataframe(df_display, use_container_width=True, height=400)

        # Trend chart (Plotly)
        st.subheader("📈 Expense Trend")
        daily = df_show.groupby(df_show["Date_dt"].dt.date)["Amount"].sum().reset_index()
        daily["Date_str"] = pd.to_datetime(daily["Date_dt"]).dt.strftime("%d/%m/%Y")
        if not daily.empty:
            fig = px.line(daily, x="Date_dt", y="Amount", markers=True, title="Daily Expenses")
            fig.update_layout(xaxis_title="Date", yaxis_title="Amount (Rs.)", margin=dict(t=40, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No expense data to show trend.")

# -------------------------
# Category Totals
# -------------------------
elif menu == "Category Totals":
    st.header("📊 Expenses by Category")
    df = load_transactions()
    if df.empty:
        st.warning("No transactions found.")
    else:
        totals = df.groupby("Category")["Amount"].sum().reset_index().sort_values("Amount", ascending=False)
        st.dataframe(totals, use_container_width=True)

        st.subheader("📊 Category Distribution (Pie)")
        fig = px.pie(totals, names="Category", values="Amount", hole=0.4, title="Expenses by Category")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("📊 Category Totals (Bar)")
        # Altair bar chart (responsive)
        chart = alt.Chart(totals).mark_bar().encode(
            x=alt.X("Category:N", sort="-y"),
            y=alt.Y("Amount:Q", title="Total Spent (Rs.)"),
            tooltip=["Category", "Amount"]
        ).properties(height=350)
        st.altair_chart(chart, use_container_width=True)

# -------------------------
# Date Range Report
# -------------------------
elif menu == "Date Range Report":
    st.header("📅 Expenses Between Dates")
    df = load_transactions()
    if df.empty:
        st.warning("No transactions found.")
    else:
        min_date = df["Date_dt"].min().date()
        max_date = df["Date_dt"].max().date()
        start_date = st.date_input("Start Date", min_date)
        end_date = st.date_input("End Date", max_date)
        group_filter = st.selectbox("Filter by Group (optional)", ["All", "(none)"] + get_existing_groups(df))
        mask = (df["Date_dt"].dt.date >= start_date) & (df["Date_dt"].dt.date <= end_date)
        filtered = df[mask]
        if group_filter != "All":
            if group_filter == "(none)":
                filtered = filtered[filtered["GroupName"].astype(str).str.strip() == ""]
            else:
                filtered = filtered[filtered["GroupName"] == group_filter]
        st.dataframe(filtered.assign(Date=filtered["Date_dt"].dt.strftime("%d/%m/%Y"))[["Date","Amount","Category","Description","Mode","GroupName"]], use_container_width=True)
        st.success(f"Total Expenses: Rs.{filtered['Amount'].sum():,.2f}")

# -------------------------
# Group Overview
# -------------------------
elif menu == "Group Overview":
    st.header("🗂️ Groups & Group Expenses")
    df = load_transactions()
    groups = get_existing_groups(df)
    if not groups:
        st.info("No groups created yet. Create groups from 'Add Transaction' (Quick group actions) or tag transactions with group names.")
    else:
        st.subheader("Group Totals")
        group_totals = df[df["GroupName"].astype(str).str.strip() != ""].groupby("GroupName")["Amount"].sum().reset_index().sort_values("Amount", ascending=False)
        st.dataframe(group_totals, use_container_width=True)

        fig = px.bar(group_totals, x="GroupName", y="Amount", title="Total spent per Group", text="Amount")
        fig.update_layout(xaxis_title="Group", yaxis_title="Total Spent (Rs.)", margin=dict(t=40, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

        selected_group = st.selectbox("Select a group to view details", ["(none)"] + groups)
        if selected_group != "(none)":
            grp_df = df[df["GroupName"] == selected_group].copy()
            grp_df["Date"] = grp_df["Date_dt"].dt.strftime("%d/%m/%Y")
            st.subheader(f"Transactions in '{selected_group}'")
            st.dataframe(grp_df[["Date","Amount","Category","Description","Mode"]], use_container_width=True, height=300)

            # Category breakdown inside group
            breakdown = grp_df.groupby("Category")["Amount"].sum().reset_index().sort_values("Amount", ascending=False)
            if not breakdown.empty:
                st.subheader("Category breakdown (within group)")
                fig2 = px.pie(breakdown, names="Category", values="Amount", title=f"Category breakdown for {selected_group}", hole=0.3)
                st.plotly_chart(fig2, use_container_width=True)

            # Export group CSV
            csv_bytes = convert_df_to_csv_bytes(grp_df[["Date","Amount","Category","Description","Mode"]])
            st.download_button(f"Download '{selected_group}' CSV", data=csv_bytes, file_name=f"{selected_group}_transactions.csv", mime="text/csv")

            # Option to archive (remove group tag) or delete transactions
            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"Remove group tag from '{selected_group}' (keep transactions)"):
                    df.loc[df["GroupName"] == selected_group, "GroupName"] = ""
                    # Save back
                    df_to_save = df.copy()
                    df_to_save["Date"] = df_to_save["Date_dt"].dt.strftime("%d/%m/%Y")
                    df_to_save = df_to_save[["Date","Amount","Category","Description","Mode","GroupName"]]
                    df_to_save.to_csv(TRANSACTION_FILE, index=False)
                    st.success(f"Group tag removed from '{selected_group}'.")
            with col2:
                if st.button(f"Delete all transactions in '{selected_group}'"):
                    df = df[df["GroupName"] != selected_group]
                    df_to_save = df.copy()
                    df_to_save["Date"] = df_to_save["Date_dt"].dt.strftime("%d/%m/%Y")
                    df_to_save = df_to_save[["Date","Amount","Category","Description","Mode","GroupName"]]
                    df_to_save.to_csv(TRANSACTION_FILE, index=False)
                    st.success(f"All transactions in '{selected_group}' deleted.")

# -------------------------
# Set Budgets
# -------------------------
elif menu == "Set Budgets":
    st.header("💵 Set Monthly Budgets")
    month = st.text_input("Month (YYYY-MM)", datetime.today().strftime("%Y-%m"))
    category = st.selectbox("Category", CATEGORIES)
    budget = st.number_input("Budget Amount (Rs.)", min_value=0.0, step=500.0)

    if st.button("Save Budget"):
        save_budget(month, category, budget)
        st.success(f"✅ Budget set for {category} in {month}")

    st.subheader("📜 All Budgets")
    st.dataframe(load_budgets(), use_container_width=True)

# -------------------------
# Summary
# -------------------------
elif menu == "Summary":
    st.header("📊 Monthly Summary")
    df = load_transactions()
    budgets = load_budgets()
    month = st.text_input("Enter Month (YYYY-MM)", datetime.today().strftime("%Y-%m"))

    if st.button("Show Summary"):
        summary = calculate_remaining(month, df, budgets)
        if summary.empty:
            st.warning("⚠️ No budgets found for this month.")
        else:
            st.dataframe(summary, use_container_width=True)
            st.subheader("📊 Remaining by Category")
            fig = px.bar(summary, x="Category", y="Remaining", title=f"Remaining Budget for {month}", text="Remaining")
            fig.update_layout(yaxis_title="Remaining (Rs.)", xaxis_title="Category", margin=dict(t=40, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)

# -------------------------
# End of app
# -------------------------
st.markdown("---")
st.caption("Tip: On mobile, use the browser menu → Add to Home screen for a native-app-like experience.")
