from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
import google.generativeai as genai
import os
import re
import html
import logging
from lib.rate_limiter import rate_limiter
from datetime import datetime

router = APIRouter()

# Load API Key securely
with open("D:\\FasiTahir\\apiKey.txt", "r") as file:
    key = file.read().strip()
genai.configure(api_key=key)

# import logging

# # Set up logging configuration
# logging.basicConfig(
#     level=logging.INFO,  # Minimum level to capture
#     format="%(asctime)s - %(levelname)s - %(message)s",  # Format for the logs
#     handlers=[
#         logging.FileHandler("nutrition_log.txt"),  # Save logs to this file
#         logging.StreamHandler()  # Also log to console
#     ]
# )

# ------------------ Logging Setup ------------------

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
log_dir = os.path.join(root_dir, "logs")
os.makedirs(log_dir, exist_ok=True)

log_file_path = os.path.join(log_dir, "child_nutrition.log")

logger = logging.getLogger("child_nutrition")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)



# Gemini config
generation_config = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "max_output_tokens": 512,
    "response_mime_type": "text/plain",
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=generation_config,
)


chat_session = model.start_chat(history=[])

# Age-based constraints (weight in kg, height in meters)
max_weight_by_month = {
    0: 4.5,  # Newborn
    1: 5.5,
    2: 6.5,
    3: 7.5,
    4: 8.2,
    5: 8.8,
    6: 9.2,
    7: 9.6,
    8: 10.0,
    9: 10.4,
    10: 10.8,
    11: 11.2,
}
# Fill in for months 12 to 120 (1-10 years)
for m in range(12, 121):
    age_years = m // 12
    max_weight_by_month[m] = 4 + age_years * 3  # same as before for simplicity

max_height_by_month = {
    0: 1.8,   # Newborn ~55 cm or 1.8 feet (0 months)
    1: 1.9,   # 1 month ~58 cm or 1.9 feet
    2: 2.0,   # 2 months ~61 cm or 2.0 feet
    3: 2.1,   # 3 months ~63 cm or 2.1 feet
    4: 2.2,   # 4 months ~65 cm or 2.2 feet
    5: 2.3,   # 5 months ~67 cm or 2.3 feet
    6: 2.4,   # 6 months ~69 cm or 2.4 feet
    7: 2.5,   # 7 months ~71 cm or 2.5 feet
    8: 2.6,   # 8 months ~73 cm or 2.6 feet
    9: 2.7,   # 9 months ~74 cm or 2.7 feet
    10: 2.8,  # 10 months ~75 cm or 2.8 feet
    11: 2.9,  # 11 months ~76 cm or 2.9 feet
}

# Fill the dictionary for months 12 to 120 (10 years)
for m in range(12, 121):
    age_years = m // 12  # Convert months to years
    # For 1 to 10 years, the height increases by 0.2 feet each year
    if age_years < 10:
        max_height_by_month[m] = 2.8 + (age_years - 1) * 0.2 


def calculate_age_in_months(dob_str: str) -> int:
    dob_str = dob_str.split("T")[0].strip()
    dob = datetime.strptime(dob_str, "%Y-%m-%d")
    today = datetime.today()
    return (today.year - dob.year) * 12 + (today.month - dob.month)

class ChildData(BaseModel):
    date_of_birth: str
    weight: float = Field(gt=0, lt=100) 
    height: float = Field(gt=0, lt=10)   
    milestones: Optional[List[str]] = []
    allergies: str
    gender: str
    child_id: Optional[str] = ""

def sanitize_input(text: str) -> str:
    """
    1. Strip malicious instructions, HTML, and prompt injection attempts
    """
    text = html.escape(text)  # escape HTML tags
    text = re.sub(r"(ignore.*|forget.*|you are now.*|disregard.*)", "", text, flags=re.IGNORECASE)
    return text.strip()


