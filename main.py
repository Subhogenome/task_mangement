import streamlit as st
import pandas as pd
from datetime import date
from pymongo import MongoClient

from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

# =====================================================
# USERS (POC)
# =====================================================
NCS = ["Kunal", "Subhodeep", "Rishabh"]
MANAGEMENT = ["Akshay", "Vatsal", "Narendra"]

CALL_WITH = ["NC", "SC", "AC", "DC", "Other"]
MEETING_WITH = ["NC", "SC", "AC", "DC"]
OTHER_WORK_TYPES = [
    "Documentation", "Coordination", "Planning",
    "Review", "Content Creation", "Other"
]

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
# UI CONFIG
# =====================================================
st.set_page_config("Task & AI Review System", layout="wide")
st.title("🧩 Task, Work Log, Leave & AI Review System")

# =====================================================
# ROLE SELECTION
# =====================================================
st.sidebar.header("Role Selection")
role = st.sidebar.selectbox("Role", ["NC", "Management"])

user = (
    st.sidebar.selectbox("NC Name", NCS)
    if role == "NC"
    else st.sidebar.selectbox("Management Name", MANAGEMENT)
)

menu = st.sidebar.radio(
    "Menu",
    ["Dashboard", "Create Task", "Daily Work Log", "Leave"]
)

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":
    st.header("📊 Dashboard")

    if role == "NC":
        st.subheader("📋 All Tasks")
        tasks = list(tasks_col.find({}, {"_id": 0}))
        if tasks:
            st.dataframe(pd.DataFrame(tasks))
        else:
            st.info("No tasks")

        st.subheader("📌 Live Work Logs")
        logs = list(logs_col.find({}, {"_id": 0}))
        if logs:
            st.dataframe(pd.DataFrame(logs))
        else:
            st.info("No logs yet")

        st.subheader("🌴 On Leave Today")
        today = str(date.today())
        on_leave = list(leaves_col.find(
            {"date": today, "status": "Approved"},
            {"_id": 0}
        ))
        if on_leave:
            st.dataframe(pd.DataFrame(on_leave))
        else:
            st.info("No one on leave")

        # ================= AI REVIEW =================
        st.divider()
        st.subheader("🧠 AI Daily Management Review")

        review_date = st.date_input("Review Date", date.today())
        review_date = str(review_date)

        if st.button("🚀 Generate Daily Summary"):
            day_logs = list(logs_col.find({"date": review_date}, {"_id": 0}))

            if not day_logs:
                st.warning("No logs found")
            else:
                df = pd.DataFrame(day_logs)
                summaries = []

                for member in MANAGEMENT:
                    member_logs = df[df["user"] == member]

                    if member_logs.empty:
                        text = f"{member}: No activity logged."
                    else:
                        response = summary_chain.invoke({
                            "name": member,
                            "logs": member_logs.to_dict(orient="records")
                        })
                        text = f"{member}:\n{response.content}"

                    summaries.append(text)
                    st.markdown(f"### {text}")

                st.divider()
                st.text_area(
                    "📧 Consolidated Summary (Email Ready)",
                    "\n\n".join(summaries),
                    height=350
                )

    else:
        st.subheader("📋 My Tasks")
        my_tasks = list(tasks_col.find({"assigned_to": user}, {"_id": 0}))
        if my_tasks:
            st.dataframe(pd.DataFrame(my_tasks))
        else:
            st.info("No tasks")

        st.subheader("🌴 Leave Balance")
        used = {}
        for l in leaves_col.find({"user": user, "status": "Approved"}):
            used[l["leave_type"]] = used.get(l["leave_type"], 0) + 1

        balance = {k: LEAVE_TYPES[k] - used.get(k, 0) for k in LEAVE_TYPES}
        st.table(pd.DataFrame(balance.items(), columns=["Type", "Remaining"]))

