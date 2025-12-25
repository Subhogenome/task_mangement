import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import datetime, date, timedelta, timezone
from bson import ObjectId
import bcrypt

# =====================================================
# APP CONFIG
# =====================================================
st.set_page_config("NC Ops System", layout="wide")

MONGO_URI = st.secrets["mongo"]["uri"]
client = MongoClient(MONGO_URI)
db = client.nc_ops

users_col = db.users
tasks_col = db.tasks
updates_col = db.task_updates
leave_col = db.leave_requests
audit_col = db.audit_logs

# =====================================================
# INDEXES
# =====================================================
users_col.create_index("email", unique=True)
tasks_col.create_index("assigned_to")
tasks_col.create_index("parent_task_id")
updates_col.create_index([("task_id", 1), ("date", 1)])
leave_col.create_index("user")
audit_col.create_index("timestamp")

# =====================================================
# CONSTANTS
# =====================================================
SESSION_TIMEOUT_MIN = 45
UPDATE_TYPES = ["Call", "Meeting", "Work"]
LEAVE_LIMITS = {"CL": 15, "SL": 7}

# =====================================================
# HELPERS
# =====================================================
def utc_now():
    return datetime.now(timezone.utc)

def to_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

def mongo_docs_to_df(docs):
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    if "_id" in df.columns:
        df["_id"] = df["_id"].astype(str)
    return df

def audit(actor, action, entity, entity_id=None, before=None, after=None):
    audit_col.insert_one({
        "actor": actor,
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id) if entity_id else None,
        "before": before,
        "after": after,
        "timestamp": utc_now()
    })

def enforce_role(user, roles):
    if user["role"] not in roles:
        st.error("Unauthorized action")
        st.stop()

def session_valid(user):
    return utc_now() - user["last_active"] < timedelta(minutes=SESSION_TIMEOUT_MIN)

def update_parent_status(parent_id):
    children = list(tasks_col.find({"parent_task_id": parent_id}))
    if children and all(c["status"] == "Completed" for c in children):
        tasks_col.update_one(
            {"_id": parent_id},
            {"$set": {"status": "Completed", "completed_at": utc_now()}}
        )

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

    email = st.text_input("Email").strip().lower()
    user = users_col.find_one({"email": email, "active": True})

    if email and not user:
        st.error("User not registered")
        st.stop()

    if user:
        if user.get("first_login", True):
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
                audit(email, "SET_PASSWORD", "user", user["_id"])
                st.success("Password set. Login again.")
                st.stop()
        else:
            pwd = st.text_input("Password", type="password")
            if st.button("Login"):
                if bcrypt.checkpw(pwd.encode(), user["password_hash"]):
                    users_col.update_one(
                        {"_id": user["_id"]},
                        {"$set": {"last_active": utc_now()}}
                    )
                    user["last_active"] = utc_now()
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Invalid password")
    st.stop()

# =====================================================
# CONTEXT
# =====================================================
user = st.session_state.user
if not session_valid(user):
    st.session_state.user = None
    st.warning("Session expired")
    st.stop()

users_col.update_one({"_id": user["_id"]}, {"$set": {"last_active": utc_now()}})
is_nc = user["role"] == "nc"

menu = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Tasks", "Daily Update", "Leave", "Performance", "Logout"]
)

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":
    st.title("📡 Live Updates")
    df = mongo_docs_to_df(
        list(updates_col.find().sort("created_at", -1).limit(50))
    )
    if not df.empty:
        st.dataframe(df.drop(columns=["_id"], errors="ignore"))
    else:
        st.info("No updates yet")

# =====================================================
# TASKS
# =====================================================
elif menu == "Tasks":
    st.title("📝 Tasks & Subtasks")
    enforce_role(user, ["nc", "management"])

    parents = list(tasks_col.find({"parent_task_id": None}))
    parent_map = {"None": None, **{p["title"]: p["_id"] for p in parents}}

    parent = st.selectbox("Parent Task", parent_map.keys())
    title = st.text_input("Title")
    desc = st.text_area("Description")
    assigned = user["email"] if not is_nc else st.text_input("Assign To")

    if st.button("Create Task"):
        task = {
            "title": title,
            "description": desc,
            "assigned_to": assigned,
            "parent_task_id": parent_map[parent],
            "status": "To Do",
            "created_by": user["email"],
            "created_at": utc_now()
        }
        res = tasks_col.insert_one(task)
        audit(user["email"], "CREATE_TASK", "task", res.inserted_id, after=task)
        st.success("Task created")

    df = mongo_docs_to_df(
        list(tasks_col.find({"assigned_to": user["email"]}))
    )
    if not df.empty:
        st.dataframe(df.drop(columns=["_id"], errors="ignore"))

