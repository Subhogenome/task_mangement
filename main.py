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
MONGO_URI = st.secrets["mongo"]["uri"]
DB_NAME = "nc_ops"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

users_col = db.users
tasks_col = db.tasks
task_logs_col = db.task_logs
leave_col = db.leave_requests

st.set_page_config("NC Task Management", layout="wide")

# =====================================================
# CONSTANTS
# =====================================================
LEAVE_TYPES = ["CL", "SL", "COURSE"]
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
        st.error("User not registered")
        st.stop()

    if user_doc:
        if user_doc.get("first_login", False):
            st.subheader("First Login – Set Password")
            p1 = st.text_input("Password", type="password")
            p2 = st.text_input("Confirm Password", type="password")

            if st.button("Set Password"):
                if not p1 or p1 != p2:
                    st.error("Passwords do not match")
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
            pwd = st.text_input("Password", type="password")
            if st.button("Login"):
                if bcrypt.checkpw(pwd.encode(), user_doc["password_hash"]):
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
    ["Dashboard", "Tasks", "Daily Update", "Leave", "Logout"]
)

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":
    st.title("📊 Dashboard")

    if is_nc:
        sel_date = st.date_input("Select Date", today)
        sel_dt = to_utc_datetime(sel_date)

        logs = list(task_logs_col.find({"date": sel_dt}))
        st.dataframe(pd.DataFrame(logs)) if logs else st.info("No logs")

    else:
        logs = list(task_logs_col.find({"user": user["email"]}))
        st.dataframe(pd.DataFrame(logs)) if logs else st.info("No logs yet")

# =====================================================
# TASK CREATION
# =====================================================
elif menu == "Tasks":
    st.title("📝 Create Task")

    title = st.text_input("Title *")
    desc = st.text_area("Description *")
    start = st.date_input("Start Date *")
    end = st.date_input("End Date *")

    if is_nc:
        assigned_to = st.text_input("Assign To (Email) *")
    else:
        assigned_to = user["email"]

    if st.button("Create Task"):
        if not all([title.strip(), desc.strip(), assigned_to.strip()]):
            st.error("All fields mandatory")
        else:
            tasks_col.insert_one({
                "title": title,
                "description": desc,
                "start_date": to_utc_datetime(start),
                "end_date": to_utc_datetime(end),
                "assigned_to": assigned_to,
                "created_by": user["email"],
                "status": "To Do",
                "created_at": datetime.now(timezone.utc)
            })
            st.success("Task created")

    st.divider()

    for t in tasks_col.find():
        if is_nc or t["assigned_to"] == user["email"]:
            with st.expander(f"{t['title']} → {t['assigned_to']}"):
                st.write(t["description"])

# =====================================================
# DAILY TASK UPDATE (MANDATORY)
# =====================================================
elif menu == "Daily Update":
    st.title("🗓️ Daily Task Update")

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
        reason = st.text_area("Reason for no task *")
        if st.button("Submit"):
            if reason.strip():
                task_logs_col.update_one(
                    {"user": user["email"], "date": log_dt},
                    {"$set": {
                        "user": user["email"],
                        "date": log_dt,
                        "task_id": None,
                        "description": reason,
                        "updated_at": datetime.now(timezone.utc)
                    }},
                    upsert=True
                )
                st.success("Logged")
        st.stop()

    task_map = {t["title"]: t["_id"] for t in my_tasks}
    task = st.selectbox("Task *", list(task_map.keys()))
    work = st.text_area("Work done today *")

    if st.button("Submit Update"):
        if not work.strip():
            st.error("Description required")
        else:
            task_logs_col.update_one(
                {"user": user["email"], "date": log_dt},
                {"$set": {
                    "user": user["email"],
                    "date": log_dt,
                    "task_id": task_map[task],
                    "description": work,
                    "updated_at": datetime.now(timezone.utc)
                }},
                upsert=True
            )
            st.success("Daily update saved")

# =====================================================
# LEAVE
# =====================================================
elif menu == "Leave":
    st.title("🌴 Leave")

    if not is_nc:
        ltype = st.selectbox("Leave Type *", LEAVE_TYPES)
        ldate = st.date_input("Leave Date *")
        reason = st.text_area("Reason *")

        if st.button("Apply Leave") and reason.strip():
            leave_col.insert_one({
                "user": user["email"],
                "type": ltype,
                "date": to_utc_datetime(ldate),
                "reason": reason,
                "status": "Pending",
                "created_at": datetime.now(timezone.utc)
            })
            st.success("Leave applied")

    else:
        for l in leave_col.find({"status": "Pending"}):
            with st.expander(f"{l['user']} | {l['type']} | {l['date']}"):
                st.write(l["reason"])
                if st.button("Approve", key=str(l["_id"])):
                    leave_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {
                            "status": "Approved",
                            "approved_at": datetime.now(timezone.utc)
                        }}
                    )
                    st.success("Approved")

# =====================================================
# LOGOUT
# =====================================================
elif menu == "Logout":
    st.session_state.user = None
    st.rerun()
