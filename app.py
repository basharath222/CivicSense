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
                if ai_output["category"] == "Common" or "homework" in v_complaint.lower():
                    status.update(label="❌ Invalid Complaint Type", state="error", expanded=True)
                    st.error("⚠️ Our AI has detected that this is not a civic infrastructure issue. Please report problems related to Water, Roads, Electricity, etc.")
                    st.stop()
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

    # --- 1. TWO-STAGE ESCALATION & ADMIN WARNINGS ---
    esc_res = supabase_client.table("complaints")\
        .select("*")\
        .eq("status", "Pending")\
        .eq("category", role)\
        .neq("category", "Common").execute()
    
    for ticket in esc_res.data:
        raw_ts = ticket['timestamp'].replace('Z', '+00:00')
        try:
            created_at = datetime.fromisoformat(raw_ts)
            from datetime import timezone
            time_diff = (datetime.now(timezone.utc) - created_at).total_seconds()
            

            # Critical: 24h, High: 36h, Medium: 48h
            limits = {
                "CRITICAL": 86400, 
                "HIGH": 129600, 
                "MEDIUM": 172800
            }

            # Get the limit for the current ticket's alert level
            escalation_limit = limits.get(ticket['alert_level'], 259200) # Default to 72h if unknown

            # Warning occurs 1 hour (3600s) before the final escalation
            warning_limit = escalation_limit - 3600
            
            if warning_limit <= time_diff < escalation_limit:
                dept_mobile = ADMIN_CREDENTIALS.get(ticket['category'], {}).get("mobile")
                if dept_mobile:
                    with st.spinner(f"📲 Alerting {ticket['category']} Admin..."):
                        # WhatsApp Warning logic
                        warning_text = f"🚨 URGENT: Ticket {ticket['complaint_id']} escalates in 30 seconds!"
                        kit.sendwhatmsg_instantly(f"+{dept_mobile}", warning_text, wait_time=20, tab_close=True)
                        time.sleep(8) 
                        pyautogui.press('enter') 
                        st.toast("Admin Notified!", icon="✅")

            elif time_diff >= escalation_limit:
                supabase_client.table("complaints").update({
                    "category": "Common", 
                    "recommended_action": "🚨 REDIRECTED: Stalled."
                }).eq("complaint_id", ticket['complaint_id']).execute()
                st.error(f"Ticket {ticket['complaint_id']} REDIRECTED to Master Admin.")
                st.rerun()
        except:
            pass

    # --- 2. DATA FETCHING ---
    if role == "Common":
        response = supabase_client.table("complaints").select("*").neq("status", "Completed").execute()
    else:
        response = supabase_client.table("complaints").select("*").eq("category", role).neq("status", "Completed").execute()
    
    dept_data = response.data

    if not dept_data:
        st.info(f"No active grievances found for {role}.")
    else:
        df = pd.DataFrame(dept_data)
        
        # --- 3. THE "CRITICAL PILLAR" VISUALIZATION ---
        # Splitting the dashboard to highlight Emergencies [cite: 61, 104]
        critical_df = df[df["alert_level"] == "CRITICAL"]
        other_df = df[df["alert_level"] != "CRITICAL"]

        if not critical_df.empty:
            st.error("🚨 EMERGENCY ACTION REQUIRED")
            for idx, row in critical_df.iterrows():
                with st.expander(f"🔴 CRITICAL: {row['address']} | {row['area']}", expanded=True):
                    # Show all citizen details and issue as before 
                    st.caption(f"📅 Registered on: {row['timestamp']}")
                    st.write(f"### Issue: {row['complaint_text']}")
                    st.divider()
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"**📍 Location:** {row['address']}, {row['area']}, {row['city']} - {row['pincode']}")
                        st.markdown(f"**📞 Citizen Contact:** {row['phone']}")
                    with c2:
                        st.markdown(f"**⚖️ Priority Score:** {row['priority_score']}/10")
                        st.markdown(f"**🛡️ Category:** {row['category']}")
                    st.warning(f"**💡 AI Action Plan:** {row['recommended_action']}")
                    
                    # Update Status Logic
                    new_status = st.selectbox("Action", ["Pending", "In Progress", "Completed"], 
                                              index=["Pending", "In Progress", "Completed"].index(row["status"]),
                                              key=f"crit_{row['complaint_id']}")
                    if new_status != row["status"]:
                        # WhatsApp Notify First 
                        with st.spinner("Notifying Citizen..."):
                            kit.sendwhatmsg_instantly(f"+91{row['phone']}", f"CivicSense: Work on your ticket {row['complaint_id']} is now {new_status}.", 20, True)
                            time.sleep(8)
                            pyautogui.press('enter')
                        
                        if new_status == "Completed":
                            supabase_client.table("complaints").delete().eq("complaint_id", row["complaint_id"]).execute()
                        else:
                            supabase_client.table("complaints").update({"status": new_status}).eq("complaint_id", row["complaint_id"]).execute()
                        st.rerun()

        # Display Standard Issues
       
        if not other_df.empty:
            st.subheader("📋 Active Tasks")
            for idx, row in other_df.iterrows():
                # Set visual indicator based on urgency level
                indicator = "🟠" if row['alert_level'] == "HIGH" else "🟢"
                
                # Expanding card now contains FULL citizen and issue details 
                with st.expander(f"{indicator} {row['address']} | {row['area']} | {row['alert_level']}"):
                    st.caption(f"📅 Registered on: {row['timestamp']}")
                    st.write(f"### Issue: {row['complaint_text']}")
                    st.divider()
                    
                    # Detailed Info Grid
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"**📍 Full Address:** {row['address']}, {row['area']}, {row['city']} - {row['pincode']}")
                        st.markdown(f"**📞 Citizen Phone:** {row['phone']}")
                    with c2:
                        st.markdown(f"**⚖️ Priority Score:** {row['priority_score']}/10")
                        st.markdown(f"**🛡️ Assigned Dept:** {row['category']}")
                    
                    st.info(f"**💡 AI Recommended Action:** {row['recommended_action']}")
                    
                    # Status Update Logic with WhatsApp Integration [cite: 33, 46]
                    new_status = st.selectbox("Update Work Status", ["Pending", "In Progress", "Completed"], 
                                            index=["Pending", "In Progress", "Completed"].index(row["status"]),
                                            key=f"std_{row['complaint_id']}")
                    
                    if new_status != row["status"]:
                        # Trigger WhatsApp Notification before updating DB [cite: 46]
                        with st.spinner("🔄 Sending WhatsApp Update to Citizen..."):
                            try:
                                citizen_msg = f"CivicSense Update: Your ticket {row['complaint_id']} status changed to {new_status}."
                                # Fixed 20-second wait to ensure reliable delivery [cite: 33]
                                kit.sendwhatmsg_instantly(f"+91{row['phone']}", citizen_msg, wait_time=30, tab_close=True)
                                time.sleep(12)
                                pyautogui.press('enter')
                                time.sleep(10)
                                st.toast("Citizen Notified Successfully!")
                            except Exception as e:
                                st.warning(f"WhatsApp Notification failed, but status will be updated: {e}")
                        
                        # Perform Database Update/Purge [cite: 41]
                        if new_status == "Completed":
                            supabase_client.table("complaints").delete().eq("complaint_id", row["complaint_id"]).execute()
                            st.success("Issue Resolved. Data purged from active database.")
                        else:
                            supabase_client.table("complaints").update({"status": new_status}).eq("complaint_id", row["complaint_id"]).execute()
                        
                        st.rerun()
                    