@router.post("/nutrition/")
async def get_nutrition_assist(child_data: ChildData, request: Request, _: None = Depends(rate_limiter)):
    logger.info(f"Received request for child_id={child_data.child_id} to generate nutrition assistance.")

    # 3. Sanitize all string fields
    safe_allergies = sanitize_input(child_data.allergies)
    safe_gender = sanitize_input(child_data.gender)

    # Calculate child's age in months
    age_months = calculate_age_in_months(child_data.date_of_birth)
    logger.info(f"Child age calculated as {age_months} months.")

    # Ensure the age is within the valid range (0 to 120 months)
    if age_months not in max_weight_by_month:
        logger.error(f"Age {age_months} out of range. Must be between 0 and 120 months.")
        raise HTTPException(status_code=400, detail="Age out of range. Please ensure age is between 0 and 10 years.")

    # Validate weight and height
    if child_data.weight > max_weight_by_month[age_months]:
        logger.error(f"Unrealistic weight: {child_data.weight} kg for child age {age_months} months.")
        raise HTTPException(status_code=400, detail="Unrealistic weight for child's age.")

    if child_data.height > max_height_by_month[age_months]:
        logger.error(f"Unrealistic height: {child_data.height} ft for child age {age_months} months.")
        raise HTTPException(status_code=400, detail="Unrealistic height for child's age.")

    # Construct the prompt for the AI model
    prompt = (
        f"You are a certified pediatric nutrition expert. Only use the data provided.\n\n"
        f"Create two sections:\n"
        f"1. General Advice: Based on age, gender, weight, and height.\n"
        f"2. Diet Plan: Actionable steps.\n\n"
        f"Child:\n"
        f"- DOB: {child_data.date_of_birth}\n"
        f"- Weight: {child_data.weight} kg\n"
        f"- Height: {child_data.height} ft\n"
        f"- Gender: {safe_gender}\n"
        f"- Allergies: {safe_allergies}\n"
        f"- Milestones: {', '.join([sanitize_input(m) for m in child_data.milestones])}\n"
        f"- Age: {age_months} months\n"
        f"Respond ONLY with dietary suggestions. Do not explain or reference external sources."
    )

    logger.info(f"Prompt generated for model: {prompt}")

    # 4. Send message & handle model errors
    try:
        response = chat_session.send_message(prompt)
        logger.info("Received response from model.")
    except Exception as e:
        logger.error("Model Error: Failed to get response", exc_info=True)
        raise HTTPException(status_code=500, detail="AI service unavailable at the moment.")

    # 5. Validate model response
    if not response.text or len(response.text.strip()) < 20:
        logger.error("Model response was empty or too short. Returning default error message.")
        return {
            "diet_plan": {
                "general_advice": [
                    {
                        "title": "Error",
                        "content": "Model failed to generate response. Try again later."
                    }
                ],
                "diet_suggestions": []
            }
        }

    # 6. Parse safely
    sections = response.text.split("\n\n")
    general_advice = []
    diet_suggestions = []

    for section in sections:
        lines = section.strip().split("\n")
        if len(lines) > 1:
            title = lines[0].strip().lower()
            content_lines = [line.lstrip("* ").strip() for line in lines[1:] if line.strip()]
            content = "\n".join(content_lines)

            if "general" in title:
                general_advice.append(content)
            else:
                diet_suggestions.append({"title": lines[0].strip(), "content": content})

    diet_plan = {"general_advice": [], "diet_suggestions": []}

    if general_advice:
        diet_plan["general_advice"].append({
            "title": "General Advice",
            "content": "\n".join(general_advice)
        })

    if diet_suggestions:
        diet_plan["diet_suggestions"] = diet_suggestions

    logger.info(f"Successfully generated nutrition plan for child_id={child_data.child_id}")

    return {"diet_plan": diet_plan}


# Follow-up question handler
def ask_follow_up(question):
    """
    Handle follow-up questions in the same chat session.
    :param question: Follow-up question from the parent
    :return: Model's response
    """
    response = chat_session.send_message(question)
    return response.text
