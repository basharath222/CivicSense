import os
import json
import logging
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Setup logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# Use the latest stable flash model
MODEL_NAME = "gemini-2.5-flash" 

from asyncio.log import logger


def calculate_priority(urgency, risk_type):
    risk_weight = {
        "Health": 3,
        "Safety": 2,
        "Infrastructure": 1,
        "None": 0
    }

    return urgency + risk_weight.get(risk_type, 0)


def get_alert_level(priority):
    if priority >= 7:
        return "CRITICAL"
    elif priority >= 5:
        return "HIGH"
    elif priority >= 3:
        return "MEDIUM"
    else:
        return "LOW"


def get_risk_color(alert_level):
    return {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢"
    }.get(alert_level, "⚪")


def analyze_situation(gemini_output):
    urgency = gemini_output.get("urgency", 3)
    risk_type = gemini_output.get("risk_type", "None")

    priority = calculate_priority(urgency, risk_type)
    alert_level = get_alert_level(priority)
    risk_color = get_risk_color(alert_level)

    return {
        "priority_score": priority,
        "alert_level": alert_level,
        "risk_indicator": risk_color
    }
import os
import json
import logging
from google import genai       # Fixes 'client is not defined'
from google.genai import types # Fixes 'types is not defined'
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Initialize the client outside the function for better performance
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_NAME = "gemini-2.5-flash" 

def analyze_complaint_with_gemini(complaint_text, prompt_template):
    # Constructing a structured system instruction
    system_instruction = (
        "You are an expert community grievance analyzer. "
        "Strictly categorize complaints into one of these: Water, Garbage, Electricity, Health, Safety, Road, Infrastructure. "
        "Return ONLY a raw JSON object."
    )

    prompt = prompt_template.replace("{complaint_text}", complaint_text)

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json", 
                temperature=0.1, 
            )
        )

        # CLEANING LOGIC: Remove markdown backticks if present
        raw_text = response.text.strip()
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(clean_json)
        
        # Ensure the category is Capitalized to match your 'category_map' keys
        if "category" in result:
            result["category"] = result["category"].strip().capitalize()
            
        return result

    except Exception as e:
        # BACKUP LOGIC: Manually check for 'garbage' to avoid 'Other' during the demo
        low_text = complaint_text.lower()
        backup_cat = "Other"
        if "garbage" in low_text or "clean" in low_text or "odour" in low_text:
            backup_cat = "Garbage"
        
        return {
            "category": backup_cat,
            "urgency": 3,
            "sentiment": "Neutral",
            "risk_type": "None",
            "recommended_action": f"System error: {str(e)[:50]}" # Helps you debug live
        }