import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import date, timedelta, datetime, timezone
from bson.objectid import ObjectId
import bcrypt

# =====================================================
# HELPERS
# =====================================================
def to_utc_datetime(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

# =====================================================
# CONFIG
# =====================================================
MONGO_URI = st.secrets["mongo"]
DB_NAME = "nc_ops"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

users_col = db.users
tasks_col = db.tasks
task_logs_col = db.task_logs
call_logs_col = db.call_logs
meeting_logs_col = db.meeting_logs
leave_col = db.leave_requests

st.set_page_config("NC Operations System", layout="wide")

# =====================================================
# CONSTANTS
# =====================================================
LEAVE_TYPES = ["CL", "SL", "COURSE"]
MEETING_SCOPE = ["Pan India", "State-wise", "With DCs", "With NCs"]

today = date.today()
editable_from = today - timedelta(days=6)

# =====================================================
# SESSION
# =====================================================
if "user" not in st.session_state:
    st.session_state.user = None

# =====================================================
# LOGIN
# =====================================================
if not st.session_state.user:
    st.title("🔐 Login")

    email = st.text_input("Email")
    user_doc = users_col.find_one({"email": email, "active": True})

    if email and not user_doc:
        st.error("User not registered. Contact admin.")
        st.stop()

    if user_doc:
        if user_doc.get("first_login", False):
            st.subheader("First-Time Login – Create Password")
            p1 = st.text_input("Create Password", type="password")
            p2 = st.text_input("Confirm Password", type="password")

            if st.button("Set Password"):
                if not p1 or p1 != p2:
                    st.error("Passwords invalid")
                else:
                    users_col.update_one(
                        {"_id": user_doc["_id"]},
                        {"$set": {
                            "password_hash": bcrypt.hashpw(p1.encode(), bcrypt.gensalt()),
                            "first_login": False,
                            "updated_at": datetime.now(timezone.utc)
                        }}
                    )
                    st.success("Password set. Login again.")
                    st.stop()
        else:
            password = st.text_input("Password", type="password")
            if st.button("Login"):
                if bcrypt.checkpw(password.encode(), user_doc["password_hash"]):
                    st.session_state.user = {
                        "email": user_doc["email"],
                        "name": user_doc["name"],
                        "role": user_doc["role"]
                    }
                    st.rerun()
                else:
                    st.error("Invalid password")

    st.stop()

# =====================================================
# AUTH CONTEXT
# =====================================================
user = st.session_state.user
is_nc = user["role"] == "nc"

st.sidebar.success(f"Logged in as {user['name']}")
menu = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Tasks", "Daily Logs", "Leave", "Logout"]
)

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":
    st.title("📊 Dashboard")

    if is_nc:
        sel_date = st.date_input("Select Date", today)
        sel_dt = to_utc_datetime(sel_date)

        def show(title, col):
            data = list(col.find({"date": sel_dt}))
            if data:
                st.subheader(title)
                st.dataframe(pd.DataFrame(data))

        show("📝 Task Logs", task_logs_col)
        show("📞 Call Logs", call_logs_col)
        show("🧑‍🤝‍🧑 Meeting Logs", meeting_logs_col)

    else:
        logs = (
            list(task_logs_col.find({"user": user["email"]})) +
            list(call_logs_col.find({"user": user["email"]})) +
            list(meeting_logs_col.find({"user": user["email"]}))
        )
        st.dataframe(pd.DataFrame(logs)) if logs else st.info("No logs yet")

# =====================================================
# DAILY LOGS
# =====================================================
elif menu == "Daily Logs":
    st.title("🗓️ Daily Work Log")

    if is_nc:
        st.info("NCs can monitor only")
        st.stop()

    log_date = st.date_input(
        "Log Date",
        today,
        min_value=editable_from,
        max_value=today
    )
    log_dt = to_utc_datetime(log_date)

    if leave_col.find_one({"user": user["email"], "date": log_dt, "status": "Approved"}):
        task_logs_col.update_one(
            {"user": user["email"], "date": log_dt},
            {"$set": {
                "user": user["email"],
                "date": log_dt,
                "task_id": None,
                "description": "No work done – On Leave",
                "updated_at": datetime.now(timezone.utc)
            }},
            upsert=True
        )
        st.warning("On approved leave")
        st.stop()

    my_tasks = list(tasks_col.find({"assigned_to": user["email"]}))
    if not my_tasks:
        reason = st.text_area("Reason *")
        if st.button("Submit") and reason.strip():
            task_logs_col.insert_one({
                "user": user["email"],
                "date": log_dt,
                "task_id": None,
                "description": reason,
                "created_at": datetime.now(timezone.utc)
            })
            st.success("Logged")
        st.stop()

    task_map = {t["title"]: t["_id"] for t in my_tasks}
    task = st.selectbox("Task *", list(task_map.keys()))
    desc = st.text_area("Work Done *")

    if st.button("Submit Task Log") and desc.strip():
        task_logs_col.update_one(
            {"user": user["email"], "date": log_dt},
            {"$set": {
                "user": user["email"],
                "date": log_dt,
                "task_id": task_map[task],
                "description": desc,
                "updated_at": datetime.now(timezone.utc)
            }},
            upsert=True
        )
        st.success("Saved")

# =====================================================
# LOGOUT
# =====================================================
elif menu == "Logout":
    st.session_state.user = None
    st.rerun()
