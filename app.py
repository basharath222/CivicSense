import streamlit as st
import pandas as pd
import os
import pywhatkit as kit
import time
import pyautogui  
from datetime import datetime

import supabase

from orchestrator.llm_engine import analyze_complaint_with_gemini
from orchestrator.situation_analyzer import analyze_situation
from utils.helpers import (
    save_complaint,
    route_authority,
    trigger_alert,
    ADMIN_CREDENTIALS,
)
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv() # Ensure .env is loaded

# Use st.cache_resource so the connection persists across reruns
@st.cache_resource
def init_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase_client = init_supabase()

# --- DIRECTORY FIX ---
if not os.path.exists("data"):
    os.makedirs("data")

# --- SESSION STATE INITIALIZATION ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "admin_role" not in st.session_state:
    st.session_state.admin_role = None

# --- PAGE CONFIG ---
st.set_page_config(page_title="CivicSense", page_icon="🏘️", layout="centered")

st.sidebar.title("Navigation")
if not st.session_state.logged_in:
    page = st.sidebar.radio("Public View", ["📝 Submit Complaint", "ℹ️ Community Impact", "🔐 Admin Login"])
else:
    page = st.sidebar.radio(f"{st.session_state.admin_role} Admin", ["🛂 Authority Dashboard"])

