import streamlit as st
import pandas as pd
from datetime import date, datetime, timezone
from pymongo import MongoClient
import bcrypt
import yagmail

from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

# =====================================================
# HELPERS
# =====================================================
def key_to_name(key: str) -> str:
    return key.replace("_", " ")

def name_to_key(name: str) -> str:
    return name.replace(" ", "_")

def utc_now():
    return datetime.now(timezone.utc)

# =====================================================
# DB
# =====================================================
client = MongoClient(st.secrets["mongo"])
db = client["nc_ops"]

users_col = db.users
tasks_col = db.tasks
logs_col = db.work_logs
leave_requests_col = db.leave_requests

# =====================================================
# EMAIL
# =====================================================
NC_EMAILS = dict(st.secrets["nc_emails"])
MGMT_EMAILS = dict(st.secrets["mgmt_emails"])
OFFICIAL_NC_EMAIL = st.secrets["of_email"]

yag = yagmail.SMTP(
    st.secrets["user"],
    st.secrets["password"]
)

def send_email(to, subject, body, cc=None):
    try:
        yag.send(to=to, subject=subject, contents=body, cc=cc)
    except Exception:
        st.warning("⚠️ Email could not be sent")

# =====================================================
# LLM
# =====================================================
llm = ChatGroq(
    api_key=st.secrets["api_key"],
    model="llama3-70b-8192",
    temperature=0.2
)

summary_prompt = PromptTemplate.from_template("""
Summarize today's work for {name}.

Cover:
- Tasks
- Calls / meetings
- Status changes
- Risks

Logs:
{logs}
""")

summary_chain = summary_prompt | llm

# =====================================================
# AUTH HELPERS
# =====================================================
def hash_pw(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt())

def verify_pw(pw, hashed):
    return bcrypt.checkpw(pw.encode(), hashed)

if "user" not in st.session_state:
    st.session_state.user = None

# =====================================================
# LOGIN
# =====================================================
if not st.session_state.user:
    st.title("🔐 Login")

    email = st.text_input("Email")
    user_doc = users_col.find_one({"email": email, "active": True}) if email else None

    if email and not user_doc:
        st.error("Unauthorized user")
        st.stop()

    if user_doc:
        if user_doc["first_login"]:
            p1 = st.text_input("Create Password", type="password")
            p2 = st.text_input("Confirm Password", type="password")

            if st.button("Set Password"):
                if not p1 or p1 != p2:
                    st.error("Passwords do not match")
                else:
                    users_col.update_one(
                        {"_id": user_doc["_id"]},
                        {"$set": {
                            "password_hash": hash_pw(p1),
                            "first_login": False,
                            "updated_at": utc_now()
                        }}
                    )
                    st.success("Password set. Please login again.")
                    st.stop()
        else:
            pwd = st.text_input("Password", type="password")
            if st.button("Login"):
                if verify_pw(pwd, user_doc["password_hash"]):
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
# CONTEXT
# =====================================================
current_user = st.session_state.user
user_email = current_user["email"]
user_name = current_user["name"]
role = current_user["role"]
user_key = name_to_key(user_name)

st.sidebar.markdown(
    f"**Logged in as**  \n{user_name}  \n({user_email})"
)

if st.sidebar.button("Logout"):
    st.session_state.user = None
    st.rerun()

menu = st.sidebar.radio(
    "Menu", ["Dashboard", "Create Task", "Daily Work Log", "Leave"]
)

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":
    st.header("📊 Dashboard")

    if role == "nc":
        st.subheader("📋 All Tasks")
        tasks = list(tasks_col.find({}, {"_id": 0}))
        if tasks:
            st.dataframe(pd.DataFrame(tasks))
        else:
            st.info("No tasks")

        st.subheader("📌 Daily Work Logs")
        logs = list(logs_col.find({}, {"_id": 0}))
        if logs:
            st.dataframe(pd.DataFrame(logs))
        else:
            st.info("No logs")

    else:
        st.subheader("📋 My Tasks")
        my_tasks = list(tasks_col.find({"assigned_to_email": user_email}, {"_id": 0}))
        if my_tasks:
            st.dataframe(pd.DataFrame(my_tasks))
        else:
            st.info("No tasks assigned")

