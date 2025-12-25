import streamlit as st
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta
import bcrypt
import pandas as pd
from bson import ObjectId

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Task • Delivery • Performance System", layout="wide")

ROLE_NC = "NC"
ROLE_MGMT = "MANAGEMENT"

UPDATE_TYPES = ["Call", "Meeting", "Documentation", "Coordination", "Other"]
CALL_ROLES = ["NC", "DC", "AC", "Lead", "Other"]
MEETING_TYPES = ["Pan India", "State-level", "With DCs", "With NCs"]
MODES = ["Online", "Offline"]

LEAVE_LIMITS = {"CL": 15, "SL": 7, "Course": 7}

# =====================================================
# DB
# =====================================================
client = MongoClient(st.secrets["mongo"])
db = client["task_system"]

users = db.users
tasks = db.tasks
updates = db.task_updates
leaves = db.leave_requests
audit_logs = db.audit_logs
system_events = db.system_events

# =====================================================
# HELPERS
# =====================================================
def utcnow():
    return datetime.now(timezone.utc)

def log_event(actor, role, event, entity=None, entity_id=None, meta=None, outcome="SUCCESS"):
    system_events.insert_one({
        "actor": actor,
        "role": role,
        "event": event,
        "entity_type": entity,
        "entity_id": entity_id,
        "metadata": meta or {},
        "outcome": outcome,
        "timestamp": utcnow()
    })

def audit(actor, action, entity, entity_id, before, after):
    audit_logs.insert_one({
        "actor": actor,
        "action": action,
        "entity_type": entity,
        "entity_id": entity_id,
        "before": before,
        "after": after,
        "timestamp": utcnow()
    })

def within_days(dt, days):
    return (utcnow() - dt).days <= days

def leave_days(l):
    return (l["to_date"].date() - l["from_date"].date()).days + 1

def leave_balance(email):
    used = {k: 0 for k in LEAVE_LIMITS}
    for l in leaves.find({"user_email": email, "status": "APPROVED"}):
        used[l["leave_type"]] += leave_days(l)
    return {k: LEAVE_LIMITS[k] - used[k] for k in LEAVE_LIMITS}

def is_on_leave(email):
    return leaves.find_one({
        "user_email": email,
        "from_date": {"$lte": utcnow()},
        "to_date": {"$gte": utcnow()},
        "status": "APPROVED"
    }) is not None

def can_create_subtask(user, task):
    return (
        (user["role"] == ROLE_NC and task["created_by"] == user["email"]) or
        (user["role"] == ROLE_MGMT and task["assigned_to"] == user["email"])
    )

def delete_task_tree(task_id, actor):
    task = tasks.find_one({"_id": task_id})
    if not task:
        return
    for sub in tasks.find({"parent_task_id": task_id}):
        delete_task_tree(sub["_id"], actor)
    tasks.delete_one({"_id": task_id})
    audit(actor, "DELETE_TASK", "TASK", task_id, task, None)
    log_event(actor, ROLE_NC, "TASK_DELETED", "TASK", task_id)

# =====================================================
# AUTH
# =====================================================
def login():
    st.title("🔐 Secure Login")

    email = st.text_input("Email")
    pwd = st.text_input("Password", type="password")

    if st.button("Login"):
        user = users.find_one({"email": email})
        if not user:
            log_event(email, "UNKNOWN", "LOGIN_FAILED", outcome="FAILED")
            st.error("Invalid credentials")
            return

        if bcrypt.checkpw(pwd.encode(), user["password_hash"]):
            st.session_state.user = user
            log_event(email, user["role"], "LOGIN_SUCCESS")
            st.rerun()
        else:
            log_event(email, user["role"], "LOGIN_FAILED", outcome="FAILED")
            st.error("Invalid credentials")

if "user" not in st.session_state:
    login()
    st.stop()

user = st.session_state.user

# =====================================================
# SIDEBAR
# =====================================================
st.sidebar.success(f"{user['name']} ({user['role']})")
page = st.sidebar.radio(
    "Navigation",
    ["Tasks", "Daily Updates", "Leave", "NC Dashboard", "Performance", "Audit Logs"]
)

