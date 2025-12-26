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

# =====================================================
# SESSION STATE (IN-MEMORY DB)
# =====================================================
if "tasks" not in st.session_state:
    st.session_state.tasks = []

if "logs" not in st.session_state:
    st.session_state.logs = []

# =====================================================
# APP HEADER
# =====================================================
st.set_page_config("Task Delegation POC", layout="wide")
st.title("🧩 Task Delegation & Daily Logging – POC")

# =====================================================
# ROLE SELECTION (NO AUTH)
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
    ["Dashboard", "Create Task", "Daily Work Log"]
)

# =====================================================
# DASHBOARD
# =====================================================
if menu == "Dashboard":
    st.header("📊 Dashboard")

    if role == "NC":
        st.subheader("All Tasks")
        if st.session_state.tasks:
            st.dataframe(pd.DataFrame(st.session_state.tasks))
        else:
            st.info("No tasks created yet")

        st.subheader("Live Work Updates")
        if st.session_state.logs:
            st.dataframe(pd.DataFrame(st.session_state.logs))
        else:
            st.info("No activity logged yet")

    else:
        st.subheader("My Assigned Tasks")
        my_tasks = [
            t for t in st.session_state.tasks
            if t["assigned_to"] == user
        ]
        if my_tasks:
            st.dataframe(pd.DataFrame(my_tasks))
        else:
            st.info("No tasks assigned to you yet")

# =====================================================
# CREATE TASK
# =====================================================
elif menu == "Create Task":
    st.header("📝 Create Task")

    title = st.text_input("Task Title")
    desc = st.text_area("Task Description")

    if role == "NC":
        assigned_to = st.selectbox("Assign to Management", MANAGEMENT)
        reporting_ncs = st.multiselect(
            "Reporting NC(s)",
            NCS,
            default=[user]
        )
    else:
        assigned_to = user
        reporting_ncs = st.multiselect(
            "Reporting NC(s)",
            NCS
        )

    if st.button("Create Task"):
        if not title or not desc:
            st.error("Title and description are mandatory")
        else:
            task = {
                "task_id": len(st.session_state.tasks) + 1,
                "title": title,
                "description": desc,
                "assigned_to": assigned_to,
                "reporting_ncs": ", ".join(reporting_ncs),
                "status": "To Do"
            }
            st.session_state.tasks.append(task)
            st.success("Task created successfully")

# =====================================================
# DAILY WORK LOG (MANAGEMENT ONLY)
# =====================================================
elif menu == "Daily Work Log":
    st.header("📅 Daily Work Log")

    if role != "Management":
        st.info("Only management can log daily work")
        st.stop()

    my_tasks = [
        t for t in st.session_state.tasks
        if t["assigned_to"] == user
    ]

    if not my_tasks:
        st.warning("No tasks assigned to you")
        st.stop()

    task_titles = {t["title"]: t for t in my_tasks}
    selected_task = st.selectbox("Select Task", task_titles.keys())

    activity_type = st.selectbox(
        "Activity Type",
        ["Task Work", "Call", "Meeting", "Other"]
    )

    log = {
        "date": str(date.today()),
        "user": user,
        "task": selected_task,
        "activity_type": activity_type
    }

    # ---------------- TASK WORK ----------------
    if activity_type == "Task Work":
        status = st.selectbox("Task Status", TASK_STATUS)
        work = st.text_area("Work Done")
        log["status"] = status
        log["details"] = work
        task_titles[selected_task]["status"] = status

    # ---------------- CALL ----------------
    elif activity_type == "Call":
        call_with = st.selectbox("Call With", CALL_WITH)
        state = st.text_input("State")
        notes = st.text_area("Call Notes")
        log["call_with"] = call_with
        log["state"] = state
        log["details"] = notes

    # ---------------- MEETING ----------------
    elif activity_type == "Meeting":
        meet_with = st.selectbox("Meeting With", MEETING_WITH)
        mode = st.selectbox("Mode", ["Online", "Offline"])
        state = st.text_input("State (if any)")
        mom = st.text_area("Minutes of Meeting (MOM)")
        log["meeting_with"] = meet_with
        log["mode"] = mode
        log["state"] = state
        log["details"] = mom

    # ---------------- OTHER ----------------
    elif activity_type == "Other":
        work_type = st.selectbox("Work Category", OTHER_WORK_TYPES)
        state = st.text_input("State (if applicable)")
        desc = st.text_area("Work Description")
        log["work_category"] = work_type
        log["state"] = state
        log["details"] = desc

    if st.button("Submit Daily Log"):
        st.session_state.logs.append(log)
        st.success("Daily work logged successfully")
