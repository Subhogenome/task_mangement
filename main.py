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
client = MongoClient(st.secrets["mongo"])
db = client["nc_ops"]

users_col = db.users
tasks_col = db.tasks
logs_col = db.work_logs
leaves_col = db.leaves

# =====================================================
# EMAILS
# =====================================================
NC_EMAILS = {
    "Rishabh Purohit": "purohitrm@gmail.com",
    "Kunal Bhaiya": "kunaljgd@gmail.com",
    "Subhodeep Chatterjee": "chatterjeesubhodeep08@gmail.com"
}

MGMT_EMAILS = {
    "Akshay Kachchhi": "akshay@srisripublications.com",
    "Vatsal Patel": "aolsm.rc1@srisripublications.com",
    "Narendra Wamburkar": "aolsm.rc2@srisripublications.com"
}

OFFICIAL_NC_EMAIL = "aolsm.nc@srisripublications.com"

yag = yagmail.SMTP(
    st.secrets["user"],
    st.secrets["password"]
)

def send_email(to, subject, body, cc=None):
    yag.send(to=to, subject=subject, contents=body, cc=cc)

# =====================================================
# LLM (ChatGroq)
# =====================================================
llm = ChatGroq(
    api_key=st.secrets["groq"]["api_key"],
    model="llama3-70b-8192",
    temperature=0.2
)

summary_prompt = PromptTemplate.from_template("""
You are a National Coordinator reviewing daily work.

Summarize work done today by {name}.

Focus on:
- Tasks
- Calls
- Meetings
- Status changes
- Risks

Logs:
{logs}

Return bullet points.
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
                        "name": user_doc["name"],
                        "email": user_doc["email"],
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
role = current_user["role"]
user = current_user["name"]

st.sidebar.markdown(f"""
**Logged in as**  
{current_user['name']}  
{current_user['email']}
""")

if st.sidebar.button("Logout"):
    st.session_state.user = None
    st.rerun()

menu = st.sidebar.radio(
    "Menu", ["Dashboard", "Create Task", "Daily Work Log", "Leave"]
)

# =====================================================
# DASHBOARD (NC ONLY AI SUMMARY SHOWN)
# =====================================================
if menu == "Dashboard":
    st.header("Dashboard")

    if role == "nc":
        st.subheader("All Tasks")
        st.dataframe(pd.DataFrame(list(tasks_col.find({}, {"_id": 0}))))

        st.subheader("AI Daily Summary")
        review_date = str(st.date_input("Date", date.today()))

        if st.button("Generate & Email Summary"):
            logs = list(logs_col.find({"date": review_date}, {"_id": 0}))
            df = pd.DataFrame(logs)

            summaries = []
            for m, mail in MGMT_EMAILS.items():
                mlogs = df[df["user"] == m]
                if not mlogs.empty:
                    text = summary_chain.invoke({
                        "name": m,
                        "logs": mlogs.to_dict(orient="records")
                    }).content
                    send_email(mail, f"[Your Summary] {review_date}", text)
                    summaries.append(f"{m}\n{text}")

            send_email(
                list(NC_EMAILS.values()),
                f"[Daily Ops Summary] {review_date}",
                "\n\n".join(summaries),
                cc=OFFICIAL_NC_EMAIL
            )

            st.success("Summary emailed")

# =====================================================
# CREATE TASK
# =====================================================
elif menu == "Create Task":
    title = st.text_input("Task Title")
    desc = st.text_area("Description")
    start = st.date_input("Start Date")
    end = st.date_input("End Date")

    if role == "nc":
        assigned_to = st.selectbox("Assign To", list(MGMT_EMAILS.keys()))
        reporters = st.multiselect("Reporting NCs", list(NC_EMAILS.keys()), default=[user])
    else:
        assigned_to = user
        reporters = st.multiselect("Reporting NCs", list(NC_EMAILS.keys()))

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
            MGMT_EMAILS.get(assigned_to),
            f"[Task Assigned] {title}",
            f"{desc}\nStart: {start}\nEnd: {end}",
            cc=[NC_EMAILS[n] for n in reporters]
        )

        st.success("Task created")

# =====================================================
# DAILY WORK LOG
# =====================================================
elif menu == "Daily Work Log":
    if role != "management":
        st.stop()

    today = str(date.today())
    tasks = list(tasks_col.find({"assigned_to": user}))
    task_map = {t["title"]: t for t in tasks}

    task = st.selectbox("Task", task_map.keys())
    details = st.text_area("Work Done")
    status = st.selectbox("Update Status", ["No Change", "To Do", "Running", "Done"])

    if st.button("Submit Log"):
        logs_col.insert_one({
            "date": today,
            "user": user,
            "task": task,
            "details": details,
            "updated_status": status
        })

        if status != "No Change":
            tasks_col.update_one({"title": task}, {"$set": {"status": status}})

        reporters = task_map[task]["reporting_ncs"]

        send_email(
            [NC_EMAILS[n] for n in reporters],
            f"[Daily Update] {user} | {task}",
            details,
            cc=MGMT_EMAILS[user]
        )

        st.success("Log saved")

# =====================================================
# LEAVE
# =====================================================
elif menu == "Leave":
    if role == "management":
        leave_type = st.selectbox("Leave Type", ["CL", "SL", "COURSE"])
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
                list(NC_EMAILS.values()),
                f"[Leave Request] {user}",
                reason,
                cc=MGMT_EMAILS[user]
            )

            st.success("Leave applied")