# =====================================================
# CREATE TASK
# =====================================================
elif menu == "Create Task":
    st.header("📝 Create Task")

    title = st.text_input("Task Title *")
    desc = st.text_area("Description *")

    c1, c2 = st.columns(2)
    start = c1.date_input("Start Date *", min_value=date.today())
    end = c2.date_input("End Date *", min_value=start)

    if role == "NC":
        assigned_to = st.selectbox("Assign To", MANAGEMENT)
        reporting_ncs = st.multiselect("Reporting NCs", NCS, default=[user])
    else:
        assigned_to = user
        reporting_ncs = st.multiselect("Reporting NCs", NCS)

    if st.button("Create Task"):
        if not title or not desc or not reporting_ncs:
            st.error("All fields mandatory")
        else:
            tasks_col.insert_one({
                "title": title,
                "description": desc,
                "assigned_to": assigned_to,
                "reporting_ncs": reporting_ncs,
                "start_date": str(start),
                "end_date": str(end),
                "status": "To Do",
                "created_by": user
            })
            st.success("Task created")

# =====================================================
# DAILY WORK LOG
# =====================================================
elif menu == "Daily Work Log":
    st.header("📅 Daily Work Log")

    if role != "Management":
        st.info("Only management can log work")
        st.stop()

    today = str(date.today())

    if leaves_col.find_one({"user": user, "date": today, "status": "Approved"}):
        st.error("On approved leave")
        st.stop()

    tasks = list(tasks_col.find({"assigned_to": user}))
    if not tasks:
        st.warning("No tasks assigned")
        st.stop()

    task_map = {t["title"]: t for t in tasks}
    task = st.selectbox("Task", task_map.keys())
    task_doc = task_map[task]

    st.info(f"{task_doc['start_date']} → {task_doc['end_date']} | Status: {task_doc['status']}")

    activity_type = st.selectbox("Activity Type", ["Task Work", "Call", "Meeting", "Other"])
    new_status = st.selectbox("Update Task Status (optional)", ["No Change"] + TASK_STATUS)

    log = {
        "date": today,
        "user": user,
        "task": task,
        "activity_type": activity_type
    }

    if activity_type == "Task Work":
        log["details"] = st.text_area("Work Done *")

    elif activity_type == "Call":
        log["called_person_name"] = st.text_input("Person Called *")
        log["call_with"] = st.selectbox("Call With", CALL_WITH)
        log["state"] = st.text_input("State")
        log["details"] = st.text_area("Call Notes *")

    elif activity_type == "Meeting":
        log["meeting_with"] = st.selectbox("Meeting With", MEETING_WITH)
        log["mode"] = st.selectbox("Mode", ["Online", "Offline"])
        log["state"] = st.text_input("State")
        log["details"] = st.text_area("MOM *")

    else:
        log["work_category"] = st.selectbox("Work Category", OTHER_WORK_TYPES)
        log["state"] = st.text_input("State")
        log["details"] = st.text_area("Description *")

    if st.button("Submit Log"):
        if not log.get("details"):
            st.error("Details required")
        else:
            if new_status != "No Change":
                tasks_col.update_one(
                    {"title": task},
                    {"$set": {"status": new_status}}
                )
                log["updated_task_status"] = new_status

            logs_col.insert_one(log)
            st.success("Work logged")

# =====================================================
# LEAVE
# =====================================================
elif menu == "Leave":
    st.header("🌴 Leave")

    if role == "Management":
        leave_type = st.selectbox("Leave Type", LEAVE_TYPES.keys())
        leave_date = st.date_input("Leave Date", min_value=date.today())
        reason = st.text_area("Reason *")

        used = leaves_col.count_documents({
            "user": user,
            "leave_type": leave_type,
            "status": "Approved"
        })

        if used >= LEAVE_TYPES[leave_type]:
            st.error("Leave exhausted")

        if st.button("Apply Leave"):
            leaves_col.insert_one({
                "user": user,
                "leave_type": leave_type,
                "date": str(leave_date),
                "reason": reason,
                "status": "Pending"
            })
            st.success("Leave applied")

    else:
        pending = list(leaves_col.find({"status": "Pending"}))
        if not pending:
            st.info("No pending leaves")

        for i, l in enumerate(pending):
            with st.expander(f"{l['user']} – {l['leave_type']} – {l['date']}"):
                if st.button("Approve", key=f"a{i}"):
                    leaves_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {"status": "Approved"}}
                    )
                    st.success("Approved")

                if st.button("Reject", key=f"r{i}"):
                    leaves_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {"status": "Rejected"}}
                    )
                    st.warning("Rejected")
