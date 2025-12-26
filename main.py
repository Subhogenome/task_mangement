import streamlit as st
import pandas as pd
from datetime import date
from pymongo import MongoClient

from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

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
# MONGO
# =====================================================
client = MongoClient(st.secrets["mongo"])
db = client["nc_ops"]

tasks_col = db.tasks
logs_col = db.work_logs
leaves_col = db.leaves

# =====================================================
# LLM (CHATGROQ)
# =====================================================
llm = ChatGroq(
    api_key=st.secrets["api_key"],
    model_name="llama3-70b-8192",
    temperature=0.2
)

summary_prompt = PromptTemplate(
    input_variables=["name", "logs"],
    template="""
You are a National Coordinator reviewing daily work.

Summarize the work done today by {name}.
Be professional, concise, and structured.

Focus on:
- Tasks worked on
- Calls (who was called, role, outcome)
- Meetings (type and outcome)
- Task status changes
- Risks, delays, or follow-ups

Work logs:
{logs}

Return a clear bullet-point summary.
"""
)

summary_chain = LLMChain(llm=llm, prompt=summary_prompt)

# =====================================================
# APP CONFIG
# =====================================================
st.set_page_config("Task, Leave & AI Review System", layout="wide")
st.title("🧩 Task, Work Log, Leave & AI Review System")

# =====================================================
# ROLE SELECTION
# =====================================================
st.sidebar.header("Select Role")
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
        # ---------- TASKS ----------
        st.subheader("📋 All Tasks")
        tasks = list(tasks_col.find({}, {"_id": 0}))
        if tasks:
            st.dataframe(pd.DataFrame(tasks))
        else:
            st.info("No tasks created")

        # ---------- WORK LOGS ----------
        st.subheader("📌 Live Work Logs")
        logs = list(logs_col.find({}, {"_id": 0}))
        if logs:
            st.dataframe(pd.DataFrame(logs))
        else:
            st.info("No logs yet")

        # ---------- ON LEAVE ----------
        st.subheader("🌴 On Leave Today")
        today = str(date.today())
        on_leave = list(leaves_col.find(
            {"date": today, "status": "Approved"}, {"_id": 0}
        ))
        if on_leave:
            st.dataframe(pd.DataFrame(on_leave))
        else:
            st.info("No one on leave today")

        # =================================================
        # 🤖 AI DAILY REVIEW (CHATGROQ)
        # =================================================
        st.divider()
        st.subheader("🧠 AI Daily Management Review")

        review_date = st.date_input("Select Review Date", date.today())
        review_date_str = str(review_date)

        if st.button("🚀 Generate Daily Summary"):
            day_logs = list(logs_col.find(
                {"date": review_date_str},
                {"_id": 0}
            ))

            if not day_logs:
                st.warning("No logs found for this date")
            else:
                df = pd.DataFrame(day_logs)
                consolidated = []

                st.markdown("## 👤 Individual Summaries")

                for member in MANAGEMENT:
                    member_logs = df[df["user"] == member]

                    if member_logs.empty:
                        summary = f"**{member}:** No activity logged."
                    else:
                        logs_text = member_logs.to_dict(orient="records")
                        summary = summary_chain.run(
                            name=member,
                            logs=logs_text
                        )

                    consolidated.append(f"### {member}\n{summary}")
                    st.markdown(consolidated[-1])

                st.divider()
                st.markdown("## 📧 Consolidated NC Summary")

                final_summary = "\n\n".join(consolidated)
                st.text_area(
                    "Email-ready summary",
                    final_summary,
                    height=400
                )

    # =================================================
    # MANAGEMENT DASHBOARD
    # =================================================
    else:
        st.subheader("📋 My Tasks")
        my_tasks = list(tasks_col.find({"assigned_to": user}, {"_id": 0}))
        if my_tasks:
            st.dataframe(pd.DataFrame(my_tasks))
        else:
            st.info("No tasks assigned")

        st.subheader("🌴 My Leave Balance")
        used = {}
        for l in leaves_col.find({"user": user, "status": "Approved"}):
            used[l["leave_type"]] = used.get(l["leave_type"], 0) + 1

        balance = {
            k: LEAVE_TYPES[k] - used.get(k, 0)
            for k in LEAVE_TYPES
        }
        st.table(pd.DataFrame(balance.items(), columns=["Leave Type", "Remaining"]))

