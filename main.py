import streamlit as st
import pandas as pd
from datetime import date

# =====================================================
# HARD-CODED USERS (POC)
# =====================================================
NCS = ["Kunal", "Subhodeep", "Rishabh"]
MANAGEMENT = ["Akshay", "Vatsal", "Narendra"]

CALL_WITH = ["NC", "SC", "AC", "DC", "Other"]
MEETING_WITH = ["NC", "SC", "AC", "DC"]
OTHER_WORK_TYPES = [
    "Documentation",
    "Coordination",
    "Planning",
    "Review",
    "Content Creation",
    "Other"
]

TASK_STATUS = ["To Do", "Running", "Done"]
LEAVE_TYPES = {"CL": 15, "SL": 7, "COURSE": 7}

# =====================================================
# SESSION STATE (IN-MEMORY DB)
# =====================================================
if "tasks" not in st.session_state:
    st.session_state.tasks = []

if "logs" not in st.session_state:
    st.session_state.logs = []

if "leaves" not in st.session_state:
    st.session_state.leaves = []

# =====================================================
# APP HEADER
# =====================================================
st.set_page_config("Task & Leave Management POC", layout="wide")
st.title("🧩 Task, Work Log & Leave Management – POC")

# =====================================================
# ROLE SELECTION
# =====================================================
st.sidebar.header("Select Role")
role = st.sidebar.selectbox("Role", ["NC", "Management"])

if role == "NC":
    user = st.sidebar.selectbox("NC Name", NCS)
else:
    user = st.sidebar.selectbox("Management Name", MANAGEMENT)

st.sidebar.divider()

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
        st.dataframe(pd.DataFrame(st.session_state.tasks)) if st.session_state.tasks else st.info("No tasks")

        st.subheader("📌 Live Work Updates")
        st.dataframe(pd.DataFrame(st.session_state.logs)) if st.session_state.logs else st.info("No logs")

        st.subheader("🌴 Who is on Leave Today")
        today = str(date.today())
        on_leave = [
            l for l in st.session_state.leaves
            if l["date"] == today and l["status"] == "Approved"
        ]
        st.dataframe(pd.DataFrame(on_leave)) if on_leave else st.info("No one on leave today")

    else:
        st.subheader("📋 My Tasks")
        my_tasks = [t for t in st.session_state.tasks if t["assigned_to"] == user]
        st.dataframe(pd.DataFrame(my_tasks)) if my_tasks else st.info("No tasks")

        st.subheader("🌴 My Leave Balance")
        used = pd.DataFrame(
            [l for l in st.session_state.leaves if l["user"] == user and l["status"] == "Approved"]
        )["leave_type"].value_counts().to_dict() if st.session_state.leaves else {}

        balance = {
            k: v - used.get(k, 0)
            for k, v in LEAVE_TYPES.items()
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
    with col1:
        start_date = st.date_input("Start Date *", min_value=date.today())
    with col2:
        end_date = st.date_input("End Date *", min_value=start_date)

    if role == "NC":
        assigned_to = st.selectbox("Assign to Management", MANAGEMENT)
        reporting_ncs = st.multiselect("Reporting NC(s)", NCS, default=[user])
    else:
        assigned_to = user
        reporting_ncs = st.multiselect("Reporting NC(s)", NCS)

    if st.button("Create Task"):
        st.session_state.tasks.append({
            "task_id": len(st.session_state.tasks) + 1,
            "title": title,
            "description": desc,
            "assigned_to": assigned_to,
            "reporting_ncs": ", ".join(reporting_ncs),
            "start_date": str(start_date),
            "end_date": str(end_date),
            "status": "To Do"
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
    if any(
        l for l in st.session_state.leaves
        if l["user"] == user and l["date"] == today and l["status"] == "Approved"
    ):
        st.error("You are on approved leave today")
        st.stop()

    my_tasks = [t for t in st.session_state.tasks if t["assigned_to"] == user]
    if not my_tasks:
        st.warning("No tasks assigned")
        st.stop()

    task_titles = {t["title"]: t for t in my_tasks}
    selected_task = st.selectbox("Task", task_titles.keys())

    activity_type = st.selectbox("Activity Type", ["Task Work", "Call", "Meeting", "Other"])

    log = {"date": today, "user": user, "task": selected_task, "activity_type": activity_type}

    if activity_type == "Task Work":
        status = st.selectbox("Task Status", TASK_STATUS)
        log["details"] = st.text_area("Work Done")
        task_titles[selected_task]["status"] = status

    elif activity_type == "Call":
        log["call_with"] = st.selectbox("Call With", CALL_WITH)
        log["state"] = st.text_input("State")
        log["details"] = st.text_area("Call Notes")

    elif activity_type == "Meeting":
        log["meeting_with"] = st.selectbox("Meeting With", MEETING_WITH)
        log["mode"] = st.selectbox("Mode", ["Online", "Offline"])
        log["state"] = st.text_input("State")
        log["details"] = st.text_area("MOM")

    else:
        log["work_category"] = st.selectbox("Work Category", OTHER_WORK_TYPES)
        log["state"] = st.text_input("State")
        log["details"] = st.text_area("Description")

    if st.button("Submit Daily Log"):
        st.session_state.logs.append(log)
        st.success("Work logged")

# =====================================================
# LEAVE MANAGEMENT
# =====================================================
elif menu == "Leave":
    st.header("🌴 Leave Management")

    today = str(date.today())

    if role == "Management":
        st.subheader("Apply for Leave")

        leave_type = st.selectbox("Leave Type", LEAVE_TYPES.keys())
        leave_date = st.date_input("Leave Date", min_value=date.today())
        reason = st.text_area("Reason")

        used = [
            l for l in st.session_state.leaves
            if l["user"] == user and l["leave_type"] == leave_type and l["status"] == "Approved"
        ]

        if len(used) >= LEAVE_TYPES[leave_type]:
            st.error("Leave balance exhausted")

        elif st.button("Apply Leave"):
            st.session_state.leaves.append({
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
        st.subheader("Pending Leave Requests")

        pending = [l for l in st.session_state.leaves if l["status"] == "Pending"]

        if not pending:
            st.info("No pending leave requests")

        for i, l in enumerate(pending):
            with st.expander(f"{l['user']} – {l['leave_type']} – {l['date']}"):
                st.write("Reason:", l["reason"])
                rej_reason = st.text_input("Rejection Reason (if rejecting)", key=i)

                col1, col2 = st.columns(2)
                if col1.button("Approve", key=f"a{i}"):
                    l["status"] = "Approved"
                    l["action_by"] = user
                    st.success("Approved")

                if col2.button("Reject", key=f"r{i}"):
                    l["status"] = "Rejected"
                    l["action_by"] = user
                    l["action_reason"] = rej_reason
                    st.warning("Rejected")