# --- PAGE: SUBMIT COMPLAINT ---
if page == "📝 Submit Complaint":
    st.title("🏘️ CivicSense")
    st.subheader("Your Voice for a Better Community")
    
    try:
        with open("prompts/complaint_prompt.txt") as f:
            PROMPT_TEMPLATE = f.read()
    except FileNotFoundError:
        st.error("Configuration Error: prompts/complaint_prompt.txt not found.")
        st.stop()

    with st.expander("📍 Step 1: Provide Location Details", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            address = st.text_input("House/Street Address *", key="addr_input")
            city = st.text_input("City *", key="city_input")
        with col2:
            area = st.text_input("Area / Locality *", key="area_input")
            pincode = st.text_input("Pincode (6 digits) *", key="pin_input")

    with st.expander("📝 Step 2: Describe the Issue", expanded=True):
        phone = st.text_input("📞 Mobile Number *", key="phone_input")
        complaint_text = st.text_area("What is happening? *", key="complaint_input")

    if st.button("🚀 Analyze & Submit Complaint"):
        v_addr, v_area, v_city, v_pin, v_phone, v_complaint = (
            st.session_state.addr_input.strip(), st.session_state.area_input.strip(),
            st.session_state.city_input.strip(), st.session_state.pin_input.strip(),
            st.session_state.phone_input.strip(), st.session_state.complaint_input.strip()
        )

        if not all([v_addr, v_area, v_city, v_pin, v_phone, v_complaint]):
            st.error("❌ Please fill in all required fields.")
        else:
            with st.status("🧠 AI is processing...", expanded=True) as status:
                ai_output = analyze_complaint_with_gemini(v_complaint, PROMPT_TEMPLATE)
                situation = analyze_situation(ai_output)
                # Inside the Submit Button logic in app.py
                # Change this line:
                normalized_cat, authority = route_authority(ai_output["category"], v_complaint)

                comp_id = save_complaint(
                    v_complaint, v_area, v_city, v_addr, v_pin, v_phone,
                    ai_output, situation, normalized_cat, authority
                )
                
                if situation["alert_level"] == "CRITICAL":
                    trigger_alert(authority, v_phone, v_area, v_city)
                status.update(label="✅ Submission Successful!", state="complete", expanded=False)

            st.balloons()
            st.success(f"### Ticket Generated: **{comp_id}**")
            st.write(f"Routed to: **{authority}**")
            
            st.divider()
            st.subheader("📊 AI Analysis Report")
            c1, c2, c3 = st.columns(3)
            c1.metric("Category", normalized_cat)
            p_color = "🔴" if situation["alert_level"] == "CRITICAL" else "🟠" if situation["alert_level"] == "HIGH" else "🟢"
            c2.metric("Priority", f"{p_color} {situation['alert_level']}")
            c3.metric("Criticality", f"{situation['priority_score']} / 10")
            st.info(f"**Action:** {ai_output['recommended_action']}")

elif page == "🛂 Authority Dashboard":
    if st.sidebar.button("🚪 Logout"):
        st.session_state.logged_in = False
        st.session_state.admin_role = None
        st.rerun()

    role = st.session_state.admin_role
    st.title(f"🛂 {role} Dashboard")

    # --- 1. MULTI-STAGE ESCALATION & ADMIN WARNINGS ---
    # Fetch Pending tickets that aren't already with Common admin
    esc_res = supabase_client.table("complaints")\
        .select("*")\
        .eq("status", "Pending")\
        .eq("category", role)\
        .neq("category", "Common").execute()
    
    # Define Thresholds
            # Critical: 2h (7200s), High: 4h (14400s), Medium: 8h (28800s)
            # limits = {"CRITICAL": 7200, "HIGH": 14400, "MEDIUM": 28800}
            # escalation_limit = limits.get(ticket['alert_level'], 86400) # Default 24h
            # warning_limit = escalation_limit - 900 # 15 Minutes before escalation
    
    for ticket in esc_res.data:
        raw_ts = ticket['timestamp'].replace('Z', '+00:00')
        try:
            created_at = datetime.fromisoformat(raw_ts)
            from datetime import timezone, timedelta
            time_diff = (datetime.now(timezone.utc) - created_at).total_seconds()
            
            # PROTOTYPE SPEEDS
            limits = {"CRITICAL": 7200, "HIGH": 14400, "MEDIUM": 28800}
            escalation_limit = limits.get(ticket['alert_level'], 86400) # Default 24h
            warning_limit = escalation_limit - 900 # 15 Minutes before escalation
            # limits = {"CRITICAL": 60, "HIGH": 120, "MEDIUM": 180}
            # escalation_limit = limits.get(ticket['alert_level'], 300)
            # warning_limit = escalation_limit - 30 
            
            # STAGE 1: WhatsApp Warning to Dept Admin
            if warning_limit <= time_diff < escalation_limit:
                dept_mobile = ADMIN_CREDENTIALS.get(ticket['category'], {}).get("mobile")
                if dept_mobile:
                    with st.spinner(f"📲 Triggering Emergency Alert to {ticket['category']} Admin..."):
                        try:
                            warning_text = f"🚨 URGENT: {ticket['category']} Admin, Ticket {ticket['complaint_id']} escalates in 15 seconds!"
                            
                            # 1. Open the tab (Increase wait_time to 25 to allow for slow loading)
                            kit.sendwhatmsg_instantly(f"+{dept_mobile}", warning_text, wait_time=25, tab_close=True)
                            
                            # 2. CRITICAL: Wait for the browser to load and the cursor to focus
                            time.sleep(8) 
                            
                            # 3. Press Enter (This will now land in the WhatsApp text box)
                            pyautogui.press('enter') 
                            
                            st.toast("Alert Sent!", icon="✅")
                        except Exception as e:
                            st.error(f"WhatsApp Automation Failed: {e}")

            elif time_diff >= escalation_limit:
                # Update Supabase first
                supabase_client.table("complaints").update({
                    "category": "Common", 
                    "recommended_action": "🚨 REDIRECTED: Stalled."
                }).eq("complaint_id", ticket['complaint_id']).execute()
                
                st.error(f"Ticket {ticket['complaint_id']} REDIRECTED to Master.")
                time.sleep(1) # Ensure the message is visible to you
                st.rerun() # Refresh after all logic is done
        except Exception as e:
            print(f"Error in automation: {e}")

    # --- 2. DATA VIEW: ROLE-BASED FILTERING ---
    if role == "Common":
        # Master Admin sees everything uncompleted
        response = supabase_client.table("complaints").select("*").neq("status", "Completed").execute()
    else:
        # Dept Admin sees only their assigned uncompleted work
        response = supabase_client.table("complaints").select("*").eq("category", role).neq("status", "Completed").execute()
    
    dept_data = response.data

    if not dept_data:
        st.info(f"No active grievances found for {role}. All clear!")
    else:
        df = pd.DataFrame(dept_data)
        
        # Overview Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("📋 Active Tasks", len(df))
        m2.metric("🚨 Critical", len(df[df["alert_level"] == "CRITICAL"]))
        m3.metric("🏠 Areas", df["area"].nunique())

        # Sort: Critical first
        p_map = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        df["p_rank"] = df["alert_level"].map(p_map)
        df = df.sort_values("p_rank")

        for idx, row in df.iterrows():
            urgency_indicator = "🔴" if row['alert_level'] == "CRITICAL" else "🟠" if row['alert_level'] == "HIGH" else "🟢"
            
            with st.expander(f"{urgency_indicator} {row['address']} | {row['area']} | {row['alert_level']}"):
                st.write(f"### Issue: {row['complaint_text']}")
                st.divider()
                
                # Citizen & Location Details for Field Officers
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**📍 Address:** {row['address']}, {row['area']}, {row['city']} - {row['pincode']}")
                    st.markdown(f"**📞 Citizen Mobile:** {row['phone']}")
                with c2:
                    st.markdown(f"**⚖️ Priority Score:** {row['priority_score']}/10")
                    st.markdown(f"**🛡️ Dept:** {row['category']}")
                
                st.info(f"**💡 AI Recommended Action:** {row['recommended_action']}")

                # Status Update & Database Purge Logic
                new_status = st.selectbox("Update Status", ["Pending", "In Progress", "Completed"], 
                                          index=["Pending", "In Progress", "Completed"].index(row["status"]),
                                          key=f"status_{row['complaint_id']}")

                if new_status != row["status"]:
                    if new_status == "Completed":
                        # REMOVE FROM SUPABASE ON COMPLETION
                        supabase_client.table("complaints").delete().eq("complaint_id", row["complaint_id"]).execute()
                        st.success("✅ Ticket Resolved and record purged from Cloud Database.")
                    else:
                        supabase_client.table("complaints").update({"status": new_status}).eq("complaint_id", row["complaint_id"]).execute()
                    
                    # Notify Citizen of Progress
                    try:
                        kit.sendwhatmsg_instantly(f"+91{row['phone']}", f"CivicSense: Work on your ticket {row['complaint_id']} is now {new_status}.", 18, True)
                        time.sleep(2)
                        pyautogui.press('enter')
                    except:
                        pass
                    
                    st.rerun()
                    
# --- OTHER PAGES ---
elif page == "ℹ️ Community Impact":
    st.title("🌍 Community Impact")
    st.markdown("Automating governance for **SDG Goal 11: Sustainable Cities.**")

elif page == "🔐 Admin Login":
    st.title("🔐 Authority Login")
    dept = st.selectbox("Department", list(ADMIN_CREDENTIALS.keys()))
    user = st.text_input("Username").strip()
    pin = st.text_input("PIN", type="password").strip()
    if st.button("Login"):
        if user.lower() == ADMIN_CREDENTIALS[dept]["username"].lower() and pin == ADMIN_CREDENTIALS[dept]["pin"]:
            st.session_state.logged_in, st.session_state.admin_role = True, dept
            st.rerun()
        else:
            st.error("Invalid credentials")