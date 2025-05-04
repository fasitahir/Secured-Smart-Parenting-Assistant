import pickle
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId
from fastapi import APIRouter, HTTPException
import os
from dateutil.relativedelta import relativedelta
import pandas as pd
from lib.encryption_utils import decrypt_field
from fastapi import Request
import hashlib
import logging
import os
import logging
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from datetime import datetime
from bson import ObjectId
from pymongo import MongoClient
from lib.encryption_utils import  decrypt_field
from lib.rate_limiter import rate_limiter

# ------------------ Logging Setup ------------------

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
log_dir = os.path.join(root_dir, "logs")
os.makedirs(log_dir, exist_ok=True)

log_file_path = os.path.join(log_dir, "child_growth.log")

logger = logging.getLogger("child_growth")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


# MongoDB setup (adjust your URI)
client = MongoClient("mongodb://localhost:27017")
db = client["child_care"]
children_collection = db["children"]


# MongoDB Setup
client = MongoClient("mongodb://localhost:27017/")
db = client.smart_parenting
growth_collection = db.growth_data
children_collection = db.children
# FastAPI App
router = APIRouter()

# Pydantic Models
class GrowthData(BaseModel):
    child_id: str
    date: datetime
    weight: float
    height: float
    milestone: str = None


@router.post("/growth/initial")
async def add_child(child: GrowthData):
    try:
        logger.info("Received request to add initial growth data")
        child_data = child.dict()
        result = growth_collection.insert_one(child_data)

        if not result.acknowledged:
            logger.error("Failed to add initial growth data")
            raise HTTPException(status_code=500, detail="Failed to add child")

        growth_data = {
            "child_id": str(result.inserted_id),
            "date": datetime.utcnow(),
            "weight": child.weight,
            "height": child.height,
            "milestone": "Initial Data"
        }
        growth_collection.insert_one(growth_data)

        logger.info(f"Initial growth data added for child_id={result.inserted_id}")
        return JSONResponse({"message": "Child added successfully"}, status_code=201)

    except Exception as e:
        logger.error(f"Error adding initial growth data: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    
@router.post("/growth/add")
async def add_growth(data: GrowthData):
    try:
        logger.info(f"Adding growth data for child_id={data.child_id}")
        growth_data = data.dict()
        result = growth_collection.insert_one(growth_data)

        update_result = children_collection.update_one(
            {"_id": ObjectId(data.child_id)},
            {"$set": {"weight": data.weight, "height": data.height}}
        )

        if update_result.matched_count == 0:
            logger.warning(f"No child found with ID: {data.child_id}")
            raise HTTPException(status_code=404, detail="Child not found")

        logger.info(f"Growth data added for child_id={data.child_id}")
        return JSONResponse({"message": "Growth data added successfully"}, status_code=201)

    except Exception as e:
        logger.error(f"Error adding growth data: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")



# Helper Functions
def generate_model_hash(model_path):
    with open(model_path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def hash_model_path(model_path):
    return hashlib.sha256(model_path.encode()).hexdigest()


def verify_model_integrity(model_path, expected_hash):
    actual_hash = generate_model_hash(model_path)
    if actual_hash != expected_hash:
        logger.error(f"Model integrity check failed. Actual: {actual_hash}, Expected: {expected_hash}")
        return False
    return True


@router.get("/growth-detection")
async def detect_growth(child_id: str, request: Request, _: None = Depends(rate_limiter)):
    try:
        logger.info(f"Growth detection request received for child_id: {child_id}")

        # Fetch child data from DB
        child_data = children_collection.find_one({"_id": ObjectId(child_id)})
        if child_data is None:
            logger.warning(f"No child found with ID: {child_id}")
            raise HTTPException(status_code=404, detail="Child not found")

        # Decrypt fields
        name = decrypt_field(child_data.get("name"))
        gender = decrypt_field(child_data.get("gender")).lower()
        dob = decrypt_field(child_data.get("date_of_birth"))
        allergies = decrypt_field(child_data.get("allergies"))
        height_raw = float(decrypt_field(child_data.get("height", "0")))

        logger.info(f"Child data decrypted for: {name}")

        # Parse and calculate age
        dob = dob.split("T")[0]
        dob = datetime.strptime(dob, "%Y-%m-%d")
        current_date = datetime.now()
        age_delta = relativedelta(current_date, dob)
        age = age_delta.years * 12 + age_delta.months

        logger.info(f"Calculated age in months: {age}")

        # Gender validation
        if gender not in ["male", "female"]:
            logger.error(f"Invalid gender found: {gender}")
            raise HTTPException(status_code=400, detail="Invalid gender")

        # Encode gender
        gender_male = int(gender == "male")
        gender_female = int(gender == "female")

        # Validate height
        height = height_raw * 30.48  # Convert from feet to cm
        if not 30 <= height <= 150:
            logger.warning(f"Height {height} cm is out of expected range for child {name}")
            raise ValueError("Height out of valid range")

        # Verify model integrity
        model_path = "lib/Model/random_forest_model.pkl"
        expected_model_hash = os.getenv("EXPECTED_MODEL_HASH")
        if not verify_model_integrity(model_path, expected_model_hash):
            logger.critical("Model integrity verification failed.")
            raise HTTPException(status_code=500, detail="Model integrity check failed")

        # Prepare data
        df = pd.DataFrame({
            "Age (months)": [age],
            "Height (cm)": [height],
            "Gender_female": [gender_female],
            "Gender_male": [gender_male]
        })

        # Load model and label encoder
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        label_encoder_path = "lib/Model/label_encoder.pkl"
        with open(label_encoder_path, "rb") as file:
            loaded_label_encoder = pickle.load(file)

        # Predict
        prediction = model.predict(df)
        nutrition_status = loaded_label_encoder.inverse_transform(prediction)[0]

        logger.info(
            f"Prediction successful for {name} | Age: {age} months | Height: {height:.2f} cm | Status: {nutrition_status}"
        )

        # Construct response
        response_data = {
            "data": {
                "child_id": str(child_data["_id"]),
                "name": name,
                "age": age,
                "height": height,
                "gender": gender,
                "nutrition_status": nutrition_status,
            },
            "message": "Prediction successful"
        }

        return JSONResponse(response_data, status_code=200)

    except HTTPException as http_err:
        logger.error(f"HTTPException for child_id={child_id}: {http_err.detail}")
        raise http_err

    except Exception as e:
        logger.exception(f"Unhandled exception during growth detection for child_id={child_id}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/growth/getGrowthData/{child_id}")
async def get_growth_data(child_id: str):
    try:
        logger.info(f"Fetching growth data for child_id={child_id}")
        growth_data = list(growth_collection.find({"child_id": child_id}).sort("date", 1))

        if not growth_data:
            logger.warning(f"No growth data found for child_id={child_id}")
            raise HTTPException(status_code=404, detail="No growth data found for this child")

        for data in growth_data:
            data["_id"] = str(data["_id"])
            if "date" in data:
                data["date"] = data["date"].isoformat()

        logger.info(f"Growth data fetched successfully for child_id={child_id}")
        return JSONResponse({"message": "Growth data found", "data": growth_data}, status_code=200)

    except Exception as e:
        logger.error(f"Error fetching growth data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
