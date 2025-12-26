import streamlit as st
import pandas as pd
from datetime import date, datetime
from pymongo import MongoClient
import bcrypt
import yagmail

from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

# =====================================================
# DB
# =====================================================
client = MongoClient(st.secrets["mongo"]["uri"])
db = client["nc_ops"]

users_col = db.users
tasks_col = db.tasks
logs_col = db.work_logs
leaves_col = db.leaves

# =====================================================
# EMAIL CONFIG
# =====================================================
NC_EMAILS = dict(st.secrets["nc_emails"])
MGMT_EMAILS = dict(st.secrets["mgmt_emails"])
OFFICIAL_NC_EMAIL = st.secrets["email"]["user"]

yag = yagmail.SMTP(
    st.secrets["email"]["user"],
    st.secrets["email"]["password"]
)

def send_email(to, subject, body, cc=None):
    yag.send(to=to, subject=subject, contents=body, cc=cc)

# =====================================================
# LLM (ChatGroq – LCEL)
# =====================================================
llm = ChatGroq(
    api_key=st.secrets["groq"]["api_key"],
    model="llama3-70b-8192",
    temperature=0.2
)

summary_prompt = PromptTemplate.from_template("""
You are a National Coordinator reviewing daily work.

Summarize the work done today by {name}.

Focus on:
- Tasks
- Calls
- Meetings
- Status changes
- Risks or delays

Logs:
{logs}

Return concise bullet points.
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
# LOGIN / FIRST LOGIN
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
                            "updated_at": datetime.utcnow()
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
        st.dataframe(pd.DataFrame(tasks)) if tasks else st.info("No tasks")

        st.subheader("📌 Daily Work Logs")
        logs = list(logs_col.find({}, {"_id": 0}))
        st.dataframe(pd.DataFrame(logs)) if logs else st.info("No logs yet")

        st.divider()
        st.subheader("🧠 AI Daily Summary")

        review_date = str(st.date_input("Review Date", date.today()))

        if st.button("Generate & Email Summary"):
            day_logs = list(logs_col.find({"date": review_date}, {"_id": 0}))
            df = pd.DataFrame(day_logs)

            summaries = []

            for key, email in MGMT_EMAILS.items():
                name = key.replace("_", " ")
                mlogs = df[df["user_email"] == email]

                if not mlogs.empty:
                    summary = summary_chain.invoke({
                        "name": name,
                        "logs": mlogs.to_dict(orient="records")
                    }).content

                    send_email(
                        to=email,
                        subject=f"[Your Daily Summary] {review_date}",
                        body=summary
                    )

                    summaries.append(f"{name}\n{summary}")

            if summaries:
                send_email(
                    to=list(NC_EMAILS.values()),
                    subject=f"[Daily Ops Summary] {review_date}",
                    body="\n\n".join(summaries),
                    cc=OFFICIAL_NC_EMAIL
                )

                st.success("Daily summaries emailed")
            else:
                st.info("No logs to summarize")

    else:
        st.subheader("📋 My Tasks")
        my_tasks = list(tasks_col.find(
            {"assigned_to_email": user_email},
            {"_id": 0}
        ))
        st.dataframe(pd.DataFrame(my_tasks)) if my_tasks else st.info("No tasks assigned")

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
        assigned_name = assignee_key.replace("_", " ")
        reporters = list(NC_EMAILS.values())
    else:
        assigned_email = user_email
        assigned_name = user_name
        reporters = list(NC_EMAILS.values())

    if st.button("Create Task"):
        tasks_col.insert_one({
            "title": title,
            "description": desc,
            "assigned_to_email": assigned_email,
            "assigned_to_name": assigned_name,
            "reporting_nc_emails": reporters,
            "start_date": str(start),
            "end_date": str(end),
            "status": "To Do",
            "created_by_email": user_email
        })

        send_email(
            to=assigned_email,
            subject=f"[Task Assigned] {title}",
            body=f"{desc}\n\nStart: {start}\nEnd: {end}",
            cc=reporters
        )

        st.success("Task created & email sent")

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

    task_title = st.selectbox("Task", task_map.keys())
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
            "created_at": datetime.utcnow()
        })

        if new_status != "No Change":
            tasks_col.update_one(
                {"title": task_title},
                {"$set": {"status": new_status}}
            )

        reporters = task_map[task_title]["reporting_nc_emails"]

        send_email(
            to=reporters,
            subject=f"[Daily Update] {user_name} | {task_title}",
            body=details,
            cc=user_email
        )

        st.success("Work logged & email sent")

# =====================================================
# LEAVE
# =====================================================
elif menu == "Leave":
    st.header("🌴 Leave")

    if role == "management":
        leave_type = st.selectbox("Leave Type", ["CL", "SL", "COURSE"])
        leave_date = st.date_input("Leave Date")
        reason = st.text_area("Reason")

        if st.button("Apply Leave"):
            leaves_col.insert_one({
                "user_email": user_email,
                "user_name": user_name,
                "leave_type": leave_type,
                "date": str(leave_date),
                "reason": reason,
                "status": "Pending"
            })

            send_email(
                to=list(NC_EMAILS.values()),
                subject=f"[Leave Request] {user_name}",
                body=reason,
                cc=user_email
            )

            st.success("Leave applied & emailed")
