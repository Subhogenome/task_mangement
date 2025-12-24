import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import date, timedelta, datetime, timezone
from bson.objectid import ObjectId
import bcrypt

# ================= HELPERS =================
def to_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

# ================= CONFIG =================
MONGO_URI = st.secrets["mongo"]["uri"]
client = MongoClient(MONGO_URI)
db = client["nc_ops"]

users_col = db.users
tasks_col = db.tasks
activity_col = db.activity_logs
leave_col = db.leave_requests

st.set_page_config("NC Task & Activity System", layout="wide")

# ================= CONSTANTS =================
CALL_TYPES = ["SC", "DC", "Lead", "Other"]
MEETING_SCOPE = ["Pan India", "State-wise", "With DCs", "With NCs"]
TASK_STATUS = ["To Do", "Running", "Done"]

today = date.today()
editable_from = today - timedelta(days=6)

# ================= SESSION =================
if "user" not in st.session_state:
    st.session_state.user = None

# ================= LOGIN =================
if not st.session_state.user:
    st.title("🔐 Login")

    email = st.text_input("Email")
    user = users_col.find_one({"email": email, "active": True})

    if email and not user:
        st.error("User not registered")
        st.stop()

    if user:
        if user["first_login"]:
            p1 = st.text_input("Create Password", type="password")
            p2 = st.text_input("Confirm Password", type="password")
            if st.button("Set Password") and p1 == p2:
                users_col.update_one(
                    {"_id": user["_id"]},
                    {"$set": {
                        "password_hash": bcrypt.hashpw(p1.encode(), bcrypt.gensalt()),
                        "first_login": False
                    }}
                )
                st.success("Password set. Login again.")
                st.stop()
        else:
            pwd = st.text_input("Password", type="password")
            if st.button("Login"):
                if bcrypt.checkpw(pwd.encode(), user["password_hash"]):
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Invalid password")
    st.stop()

# ================= CONTEXT =================
user = st.session_state.user
is_nc = user["role"] == "nc"

menu = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Tasks", "Daily Activity", "Leave", "Logout"]
)

# ================= DASHBOARD =================
if menu == "Dashboard":
    st.title("📊 Dashboard")

    if is_nc:
        d = st.date_input("Select Date", today)
        dt = to_utc(d)
        logs = list(activity_col.find({"date": dt}))
        st.dataframe(pd.DataFrame(logs)) if logs else st.info("No activity")

    else:
        logs = list(activity_col.find({"user": user["email"]}))
        st.dataframe(pd.DataFrame(logs)) if logs else st.info("No activity yet")

# ================= TASKS =================
elif menu == "Tasks":
    st.title("📝 Tasks")

    title = st.text_input("Title *")
    desc = st.text_area("Description *")
    start = st.date_input("Start Date *")
    end = st.date_input("End Date *")

    assigned = st.text_input("Assign To (Email) *") if is_nc else user["email"]

    if st.button("Create Task"):
        if title and desc and assigned:
            tasks_col.insert_one({
                "title": title,
                "description": desc,
                "start_date": to_utc(start),
                "end_date": to_utc(end),
                "assigned_to": assigned,
                "status": "To Do"
            })
            st.success("Task created")

# ================= DAILY ACTIVITY =================
elif menu == "Daily Activity":
    st.title("🗓️ Daily Activity Log")

    if is_nc:
        st.info("NCs monitor only")
        st.stop()

    d = st.date_input("Date", today, min_value=editable_from, max_value=today)
    dt = to_utc(d)

    if leave_col.find_one({"user": user["email"], "date": dt, "status": "Approved"}):
        st.warning("On leave")
        st.stop()

    tasks = list(tasks_col.find({"assigned_to": user["email"]}))
    task_map = {t["title"]: t["_id"] for t in tasks}

    activity_type = st.selectbox("Activity Type", ["Task Work", "Call", "Meeting"])
    task = st.selectbox("Related Task *", list(task_map.keys()))

    payload = {}

    if activity_type == "Task Work":
        payload["status"] = st.selectbox("Task Status", TASK_STATUS)
        payload["work"] = st.text_area("Work Done *")

    elif activity_type == "Call":
        payload["call_type"] = st.selectbox("Call Type", CALL_TYPES)
        payload["state"] = st.text_input("State")
        payload["notes"] = st.text_area("Call Notes *")

    elif activity_type == "Meeting":
        payload["scope"] = st.selectbox("Meeting Scope", MEETING_SCOPE)
        payload["mode"] = st.selectbox("Mode", ["Online", "Offline"])
        payload["mom"] = st.text_area("MOM *")

    if st.button("Add Activity"):
        if all(payload.values()):
            activity_col.insert_one({
                "user": user["email"],
                "date": dt,
                "activity_type": activity_type,
                "task_id": task_map[task],
                "payload": payload,
                "created_at": datetime.now(timezone.utc)
            })
            st.success("Activity logged")

# ================= LEAVE =================
elif menu == "Leave":
    st.title("🌴 Leave")

    if not is_nc:
        d = st.date_input("Leave Date")
        reason = st.text_area("Reason")
        if st.button("Apply Leave") and reason:
            leave_col.insert_one({
                "user": user["email"],
                "date": to_utc(d),
                "reason": reason,
                "status": "Pending"
            })
            st.success("Leave applied")

    else:
        for l in leave_col.find({"status": "Pending"}):
            if st.button(f"Approve {l['user']} - {l['date']}"):
                leave_col.update_one({"_id": l["_id"]}, {"$set": {"status": "Approved"}})
                st.success("Approved")

# ================= LOGOUT =================
elif menu == "Logout":
    st.session_state.user = None
    st.rerun()
