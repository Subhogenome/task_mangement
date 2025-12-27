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
def utc_now():
    return datetime.now(timezone.utc)

def days_between(d1, d2):
    return (d2 - d1).days + 1

def key_to_name(k):
    return k.replace("_", " ")

def name_to_key(n):
    return n.replace(" ", "_")

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
        st.warning("⚠️ Email sending failed")

# =====================================================
# AI (ChatGroq)
# =====================================================
llm = ChatGroq(
    api_key=st.secrets["api_key"],
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0.2
)

# --- Log-based summary (existing) ---
summary_prompt = PromptTemplate.from_template("""
You are a National Coordinator.

Summarize the work done today by {name}.

Logs:
{logs}
""")

summary_chain = summary_prompt | llm

# --- Task-aware summary (NEW, added) ---
task_aware_prompt = PromptTemplate.from_template("""
You are a National Coordinator reviewing daily execution.

Person: {name}

ASSIGNED TASKS:
{tasks}

TODAY'S WORK LOGS:
{logs}

INSTRUCTIONS:
1. Identify which assigned tasks were worked on today.
2. Describe what was done.
3. Identify assigned tasks NOT worked on today.
4. Mention progress, delays, or risks.

Return under:
- ✅ Worked On Today
- ❌ Not Worked On
- ⚠️ Risks / Follow-ups
""")

task_aware_chain = task_aware_prompt | llm

# =====================================================
# AUTH
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
            st.subheader("Create Password")
            p1 = st.text_input("Password", type="password")
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
                    st.success("Password set. Login again.")
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
user = st.session_state.user
email = user["email"]
name = user["name"]
role = user["role"]
user_key = name_to_key(name)

st.sidebar.markdown(
    f"**{name}**  \n{email}  \nRole: `{role}`"
)

if st.sidebar.button("Logout"):
    st.session_state.user = None
    st.rerun()

# =====================================================
# SIDEBAR MENU (FIXED LOCATION)
# =====================================================
menu = st.sidebar.radio(
    "Menu",
    ["Dashboard", "Create Task", "Daily Work Log", "Leave"]
)

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":
    st.header("📊 Dashboard")

    # ---------------- NC DASHBOARD ----------------
    if role == "nc":
        review_date = st.date_input("Select Date", date.today())
        day_str = str(review_date)

        # --- Existing log-based summary ---
        st.subheader("🧠 AI Daily Summary (Log-based)")

        if st.button("Generate AI Summary"):
            logs = list(logs_col.find({"date": day_str}, {"_id": 0}))
            if not logs:
                st.warning("No work logs found")
            else:
                df = pd.DataFrame(logs)
                for key, mgmt_email in MGMT_EMAILS.items():
                    user_logs = df[df["user_email"] == mgmt_email]
                    if user_logs.empty:
                        continue

                    summary = summary_chain.invoke({
                        "name": key_to_name(key),
                        "logs": user_logs.to_dict(orient="records")
                    }).content

                    st.markdown(f"### {key_to_name(key)}")
                    st.write(summary)

        # --- Task-aware summary ---
        st.divider()
        st.subheader("🧠 AI Task-Aware Daily Review")

        if st.button("Generate Task-Aware Review"):
            for key, mgmt_email in MGMT_EMAILS.items():
                mgmt_name = key_to_name(key)

                assigned_tasks = list(
                    tasks_col.find(
                        {"assigned_to_email": mgmt_email},
                        {"_id": 0, "title": 1, "status": 1, "end_date": 1}
                    )
                )

                today_logs = list(
                    logs_col.find(
                        {"user_email": mgmt_email, "date": day_str},
                        {"_id": 0}
                    )
                )

                if not assigned_tasks and not today_logs:
                    continue

                summary = task_aware_chain.invoke({
                    "name": mgmt_name,
                    "tasks": assigned_tasks,
                    "logs": today_logs
                }).content

                st.markdown(f"### {mgmt_name}")
                st.write(summary)

                send_email(
                    to=mgmt_email,
                    subject=f"[AI Task Review] {mgmt_name} – {day_str}",
                    body=summary,
                    cc=OFFICIAL_NC_EMAIL
                )

        st.divider()
        st.subheader("📋 All Tasks")
        tasks = list(tasks_col.find({}, {"_id": 0}))
        if tasks:
            st.dataframe(pd.DataFrame(tasks))
        else:
            st.info("No tasks")

        st.subheader("📌 All Work Logs")
        logs = list(logs_col.find({}, {"_id": 0}))
        if logs:
            st.dataframe(pd.DataFrame(logs))
        else:
            st.info("No logs")

    # ---------------- MANAGEMENT DASHBOARD ----------------
    else:
        st.subheader("📋 My Tasks")
        my_tasks = list(tasks_col.find({"assigned_to_email": email}, {"_id": 0}))
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
        assigned_email = email
        assigned_name = name
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
            "created_by_email": email
        })
        st.success("Task created")

# =====================================================
# DAILY WORK LOG
# =====================================================
elif menu == "Daily Work Log":
    if role != "management":
        st.stop()

    tasks = list(tasks_col.find({"assigned_to_email": email}))
    titles = [t["title"] for t in tasks]

    if not titles:
        st.info("No tasks assigned")
        st.stop()

    task = st.selectbox("Task", titles)
    details = st.text_area("Work Done")
    status = st.selectbox("Status", ["To Do", "Running", "Done"])

    if st.button("Submit Log"):
        logs_col.insert_one({
            "date": str(date.today()),
            "user_email": email,
            "user_name": name,
            "task_title": task,
            "details": details,
            "status": status,
            "created_at": utc_now()
        })
        tasks_col.update_one({"title": task}, {"$set": {"status": status}})
        st.success("Work logged")

# =====================================================
# LEAVE / WFH
# =====================================================
elif menu == "Leave":
    st.header("🌴 Leave / WFH")

    if role == "management":
        mode = st.selectbox("Mode", ["Leave", "WFH"])
        leave_type = st.selectbox(
            "Type",
            ["CL", "SL", "COURSE"] if mode == "Leave" else ["WFH"]
        )
        start = st.date_input("From Date")
        end = st.date_input("To Date")
        days = days_between(start, end)
        reason = st.text_area("Reason")

        st.info(f"Total Days: {days}")

        if st.button("Apply"):
            leave_requests_col.insert_one({
                "user_email": email,
                "user_name": name,
                "mode": mode,
                "leave_type": leave_type,
                "from_date": str(start),
                "to_date": str(end),
                "days": days,
                "reason": reason,
                "status": "Pending",
                "applied_at": utc_now()
            })
            st.success("Leave / WFH applied")

    else:
        st.subheader("📥 Pending Requests")
        pending = list(leave_requests_col.find({"status": "Pending"}))

        if not pending:
            st.info("No pending requests")
        else:
            for req in pending:
                with st.expander(
                    f"{req['user_name']} | {req['mode']} | {req['days']} days"
                ):
                    st.write(req)
