# --- imports & helpers stay SAME ---
import streamlit as st
import pandas as pd
from datetime import date, datetime, timezone
from pymongo import MongoClient
import bcrypt
import yagmail

from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

def utc_now():
    return datetime.now(timezone.utc)

def days_between(d1, d2):
    return (d2 - d1).days + 1

def key_to_name(k):
    return k.replace("_", " ")

def name_to_key(n):
    return n.replace(" ", "_")

# --- DB ---
client = MongoClient(st.secrets["mongo"])
db = client["nc_ops"]

users_col = db.users
tasks_col = db.tasks
logs_col = db.work_logs
leave_requests_col = db.leave_requests

# --- EMAIL ---
NC_EMAILS = dict(st.secrets["nc_emails"])
MGMT_EMAILS = dict(st.secrets["mgmt_emails"])
OFFICIAL_NC_EMAIL = st.secrets["of_email"]

yag = yagmail.SMTP(st.secrets["user"], st.secrets["password"])

def send_email(to, subject, body, cc=None):
    try:
        yag.send(to=to, subject=subject, contents=body, cc=cc)
    except Exception:
        st.warning("⚠️ Email sending failed")

# --- AI ---
llm = ChatGroq(
    api_key=st.secrets["api_key"],
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0.2
)

summary_prompt = PromptTemplate.from_template("""
You are a National Coordinator.

Summarize the work done today by {name}.

Logs:
{logs}
""")

summary_chain = summary_prompt | llm

# ✅ NEW TASK-AWARE PROMPT (ADDED)
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

# --- AUTH (unchanged) ---
def hash_pw(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt())

def verify_pw(pw, hashed):
    return bcrypt.checkpw(pw.encode(), hashed)

if "user" not in st.session_state:
    st.session_state.user = None

# --- LOGIN (unchanged) ---
# [LOGIN CODE EXACTLY SAME AS YOURS]

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":
    st.header("📊 Dashboard")

    if role == "nc":
        st.subheader("🧠 AI Daily Summary (Log-based)")

        review_date = st.date_input("Select Date", date.today())
        day_str = str(review_date)

        if st.button("Generate AI Summary"):
            logs = list(logs_col.find({"date": day_str}, {"_id": 0}))
            if not logs:
                st.warning("No logs")
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

        # =================================================
        # ✅ NEW: TASK-AWARE AI REVIEW
        # =================================================
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

        # --- Existing tables remain ---
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

    else:
        st.subheader("📋 My Tasks")
        my_tasks = list(tasks_col.find({"assigned_to_email": email}, {"_id": 0}))
        if my_tasks:
            st.dataframe(pd.DataFrame(my_tasks))
        else:
            st.info("No tasks assigned")