# =====================================================
# CREATE TASK
# =====================================================
elif menu == "Create Task":
    st.header("📝 Create Task")

    title = st.text_input("Task Title")
    desc = st.text_area("Description")
    start = st.date_input("Start Date")
    end = st.date_input("End Date")

    if role == "nc":
        assignee_key = st.selectbox("Assign To", list(MGMT_EMAILS.keys()))
        assigned_email = MGMT_EMAILS[assignee_key]
        assigned_name = key_to_name(assignee_key)

        reporters = st.multiselect(
            "Reporting NCs",
            list(NC_EMAILS.keys()),
            default=[user_key] if user_key in NC_EMAILS else []
        )
    else:
        assigned_email = user_email
        assigned_name = user_name
        reporters = list(NC_EMAILS.keys())

    if st.button("Create Task"):
        tasks_col.insert_one({
            "title": title,
            "description": desc,
            "assigned_to_email": assigned_email,
            "assigned_to_name": assigned_name,
            "reporting_nc_keys": reporters,
            "reporting_nc_emails": [NC_EMAILS[k] for k in reporters],
            "start_date": str(start),
            "end_date": str(end),
            "status": "To Do",
            "created_by_email": user_email
        })

        send_email(
            to=assigned_email,
            subject=f"[Task Assigned] {title}",
            body=f"{desc}\nStart: {start}\nEnd: {end}",
            cc=[NC_EMAILS[k] for k in reporters]
        )

        st.success("Task created")

# =====================================================
# DAILY WORK LOG
# =====================================================
elif menu == "Daily Work Log":
    if role != "management":
        st.stop()

    today = str(date.today())
    tasks = list(tasks_col.find({"assigned_to_email": user_email}))
    task_map = {t["title"]: t for t in tasks}

    if not task_map:
        st.info("No tasks assigned")
        st.stop()

    task_title = st.selectbox("Task", list(task_map.keys()))
    details = st.text_area("Work Done")
    new_status = st.selectbox("Update Status", ["No Change", "To Do", "Running", "Done"])

    if st.button("Submit Log"):
        logs_col.insert_one({
            "date": today,
            "user_email": user_email,
            "user_name": user_name,
            "task_title": task_title,
            "details": details,
            "updated_status": new_status,
            "created_at": utc_now()
        })

        if new_status != "No Change":
            tasks_col.update_one(
                {"title": task_title},
                {"$set": {"status": new_status}}
            )

        send_email(
            to=task_map[task_title]["reporting_nc_emails"],
            subject=f"[Daily Update] {user_name} | {task_title}",
            body=details,
            cc=user_email
        )

        st.success("Work logged")

# =====================================================
# LEAVE (MANAGEMENT + NC REVIEW)
# =====================================================
elif menu == "Leave":
    st.header("🌴 Leave")

    if role == "management":
        leave_type = st.selectbox("Leave Type", ["CL", "SL", "COURSE"])
        leave_date = st.date_input("Leave Date")
        reason = st.text_area("Reason")

        if st.button("Apply Leave"):
            leave_requests_col.insert_one({
                "user_email": user_email,
                "user_name": user_name,
                "leave_type": leave_type,
                "date": str(leave_date),
                "reason": reason,
                "status": "Pending",
                "applied_at": utc_now()
            })

            send_email(
                to=list(NC_EMAILS.values()),
                subject=f"[Leave Request] {user_name} | {leave_type}",
                body=reason,
                cc=user_email
            )

            st.success("Leave applied")

    else:
        st.subheader("📥 Pending Leave Requests")
        pending = list(leave_requests_col.find({"status": "Pending"}))

        if not pending:
            st.info("No pending leave requests")
            st.stop()

        for leave in pending:
            with st.expander(f"{leave['user_name']} | {leave['leave_type']} | {leave['date']}"):
                st.write(f"**Reason:** {leave['reason']}")

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Approve", key=f"a_{leave['_id']}"):
                        leave_requests_col.update_one(
                            {"_id": leave["_id"]},
                            {"$set": {
                                "status": "Approved",
                                "reviewed_by": user_name,
                                "reviewed_at": utc_now()
                            }}
                        )
                        send_email(
                            to=leave["user_email"],
                            subject="[Leave Approved]",
                            body=f"Approved by {user_name}",
                            cc=list(NC_EMAILS.values())
                        )
                        st.rerun()

                with col2:
                    reject_reason = st.text_input("Reject reason", key=f"r_{leave['_id']}")
                    if st.button("Reject", key=f"rej_{leave['_id']}"):
                        leave_requests_col.update_one(
                            {"_id": leave["_id"]},
                            {"$set": {
                                "status": "Rejected",
                                "reviewed_by": user_name,
                                "reviewed_at": utc_now(),
                                "rejection_reason": reject_reason
                            }}
                        )
                        send_email(
                            to=leave["user_email"],
                            subject="[Leave Rejected]",
                            body=reject_reason,
                            cc=list(NC_EMAILS.values())
                        )
                        st.rerun()
