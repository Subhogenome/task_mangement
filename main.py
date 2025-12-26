import streamlit as st
import pandas as pd
from datetime import date
from pymongo import MongoClient
import yagmail

from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

# =====================================================
# USERS & EMAILS
# =====================================================
NCS = ["Rishabh", "Kunal", "Subhodeep"]
MANAGEMENT = ["Akshay", "Vatsal", "Narendra"]

NC_EMAILS = {
    "Rishabh": "purohitrm@gmail.com",
    "Kunal": "kunaljgd@gmail.com",
    "Subhodeep": "chatterjeesubhodeep08@gmail.com"
}

MGMT_EMAILS = {
    "Narendra": "aolsm.rc2@srisripublications.com",
    "Akshay": "akshay@srisripublications.com",
    "Vatsal": "aolsm.rc1@srisripublications.com"
}

OFFICIAL_NC_EMAIL = "aolsm.nc@srisripublications.com"

CALL_WITH = ["NC", "SC", "AC", "DC", "Other"]
MEETING_WITH = ["NC", "SC", "AC", "DC"]
TASK_STATUS = ["To Do", "Running", "Done"]
LEAVE_TYPES = {"CL": 15, "SL": 7, "COURSE": 7}

# =====================================================
# DB
# =====================================================
client = MongoClient(st.secrets["mongo"])
db = client["nc_ops"]

tasks_col = db.tasks
logs_col = db.work_logs
leaves_col = db.leaves

# =====================================================
# EMAIL (YAGMAIL)
# =====================================================
yag = yagmail.SMTP(
    user=st.secrets["user"],
    password=st.secrets["password"]
)

def send_email(to, subject, body, cc=None):
    yag.send(to=to, subject=subject, contents=body, cc=cc)

# =====================================================
# LLM (ChatGroq – LCEL)
# =====================================================
llm = ChatGroq(
    api_key=st.secrets["api_key"],
    model="llama3-70b-8192",
    temperature=0.2
)

summary_prompt = PromptTemplate.from_template("""
You are a National Coordinator reviewing daily work.

Summarize the work done today by {name}.
Be concise, professional, and structured.

Cover:
- Tasks worked on
- Calls (who was called, role, outcome)
- Meetings (type and outcome)
- Task status changes
- Risks or follow-ups

Work logs:
{logs}

Return bullet points.
""")

summary_chain = summary_prompt | llm

# =====================================================
# UI
# =====================================================
st.set_page_config("NC Ops System", layout="wide")
st.title("🧩 NC Task, Work Log & AI Review System")

role = st.sidebar.selectbox("Role", ["NC", "Management"])
user = (
    st.sidebar.selectbox("NC Name", NCS)
    if role == "NC"
    else st.sidebar.selectbox("Management Name", MANAGEMENT)
)

menu = st.sidebar.radio(
    "Menu", ["Dashboard", "Create Task", "Daily Work Log", "Leave"]
)

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":

    if role == "NC":
        st.subheader("📋 All Tasks")
        st.dataframe(pd.DataFrame(list(tasks_col.find({}, {"_id": 0}))))

        st.subheader("📌 Live Logs")
        st.dataframe(pd.DataFrame(list(logs_col.find({}, {"_id": 0}))))

        st.divider()
        st.subheader("🧠 AI Daily Summary")

        review_date = str(st.date_input("Review Date", date.today()))

        if st.button("Generate & Email Summary"):
            day_logs = list(logs_col.find({"date": review_date}, {"_id": 0}))
            df = pd.DataFrame(day_logs)

            full_summary = []

            for m in MANAGEMENT:
                member_logs = df[df["user"] == m]
                if member_logs.empty:
                    summary = f"{m}: No activity."
                else:
                    summary = summary_chain.invoke({
                        "name": m,
                        "logs": member_logs.to_dict(orient="records")
                    }).content

                full_summary.append(f"{m}\n{summary}")

                # Send personal summary
                send_email(
                    to=MGMT_EMAILS[m],
                    subject=f"[Your Daily Work Summary] {review_date}",
                    body=summary
                )

            # Send consolidated to NCs
            send_email(
                to=list(NC_EMAILS.values()),
                cc=OFFICIAL_NC_EMAIL,
                subject=f"[Daily Ops Summary] {review_date}",
                body="\n\n".join(full_summary)
            )

            st.success("Daily summaries emailed")