# =====================================================
# CREATE TASK
# =====================================================
elif menu == "Create Task":
    st.header("📝 Create Task")

    title = st.text_input("Task Title *")
    desc = st.text_area("Task Description *")

    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start Date *", min_value=date.today())
    end_date = col2.date_input("End Date *", min_value=start_date)

    if role == "NC":
        assigned_to = st.selectbox("Assign to Management", MANAGEMENT)
        reporting_ncs = st.multiselect("Reporting NC(s)", NCS, default=[user])
    else:
        assigned_to = user
        reporting_ncs = st.multiselect("Reporting NC(s)", NCS)

    if st.button("Create Task"):
        if not title or not desc or not reporting_ncs:
            st.error("All fields are mandatory")
        else:
            tasks_col.insert_one({
                "title": title,
                "description": desc,
                "assigned_to": assigned_to,
                "reporting_ncs": reporting_ncs,
                "start_date": str(start_date),
                "end_date": str(end_date),
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
        st.error("You are on approved leave today")
        st.stop()

    my_tasks = list(tasks_col.find({"assigned_to": user}))
    if not my_tasks:
        st.warning("No tasks assigned")
        st.stop()

    task_map = {t["title"]: t for t in my_tasks}
    selected_task = st.selectbox("Task", task_map.keys())
    task_doc = task_map[selected_task]

    st.info(
        f"🗓 {task_doc['start_date']} → {task_doc['end_date']} | "
        f"Current Status: {task_doc['status']}"
    )

    activity_type = st.selectbox(
        "Activity Type", ["Task Work", "Call", "Meeting", "Other"]
    )

    new_status = st.selectbox(
        "🔄 Update Task Status (optional)",
        ["No Change"] + TASK_STATUS
    )

    log = {
        "date": today,
        "user": user,
        "task": selected_task,
        "activity_type": activity_type
    }

    if activity_type == "Task Work":
        log["details"] = st.text_area("Work Done *")

    elif activity_type == "Call":
        log["called_person_name"] = st.text_input("Person Called (Name) *")
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
        log["details"] = st.text_area("Work Description *")

    if st.button("Submit Daily Log"):
        if not log.get("details"):
            st.error("Details are mandatory")
        else:
            if new_status != "No Change":
                tasks_col.update_one(
                    {"title": selected_task},
                    {"$set": {"status": new_status}}
                )
                log["updated_task_status"] = new_status

            logs_col.insert_one(log)
            st.success("Daily work logged")

# =====================================================
# LEAVE MANAGEMENT
# =====================================================
elif menu == "Leave":
    st.header("🌴 Leave Management")

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
            st.error("Leave balance exhausted")

        if st.button("Apply Leave"):
            leaves_col.insert_one({
                "user": user,
                "leave_type": leave_type,
                "date": str(leave_date),
                "reason": reason,
                "status": "Pending",
                "action_by": "",
                "action_reason": ""
            })
            st.success("Leave applied")

    else:
        pending = list(leaves_col.find({"status": "Pending"}))
        if not pending:
            st.info("No pending requests")

        for idx, l in enumerate(pending):
            with st.expander(f"{l['user']} – {l['leave_type']} – {l['date']}"):
                st.write("Reason:", l["reason"])
                rej_reason = st.text_input("Rejection Reason", key=idx)

                c1, c2 = st.columns(2)
                if c1.button("Approve", key=f"a{idx}"):
                    leaves_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {"status": "Approved", "action_by": user}}
                    )
                    st.success("Approved")

                if c2.button("Reject", key=f"r{idx}"):
                    leaves_col.update_one(
                        {"_id": l["_id"]},
                        {"$set": {
                            "status": "Rejected",
                            "action_by": user,
                            "action_reason": rej_reason
                        }}
                    )
                    st.warning("Rejected")
