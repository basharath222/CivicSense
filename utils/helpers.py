import csv
import os
import uuid
import logging
from datetime import datetime

# Setup logging to track errors and file operations
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path setup with a safety check
DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "complaints.csv")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# -------------------------------
# Admin credentials (demo-safe)
# -------------------------------
# These keys must match the normalized categories for role-based access [cite: 140]
ADMIN_CREDENTIALS = {
    "Common": {"username": "master_admin", "pin": "0000", "mobile": "919677631754"},
    "Water": {"username": "water_admin", "pin": "1111", "mobile": "919677631754"},
    "Garbage": {"username": "garbage_admin", "pin": "2222", "mobile": "919677631754"},
    "Electricity": {"username": "electricity_admin", "pin": "3333", "mobile": "919677631754"},
    "Health": {"username": "health_admin", "pin": "4444", "mobile": "919677631754"},
    "Safety": {"username": "safety_admin", "pin": "5555", "mobile": "919677631754"},
    "Road": {"username": "road_admin", "pin": "6666", "mobile": "919677631754"},
    "Infrastructure": {"username": "pwd_admin", "pin": "7777", "mobile": "919677631754"},
}

# -------------------------------
# Authority routing & Normalization
# -------------------------------
def route_authority(ai_category, complaint_text=""):
    """
    Enhanced normalization with a fallback keyword scanner 
    to prevent 'General Municipal Authority' routing on API errors.
    """
    category_map = {
        "Water": ["Water", "Leakage", "Supply", "Drainage", "Pipe"],
        "Garbage": ["Garbage", "Waste", "Sanitation", "Sewage", "Clean", "Odour", "Smell", "Trash"],
        "Electricity": ["Electricity", "Power", "Street Light", "Transformer", "Current"],
        "Health": ["Health", "Disease", "Medical", "Hospital", "Fever", "Sick"],
        "Safety": ["Safety", "Crime", "Police", "Emergency", "Fire", "Harassment", "POSH"],
        "Road": ["Road", "Pothole", "Speed Breaker", "Traffic", "Highways"],
        "Infrastructure": ["Infrastructure", "Building", "Bridge", "PWD"]
    }

    normalized_category = "Other"
    ai_cat_lower = ai_category.lower()
    
    # 1. First try to match the AI category
    for formal_key, synonyms in category_map.items():
        if any(syn.lower() in ai_cat_lower for syn in synonyms):
            normalized_category = formal_key
            break

    # 2. FALLBACK: If AI failed (Other), scan the actual complaint text
    if normalized_category == "Other" and complaint_text:
        text_lower = complaint_text.lower()
        for formal_key, synonyms in category_map.items():
            if any(syn.lower() in text_lower for syn in synonyms):
                normalized_category = formal_key
                break

    routing_map = {
        "Water": "Water Supply Department",
        "Garbage": "Municipal Sanitation Department",
        "Electricity": "Electricity Board (TNEB)",
        "Health": "Public Health Department",
        "Safety": "Police / Emergency Services",
        "Road": "Highways & Traffic Department",
        "Infrastructure": "Public Works Department (PWD)"
    }
    
    final_authority = routing_map.get(normalized_category, "General Municipal Authority")
    return normalized_category, final_authority
# -------------------------------
# Save complaint to CSV
# -------------------------------
def save_complaint(
    complaint_text, area, city, address, pincode, phone, 
    ai_output, situation_output, normalized_category, authority
):
    """
    Saves a record to CSV with 'utf-8-sig' for Tamil/English support.
    """
    file_exists = os.path.isfile(DATA_FILE)
    complaint_id = f"CIVIC-{uuid.uuid4().hex[:8].upper()}"

    headers = [
        "complaint_id", "timestamp", "area", "city", "address", "pincode", 
        "phone", "complaint_text", "category", "urgency", "sentiment", 
        "risk_type", "priority_score", "alert_level", "assigned_authority", 
        "status", "recommended_action"
    ]

    row_data = [
        complaint_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        area.strip(), city.strip(), address.strip(), pincode.strip(), phone.strip(),
        complaint_text.strip(),
        normalized_category,  # Use the normalized key for dashboard filtering [cite: 140]
        ai_output.get("urgency", 3),
        ai_output.get("sentiment", "Neutral"),
        ai_output.get("risk_type", "None"),
        situation_output.get("priority_score", 0),
        situation_output.get("alert_level", "LOW"),
        authority,
        "Pending",
        ai_output.get("recommended_action", "Manual review required.")
    ]

    try:
        with open(DATA_FILE, mode="a", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(headers)
            writer.writerow(row_data)
        logger.info(f"Successfully saved complaint: {complaint_id}")
        return complaint_id
    except Exception as e:
        logger.error(f"Failed to save complaint: {str(e)}")
        return None

# -------------------------------
# Alert automation (simulation)
# -------------------------------
def trigger_alert(authority, phone, area, city):
    """
    Triggers automated alerts for CRITICAL level complaints.
    """
    alert_msg = (
        f"🚨 [CRITICAL ALERT]\n"
        f"Target Authority: {authority}\n"
        f"Location: {area}, {city}\n"
        f"Citizen Contact: {phone}\n"
        f"Automation Status: Escalated to Official Dashboard."
    )
    print("\n" + "="*40 + "\n" + alert_msg + "\n" + "="*40 + "\n")

import os
import uuid
from supabase import create_client, Client

# Add these to your .env file
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_complaint(complaint_text, area, city, address, pincode, phone, ai_output, situation_output, normalized_category, authority):
    complaint_id = f"CIVIC-{uuid.uuid4().hex[:8].upper()}"
    
    data = {
        "complaint_id": complaint_id,
        "area": area,
        "city": city,
        "address": address,
        "pincode": pincode,
        "phone": phone,
        "complaint_text": complaint_text,
        "category": normalized_category,
        "urgency": ai_output.get("urgency"),
        "sentiment": ai_output.get("sentiment"),
        "risk_type": ai_output.get("risk_type"),
        "priority_score": situation_output.get("priority_score"),
        "alert_level": situation_output.get("alert_level"),
        "assigned_authority": authority,
        "recommended_action": ai_output.get("recommended_action")
    }

    # Insert into Cloud Database
    try:
        supabase.table("complaints").insert(data).execute()
        return complaint_id
    except Exception as e:
        print(f"Cloud DB Error: {e}")
        return None

def log_automation(phone, message, status):
    """Replaces pywhatkit_db.txt with Cloud Logging"""
    log_data = {"phone": phone, "message": message, "status": status}
    supabase.table("automation_logs").insert(log_data).execute()