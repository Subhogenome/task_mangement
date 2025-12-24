import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
from pymongo import MongoClient
import pytz
import os

# ---------------------------------
# Config
# ---------------------------------
st.set_page_config(page_title="Glucose Logger", layout="centered")
st.title("🩸 Glucose Level Logger")

IST = pytz.timezone("Asia/Kolkata")

# ---------------------------------
# MongoDB Connection
# ---------------------------------
MONGO_URI = st.secrets.get("MONGO_URI") or os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["glucose_db"]
collection = db["readings"]

# ---------------------------------
# Helpers
# ---------------------------------
def classify_glucose(value):
    if value < 70:
        return "Hypoglycemia"
    elif value <= 140:
        return "Normal"
    else:
        return "Hyperglycemia"

def get_ist_timestamp(log_time=None):
    now_ist = datetime.now(IST)
    if log_time:
        combined = datetime.combine(now_ist.date(), log_time)
        return IST.localize(combined)
    return now_ist

# ---------------------------------
# Input Form
# ---------------------------------
with st.form("glucose_form"):
    glucose = st.number_input(
        "Glucose Level (mg/dL)",
        min_value=20,
        max_value=600,
        step=1
    )

    log_time = st.time_input(
        "Time (optional – defaults to current IST)",
        value=None
    )

    submit = st.form_submit_button("➕ Log Reading")

    if submit:
        timestamp = get_ist_timestamp(log_time)

        collection.insert_one({
            "time": timestamp,
            "glucose": glucose,
            "status": classify_glucose(glucose)
        })

        st.success(
            f"Logged {glucose} mg/dL at {timestamp.strftime('%d %b %Y %I:%M %p IST')}"
        )

# ---------------------------------
# Fetch Data
# ---------------------------------
data = list(collection.find({}, {"_id": 0}))

if data:
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_convert("Asia/Kolkata")
    df = df.sort_values("time")

    # -----------------------------
    # Table
    # -----------------------------
    st.subheader("📋 Glucose History")
    st.dataframe(df, use_container_width=True)

    # -----------------------------
    # Plotly Graph
    # -----------------------------
    st.subheader("📈 Glucose Trend (IST)")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["time"],
        y=df["glucose"],
        mode="lines+markers",
        name="Glucose",
        hovertemplate="Time: %{x}<br>Glucose: %{y} mg/dL<extra></extra>"
    ))

    fig.add_hline(y=70, line_dash="dash", annotation_text="Hypo (70)")
    fig.add_hline(y=140, line_dash="dash", annotation_text="Hyper (140)")

    fig.add_hrect(y0=0, y1=70, fillcolor="blue", opacity=0.08)
    fig.add_hrect(y0=70, y1=140, fillcolor="green", opacity=0.08)
    fig.add_hrect(y0=140, y1=600, fillcolor="red", opacity=0.08)

    fig.update_layout(
        xaxis_title="Time (IST)",
        yaxis_title="Glucose (mg/dL)",
        hovermode="x unified",
        height=450
    )

    st.plotly_chart(fig, use_container_width=True)

    # -----------------------------
    # Latest Reading
    # -----------------------------
    latest = df.iloc[-1]
    st.markdown(f"""
    ### 🧠 Latest Reading
    - 🕒 **Time:** {latest['time'].strftime('%d %b %Y %I:%M %p IST')}
    - 🩸 **Glucose:** {latest['glucose']} mg/dL
    - 📌 **Status:** **{latest['status']}**
    """)

else:
    st.info("No glucose readings found. Add one above 👆")