# =====================================================
# CREATE TASK
# =====================================================
elif menu == "Create Task":
    title = st.text_input("Task Title")
    desc = st.text_area("Description")

    start = st.date_input("Start Date")
    end = st.date_input("End Date")

    if role == "NC":
        assigned_to = st.selectbox("Assign To", MANAGEMENT)
        reporters = st.multiselect("Reporting NCs", NCS, default=[user])
    else:
        assigned_to = user
        reporters = st.multiselect("Reporting NCs", NCS)

    if st.button("Create Task"):
        tasks_col.insert_one({
            "title": title,
            "description": desc,
            "assigned_to": assigned_to,
            "reporting_ncs": reporters,
            "start_date": str(start),
            "end_date": str(end),
            "status": "To Do",
            "created_by": user
        })

        send_email(
            to=MGMT_EMAILS.get(assigned_to),
            cc=[NC_EMAILS[n] for n in reporters],
            subject=f"[Task Assigned] {title}",
            body=f"""
Task: {title}
Description: {desc}
Start: {start}
End: {end}
Assigned To: {assigned_to}
Reporting NCs: {', '.join(reporters)}
Created By: {user}
"""
        )

        st.success("Task created & email sent")

# =====================================================
# DAILY WORK LOG
# =====================================================
elif menu == "Daily Work Log":
    if role != "Management":
        st.stop()

    today = str(date.today())
    tasks = list(tasks_col.find({"assigned_to": user}))

    task_map = {t["title"]: t for t in tasks}
    task = st.selectbox("Task", task_map.keys())

    activity = st.selectbox("Activity", ["Task Work", "Call", "Meeting", "Other"])
    details = st.text_area("Details")

    new_status = st.selectbox("Update Status", ["No Change"] + TASK_STATUS)

    if st.button("Submit Log"):
        log = {
            "date": today,
            "user": user,
            "task": task,
            "activity_type": activity,
            "details": details
        }

        if new_status != "No Change":
            tasks_col.update_one({"title": task}, {"$set": {"status": new_status}})
            log["updated_task_status"] = new_status

        logs_col.insert_one(log)

        reporters = task_map[task]["reporting_ncs"]

        send_email(
            to=[NC_EMAILS[n] for n in reporters],
            cc=MGMT_EMAILS[user],
            subject=f"[Daily Update][{user}] {task}",
            body=f"""
User: {user}
Task: {task}
Activity: {activity}

Details:
{details}

Status Update:
{new_status}
"""
        )

        st.success("Log saved & email sent")

# =====================================================
# LEAVE
# =====================================================
elif menu == "Leave":

    if role == "Management":
        leave_type = st.selectbox("Leave Type", LEAVE_TYPES.keys())
        leave_date = st.date_input("Leave Date")
        reason = st.text_area("Reason")

        if st.button("Apply Leave"):
            leaves_col.insert_one({
                "user": user,
                "leave_type": leave_type,
                "date": str(leave_date),
                "reason": reason,
                "status": "Pending"
            })

            send_email(
                to=list(NC_EMAILS.values()),
                cc=MGMT_EMAILS[user],
                subject=f"[Leave Request] {user} | {leave_type} | {leave_date}",
                body=reason
            )

            st.success("Leave applied & email sent")

    else:
        pending = list(leaves_col.find({"status": "Pending"}))
        for l in pending:
            with st.expander(f"{l['user']} | {l['leave_type']} | {l['date']}"):
                if st.button("Approve", key=l["_id"]):
                    leaves_col.update_one({"_id": l["_id"]}, {"$set": {"status": "Approved"}})
                    send_email(
                        to=MGMT_EMAILS[l["user"]],
                        cc=list(NC_EMAILS.values()),
                        subject=f"[Leave Approved] {l['leave_type']} | {l['date']}",
                        body="Approved"
                    )