# --- PAGE: COMMUNITY IMPACT (ABOUT PAGE) ---
elif page == "ℹ️ Community Impact":
    st.title("🌍 About CivicSense")
    st.subheader("Automating Governance for a Safer, Smarter Tomorrow")

    st.markdown("""
    **CivicSense** is an AI-powered grievance redressal system designed to bridge the gap between 
    citizens and local authorities. By leveraging Large Language Models, we turn unstructured 
    community complaints into actionable data. 
    """)

    st.divider()

    # --- SECTION: OUR MISSION ---
    col1, col2 = st.columns(2)
    with col1:
        st.header("🎯 Our Mission")
        st.write("""
        * **Zero Friction**: Allowing citizens to report issues in natural language. 
        * **Instant Routing**: Eliminating manual sorting by directing tickets to the right experts.
        * **Life-Saving Priority**: Ensuring critical emergencies are never buried in paperwork. 
        """)
    
    with col2:
        st.header("🛠️ Core Innovation")
        st.write("""
        * **AI-Driven Logic**: Using Google Gemini to extract intent and risk levels. 
        * **Automated Escalation**: A two-stage protocol to prevent administrative delays.
        * **Transparency**: Real-time WhatsApp notifications to keep citizens informed. 
        """)

    st.divider()

    # --- SECTION: SDG ALIGNMENT ---
    st.header("Global Impact: SDG Goal 11")
    st.info("**Sustainable Cities and Communities**")
    st.write("""
    CivicSense directly contributes to **United Nations Sustainable Development Goal 11** by:
    1. **Target 11.3**: Enhancing inclusive and sustainable urbanization through participatory governance. 
    2. **Target 11.7**: Providing universal access to safe, inclusive, and accessible green and public spaces by maintaining infrastructure efficiently.
    """)


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