# =====================================================
# DAILY UPDATE
# =====================================================
elif menu == "Daily Update":
    st.title("📅 Daily Update")

    my_tasks = list(tasks_col.find({
        "assigned_to": user["email"],
        "status": {"$ne": "Completed"}
    }))

    if not my_tasks:
        st.info("No active tasks")
        st.stop()

    task_map = {t["title"]: t["_id"] for t in my_tasks}
    task = st.selectbox("Task", task_map.keys())
    update_type = st.selectbox("Update Type", UPDATE_TYPES)
    detail = st.text_area("Details")

    if st.button("Submit Update"):
        today_utc = to_utc(date.today())
        if updates_col.find_one({
            "user": user["email"],
            "task_id": task_map[task],
            "date": today_utc
        }):
            st.error("Update already logged today")
            st.stop()

        update = {
            "user": user["email"],
            "task_id": task_map[task],
            "update_type": update_type,
            "detail": detail,
            "date": today_utc,
            "created_at": utc_now()
        }
        updates_col.insert_one(update)
        tasks_col.update_one(
            {"_id": task_map[task]},
            {"$set": {"status": "Running"}}
        )

        t = tasks_col.find_one({"_id": task_map[task]})
        if t.get("parent_task_id"):
            update_parent_status(t["parent_task_id"])

        audit(user["email"], "LOG_UPDATE", "task", task_map[task], after=update)
        st.success("Update logged")

# =====================================================
# LEAVE
# =====================================================
elif menu == "Leave":
    st.title("🌴 Leave Management")

    approved = list(
        leave_col.find({"user": user["email"], "status": "Approved"})
    )

    used = {}
    for l in approved:
        lt = l.get("type")
        if lt:
            used[lt] = used.get(lt, 0) + l.get("days", 1)

    for lt, limit in LEAVE_LIMITS.items():
        st.write(f"{lt}: {limit - used.get(lt, 0)} remaining")

    if not is_nc:
        f = st.date_input("From")
        t = st.date_input("To")
        ltype = st.selectbox("Type", list(LEAVE_LIMITS))
        reason = st.text_area("Reason")

        if st.button("Apply"):
            leave = {
                "user": user["email"],
                "from": to_utc(f),
                "to": to_utc(t),
                "days": (t - f).days + 1,
                "type": ltype,
                "reason": reason,
                "status": "Pending"
            }
            leave_col.insert_one(leave)
            audit(user["email"], "APPLY_LEAVE", "leave", after=leave)
            st.success("Leave applied")

    if is_nc:
        for l in leave_col.find({"status": "Pending"}):
            with st.expander(l["user"]):
                rej = st.text_input("Rejection reason", key=str(l["_id"]))
                c1, c2 = st.columns(2)
                if c1.button("Approve", key="a"+str(l["_id"])):
                    leave_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {"status": "Approved", "approved_by": user["email"]}}
                    )
                    audit(user["email"], "APPROVE_LEAVE", "leave", l["_id"])
                if c2.button("Reject", key="r"+str(l["_id"])):
                    if not rej:
                        st.error("Reason required")
                        st.stop()
                    leave_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {
                            "status": "Rejected",
                            "approved_by": user["email"],
                            "rejection_reason": rej
                        }}
                    )
                    audit(user["email"], "REJECT_LEAVE", "leave", l["_id"])

# =====================================================
# PERFORMANCE
# =====================================================
elif menu == "Performance":
    st.title("📊 Performance")
    st.metric(
        "Tasks Completed",
        tasks_col.count_documents({
            "assigned_to": user["email"],
            "status": "Completed"
        })
    )
    st.metric(
        "Total Updates",
        updates_col.count_documents({"user": user["email"]})
    )

# =====================================================
# LOGOUT
# =====================================================
elif menu == "Logout":
    st.session_state.user = None
    st.rerun()