if st.sidebar.button("Logout"):
    log_event(user["email"], user["role"], "LOGOUT")
    st.session_state.clear()
    st.rerun()

# =====================================================
# TASKS + SUBTASKS
# =====================================================
if page == "Tasks":
    st.header("📌 Task & Subtask Management")

    with st.expander("➕ Create Task"):
        title = st.text_input("Title")
        desc = st.text_area("Description")
        assigned = st.text_input("Assign To (email)")
        start = st.date_input("Start")
        end = st.date_input("End")

        if st.button("Create"):
            if user["role"] == ROLE_MGMT and assigned != user["email"]:
                log_event(user["email"], user["role"], "PERMISSION_DENIED", "TASK", meta={"reason": "MGMT self-only"}, outcome="DENIED")
                st.error("Management can assign tasks only to themselves")
            else:
                doc = {
                    "title": title,
                    "description": desc,
                    "parent_task_id": None,
                    "assigned_to": assigned,
                    "reporting_ncs": [user["email"]] if user["role"] == ROLE_NC else [],
                    "status": "To Do",
                    "start_date": datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
                    "end_date": datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc),
                    "created_by": user["email"],
                    "created_at": utcnow()
                }
                res = tasks.insert_one(doc)
                audit(user["email"], "CREATE_TASK", "TASK", res.inserted_id, None, doc)
                log_event(user["email"], user["role"], "TASK_CREATED", "TASK", res.inserted_id)
                st.success("Task created")

    def render(task, level=0):
        pad = "—" * level
        with st.expander(f"{pad} {task['title']} → {task['assigned_to']}"):
            st.json(task)

            if can_create_subtask(user, task):
                with st.form(f"sub_{task['_id']}"):
                    t = st.text_input("Subtask title")
                    d = st.text_area("Description")
                    if st.form_submit_button("Add Subtask"):
                        doc = {
                            "title": t,
                            "description": d,
                            "parent_task_id": task["_id"],
                            "assigned_to": task["assigned_to"],
                            "reporting_ncs": task["reporting_ncs"],
                            "status": "To Do",
                            "start_date": task["start_date"],
                            "end_date": task["end_date"],
                            "created_by": user["email"],
                            "created_at": utcnow()
                        }
                        r = tasks.insert_one(doc)
                        audit(user["email"], "ADD_SUBTASK", "TASK", r.inserted_id, None, doc)
                        log_event(user["email"], user["role"], "SUBTASK_CREATED", "TASK", r.inserted_id)
                        st.rerun()

            if user["role"] == ROLE_NC and task["created_by"] == user["email"]:
                if st.button("🗑 Delete Task"):
                    delete_task_tree(task["_id"], user["email"])
                    st.rerun()

        for s in tasks.find({"parent_task_id": task["_id"]}):
            render(s, level + 1)

    for root in tasks.find({"parent_task_id": None}):
        render(root)

# =====================================================
# DAILY UPDATES
# =====================================================
if page == "Daily Updates":
    st.header("🗒 Daily Updates")

    if is_on_leave(user["email"]):
        log_event(user["email"], user["role"], "UPDATE_BLOCKED_LEAVE")
        st.warning("On approved leave. Updates disabled.")
        st.stop()

    my_tasks = list(tasks.find({"assigned_to": user["email"]}))
    task_map = {str(t["_id"]): t["title"] for t in my_tasks}

    task_id = st.selectbox("Task", task_map)
    utype = st.selectbox("Update Type", UPDATE_TYPES)

    call_meta = meeting_meta = None

    if utype == "Call":
        call_meta = {
            "person_name": st.text_input("Person"),
            "person_role": st.selectbox("Role", CALL_ROLES),
            "state": st.text_input("State"),
            "purpose": st.text_area("Purpose")
        }

    if utype == "Meeting":
        meeting_meta = {
            "meeting_type": st.selectbox("Type", MEETING_TYPES),
            "mode": st.selectbox("Mode", MODES),
            "mom": st.text_area("MOM")
        }

    if st.button("Log Update"):
        doc = {
            "task_id": ObjectId(task_id),
            "update_type": utype,
            "logged_by": user["email"],
            "logged_at": utcnow(),
            "call_meta": call_meta,
            "meeting_meta": meeting_meta
        }
        r = updates.insert_one(doc)
        audit(user["email"], "ADD_UPDATE", "TASK_UPDATE", r.inserted_id, None, doc)
        log_event(user["email"], user["role"], "UPDATE_LOGGED", "TASK_UPDATE", r.inserted_id)
        st.success("Update logged")

