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
