import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import date, timedelta, datetime, timezone
from bson.objectid import ObjectId
import bcrypt

# =====================================================
# HELPERS
# =====================================================
def to_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

def within_7_days(d):
    return d >= to_utc(date.today() - timedelta(days=6))

# =====================================================
# CONFIG
# =====================================================
MONGO_URI = st.secrets["mongo"]["uri"]
client = MongoClient(MONGO_URI)
db = client["nc_ops"]

users_col = db.users
tasks_col = db.tasks
updates_col = db.task_updates
leave_col = db.leave_requests

st.set_page_config("NC Task Management System", layout="wide")

# =====================================================
# CONSTANTS
# =====================================================
UPDATE_TYPES = ["Call", "Meeting", "Documentation", "Coordination", "Other"]
CALL_TYPES = ["SC", "DC", "Lead", "Other"]
MEETING_TYPES = ["Pan India", "State", "DCs", "NCs"]

LEAVE_LIMITS = {"CL": 15, "SL": 7, "COURSE": 7}

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

# =====================================================
# CONTEXT
# =====================================================
user = st.session_state.user
is_nc = user["role"] == "nc"

menu = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Tasks", "Daily Update", "Leave", "Logout"]
)

# =====================================================
# DASHBOARD (REAL-TIME)
# =====================================================
if menu == "Dashboard":
    st.title("📡 Live Task Updates")

    logs = list(updates_col.find().sort("created_at", -1).limit(100))
    if not logs:
        st.info("No updates yet")
    else:
        df = pd.DataFrame(logs)
        df["task"] = df["task_id"].astype(str)
        st.dataframe(df[["user", "update_type", "task", "detail", "created_at"]])

# =====================================================
# TASKS (TASK + SUBTASK)
# =====================================================
elif menu == "Tasks":
    st.title("📝 Task & Subtask Management")

    all_tasks = list(tasks_col.find())
    parent_map = {t["title"]: t["_id"] for t in all_tasks if t.get("parent_task_id") is None}

    parent = st.selectbox("Parent Task (optional)", ["None"] + list(parent_map.keys()))
    title = st.text_input("Task Title *")
    desc = st.text_area("Description *")
    start = st.date_input("Start Date")
    end = st.date_input("End Date")

    # 🔑 KEY REQUIREMENT MET HERE
    assigned = user["email"] if not is_nc else st.text_input("Assign To (Email)")
    reportees = st.multiselect(
        "Reporting NC(s)",
        [u["email"] for u in users_col.find({"role": "nc"})]
    )

    if st.button("Create Task"):
        tasks_col.insert_one({
            "title": title,
            "description": desc,
            "parent_task_id": None if parent == "None" else parent_map[parent],
            "assigned_to": assigned,
            "reporting_ncs": reportees,
            "status": "To Do",
            "start_date": to_utc(start),
            "end_date": to_utc(end),
            "created_by": user["email"],
            "created_at": datetime.now(timezone.utc)
        })
        st.success("Task created")

    st.subheader("📋 Existing Tasks")
    st.dataframe(pd.DataFrame(all_tasks))

# =====================================================
# DAILY UPDATE (STRUCTURED, EXPLICIT)
# =====================================================
elif menu == "Daily Update":
    st.title("📅 Daily Task Update")

    if leave_col.find_one({"user": user["email"], "date": to_utc(today), "status": "Approved"}):
        st.error("You are on approved leave today")
        st.stop()

    my_tasks = list(tasks_col.find({"assigned_to": user["email"]}))
    task_map = {t["title"]: t["_id"] for t in my_tasks}

    task = st.selectbox("Task / Subtask *", task_map.keys())
    update_type = st.selectbox("Update Type *", UPDATE_TYPES)

    detail = {}

    if update_type == "Call":
        detail["call_type"] = st.selectbox("Call With", CALL_TYPES)
        detail["summary"] = st.text_area("Call Summary *")

    elif update_type == "Meeting":
        detail["meeting_type"] = st.selectbox("Meeting Type", MEETING_TYPES)
        detail["mom"] = st.text_area("MOM *")

    else:
        detail["description"] = st.text_area("Work Description *")

    if st.button("Submit Update"):
        updates_col.insert_one({
            "user": user["email"],
            "task_id": task_map[task],
            "update_type": update_type,
            "detail": detail,
            "date": to_utc(today),
            "created_at": datetime.now(timezone.utc)
        })
        tasks_col.update_one(
            {"_id": task_map[task]},
            {"$set": {"status": "Running"}}
        )
        st.success("Update logged")

    st.subheader("✏️ Edit / Delete (Last 7 Days)")
    logs = list(updates_col.find({"user": user["email"], "date": {"$gte": to_utc(editable_from)}}))

    for l in logs:
        with st.expander(str(l["_id"])):
            st.json(l)
            if st.button("Delete", key=str(l["_id"])):
                updates_col.delete_one({"_id": l["_id"]})
                st.success("Deleted")
                st.rerun()

# =====================================================
# LEAVE (BALANCE + APPROVAL)
# =====================================================
elif menu == "Leave":
    st.title("🌴 Leave Management")

    # ---- BALANCE ----
    used = pd.DataFrame(
        list(leave_col.find({"user": user["email"], "status": "Approved"}))
    )["type"].value_counts().to_dict() if leave_col.count_documents({"user": user["email"]}) else {}

    st.subheader("Your Leave Balance")
    for lt, limit in LEAVE_LIMITS.items():
        st.write(f"{lt}: {limit - used.get(lt, 0)} remaining")

    # ---- APPLY ----
    if not is_nc:
        d = st.date_input("Leave Date")
        ltype = st.selectbox("Leave Type", list(LEAVE_LIMITS.keys()))
        reason = st.text_area("Reason")

        if st.button("Apply Leave"):
            leave_col.insert_one({
                "user": user["email"],
                "type": ltype,
                "date": to_utc(d),
                "reason": reason,
                "status": "Pending"
            })
            st.success("Leave applied")

    # ---- APPROVE / REJECT ----
    if is_nc:
        st.subheader("Pending Leave Requests")
        for l in leave_col.find({"status": "Pending"}):
            with st.expander(l["user"]):
                st.write(l)
                col1, col2 = st.columns(2)
                if col1.button("Approve", key=str(l["_id"])):
                    leave_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {"status": "Approved", "approved_by": user["email"]}}
                    )
                    st.success("Approved")
                if col2.button("Reject", key="rej"+str(l["_id"])):
                    leave_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {"status": "Rejected", "approved_by": user["email"]}}
                    )
                    st.warning("Rejected")

# =====================================================
# LOGOUT
# =====================================================
elif menu == "Logout":
    st.session_state.user = None
    st.rerun()