# =====================================================
# LEAVE
# =====================================================
if page == "Leave":
    st.header("🏖 Leave Management")

    bal = leave_balance(user["email"])
    st.json(bal)

    with st.expander("➕ Apply Leave"):
        ltype = st.selectbox("Type", list(LEAVE_LIMITS))
        f = st.date_input("From")
        t = st.date_input("To")
        days = (t - f).days + 1

        if st.button("Apply"):
            if days > bal[ltype]:
                log_event(user["email"], user["role"], "LEAVE_OVERUSE", outcome="DENIED")
                st.error("Insufficient balance")
            else:
                doc = {
                    "user_email": user["email"],
                    "leave_type": ltype,
                    "from_date": datetime.combine(f, datetime.min.time(), tzinfo=timezone.utc),
                    "to_date": datetime.combine(t, datetime.min.time(), tzinfo=timezone.utc),
                    "status": "PENDING",
                    "created_at": utcnow()
                }
                r = leaves.insert_one(doc)
                log_event(user["email"], user["role"], "LEAVE_APPLIED", "LEAVE", r.inserted_id)
                st.success("Leave applied")

    if user["role"] == ROLE_NC:
        for l in leaves.find({"status": "PENDING"}):
            st.json(l)
            reason = st.text_input(f"Rejection reason {l['_id']}")
            if st.button(f"Approve {l['_id']}"):
                leaves.update_one({"_id": l["_id"]}, {"$set": {"status": "APPROVED"}})
                audit(user["email"], "LEAVE_APPROVED", "LEAVE", l["_id"], l, None)
                log_event(user["email"], user["role"], "LEAVE_APPROVED", "LEAVE", l["_id"])
                st.rerun()
            if reason and st.button(f"Reject {l['_id']}"):
                leaves.update_one({"_id": l["_id"]}, {"$set": {"status": "REJECTED", "rejection_reason": reason}})
                audit(user["email"], "LEAVE_REJECTED", "LEAVE", l["_id"], l, {"reason": reason})
                log_event(user["email"], user["role"], "LEAVE_REJECTED", "LEAVE", l["_id"], {"reason": reason})
                st.rerun()

# =====================================================
# NC DASHBOARD
# =====================================================
if page == "NC Dashboard":
    if user["role"] != ROLE_NC:
        st.stop()
    log_event(user["email"], user["role"], "NC_DASHBOARD_VIEWED")
    df = pd.DataFrame(list(updates.find()))
    st.dataframe(df.sort_values("logged_at", ascending=False))

# =====================================================
# PERFORMANCE
# =====================================================
if page == "Performance":
    log_event(user["email"], user["role"], "PERFORMANCE_VIEWED")
    data = list(updates.find({"logged_by": user["email"]}))
    calls = sum(1 for d in data if d["update_type"] == "Call")
    meetings = sum(1 for d in data if d["update_type"] == "Meeting")
    missed = max(0, 22 - len(set(d["logged_at"].date() for d in data)))
    rating = "Good" if missed <= 2 else "Average" if missed <= 5 else "Poor"

    st.success(
        f"{user['name']} logged {len(data)} updates "
        f"({calls} calls, {meetings} meetings). "
        f"Missed {missed} days. Engagement: {rating}"
    )

# =====================================================
# AUDIT LOGS
# =====================================================
if page == "Audit Logs":
    if user["role"] != ROLE_NC:
        st.stop()
    log_event(user["email"], user["role"], "AUDIT_LOG_VIEWED")
    for a in audit_logs.find().sort("timestamp", -1):
        st.json(a)
