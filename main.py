import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import date, timedelta, datetime
from bson.objectid import ObjectId
import bcrypt

# =====================================================
# CONFIG (SECURE)
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

INDIAN_STATES = [
    "Andhra Pradesh","Assam","Bihar","Chhattisgarh","Delhi","Goa","Gujarat",
    "Haryana","Himachal Pradesh","Jharkhand","Karnataka","Kerala","Madhya Pradesh",
    "Maharashtra","Odisha","Punjab","Rajasthan","Tamil Nadu","Telangana",
    "Uttar Pradesh","Uttarakhand","West Bengal","Other"
]

MEETING_SCOPE = ["Pan India", "State-wise", "With DCs", "With NCs"]

today = date.today()
editable_from = today - timedelta(days=6)

# =====================================================
# SESSION
# =====================================================
if "user" not in st.session_state:
    st.session_state.user = None

# =====================================================
# LOGIN (NO BOOTSTRAP)
# =====================================================
if not st.session_state.user:
    st.title("🔐 Login")

    email = st.text_input("Email")
    user_doc = users_col.find_one({"email": email, "active": True})

    if email and not user_doc:
        st.error("User not registered. Contact admin.")
        st.stop()

    if user_doc:

        # ---------- FIRST LOGIN ----------
        if user_doc.get("first_login", False):
            st.subheader("First-Time Login – Create Password")

            p1 = st.text_input("Create Password", type="password")
            p2 = st.text_input("Confirm Password", type="password")

            if st.button("Set Password"):
                if not p1 or p1 != p2:
                    st.error("Passwords are empty or do not match")
                else:
                    users_col.update_one(
                        {"_id": user_doc["_id"]},
                        {"$set": {
                            "password_hash": bcrypt.hashpw(
                                p1.encode(), bcrypt.gensalt()
                            ),
                            "first_login": False,
                            "updated_at": datetime.utcnow()
                        }}
                    )
                    st.success("Password created. Please login again.")
                    st.stop()

        # ---------- NORMAL LOGIN ----------
        else:
            password = st.text_input("Password", type="password")
            if st.button("Login"):
                if bcrypt.checkpw(
                    password.encode(),
                    user_doc["password_hash"]
                ):
                    st.session_state.user = {
                        "email": user_doc["email"],
                        "name": user_doc["name"],
                        "role": user_doc["role"]
                    }
                    st.experimental_rerun()
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

        def show(title, col):
            data = list(col.find({"date": sel_date}))
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
        if logs:
            st.dataframe(pd.DataFrame(logs))
        else:
            st.info("No activity logged yet")

# =====================================================
# TASKS
# =====================================================
elif menu == "Tasks":
    st.title("📝 Tasks")

    title = st.text_input("Task Title *")
    desc = st.text_area("Task Description *")
    start = st.date_input("Start Date *")
    end = st.date_input("End Date *")

    if is_nc:
        assigned_to = st.text_input("Assign To (Email) *")
    else:
        assigned_to = user["email"]

    if st.button("Create Task"):
        if not all([title.strip(), desc.strip(), start, end, assigned_to.strip()]):
            st.error("All fields are mandatory")
        else:
            tasks_col.insert_one({
                "title": title,
                "description": desc,
                "start_date": start,
                "end_date": end,
                "assigned_to": assigned_to,
                "created_by": user["email"],
                "status": "To Do"
            })
            st.success("Task created")

    st.divider()
    for t in tasks_col.find():
        if is_nc or t["assigned_to"] == user["email"]:
            with st.expander(f"{t['title']} → {t['assigned_to']}"):
                st.write(t["description"])
                st.write(f"{t['start_date']} → {t['end_date']}")

# =====================================================
# DAILY LOGS (MANDATORY)
# =====================================================
elif menu == "Daily Logs":
    st.title("🗓️ Daily Work Log (Mandatory)")

    if is_nc:
        st.info("NCs can monitor only")
        st.stop()

    log_date = st.date_input(
        "Log Date",
        today,
        min_value=editable_from,
        max_value=today
    )

    if leave_col.find_one({"user": user["email"], "date": log_date, "status": "Approved"}):
        st.warning("On approved leave. Auto log applied.")
        task_logs_col.update_one(
            {"user": user["email"], "date": log_date},
            {"$set": {
                "user": user["email"],
                "date": log_date,
                "task_id": None,
                "description": "No work done – On Leave"
            }},
            upsert=True
        )
        st.stop()

    my_tasks = list(tasks_col.find({"assigned_to": user["email"]}))

    if not my_tasks:
        st.error("No tasks assigned. Reason is mandatory.")
        reason = st.text_area("Reason *")
        if st.button("Submit"):
            if reason.strip():
                task_logs_col.insert_one({
                    "user": user["email"],
                    "date": log_date,
                    "task_id": None,
                    "description": reason
                })
                st.success("Log saved")
        st.stop()

    task_map = {t["title"]: t["_id"] for t in my_tasks}
    task = st.selectbox("Task *", list(task_map.keys()))
    desc = st.text_area("Work Done *")

    if st.button("Submit Task Log"):
        if not desc.strip():
            st.error("Description is mandatory")
        else:
            task_logs_col.update_one(
                {"user": user["email"], "date": log_date},
                {"$set": {
                    "user": user["email"],
                    "date": log_date,
                    "task_id": task_map[task],
                    "description": desc
                }},
                upsert=True
            )
            st.success("Daily log saved")

# =====================================================
# LEAVE
# =====================================================
elif menu == "Leave":
    st.title("🌴 Leave")

    if not is_nc:
        ltype = st.selectbox("Leave Type *", LEAVE_TYPES)
        ldate = st.date_input("Leave Date *")
        reason = st.text_area("Reason *")

        if st.button("Apply Leave"):
            if reason.strip():
                leave_col.insert_one({
                    "user": user["email"],
                    "type": ltype,
                    "date": ldate,
                    "reason": reason,
                    "status": "Pending"
                })
                st.success("Leave applied")

    else:
        st.subheader("Approve Leaves")
        for l in leave_col.find({"status": "Pending"}):
            with st.expander(f"{l['user']} | {l['type']} | {l['date']}"):
                st.write(l["reason"])
                if st.button("Approve", key=str(l["_id"])):
                    leave_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {"status": "Approved"}}
                    )
                    st.success("Approved")

# =====================================================
# LOGOUT
# =====================================================
elif menu == "Logout":
    st.session_state.user = None
    st.experimental_rerun()
