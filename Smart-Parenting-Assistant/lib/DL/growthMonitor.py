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

# Define the root directory of the project
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
            
        print("Adding child initial growth data")
        # Insert child profile
        child_data = child.dict()
        result = growth_collection.insert_one(child_data)

        if not result.acknowledged:
            raise HTTPException(status_code=500, detail="Failed to add child")

        # Add initial growth data for the child
        growth_data = {
            "child_id": str(result.inserted_id),
            "date": datetime.utcnow(),
            "weight": child.weight,
            "height": child.height,
            "milestone": "Initial Data"
        }
        growth_collection.insert_one(growth_data)

        response_data =  {"message": "Child added successfully"}
        return JSONResponse(response_data, status_code=201)
    except Exception as e:
        print(f"Error adding child: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    
@router.post("/growth/add")
async def add_growth(data: GrowthData):
    # Add growth data
    growth_data = data.dict()
    result = growth_collection.insert_one(growth_data)
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to add growth data")
    # Update child's height and weight in their profile
    print("child_id: ", ObjectId(data.child_id))
    update_result = children_collection.update_one(
        {"_id": ObjectId(data.child_id)},
        {"$set": {"weight": data.weight, "height": data.height}}
    )

    if update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Child not found")
    
    response_data = {"message": "Growth data added successfully"}
    return JSONResponse(response_data, status_code=201)



# Add this logger setup at the top of your file
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.get("/growth-detection")
async def detect_growth(child_id: str, request: Request):
    try:
        # Fetch child data from the database
        child_data = children_collection.find_one({"_id": ObjectId(child_id)})
        if child_data is None:
            raise HTTPException(status_code=404, detail="Child not found or no data available")

        # ====== Phase 1: Data Protection ======

        # Basic Raw Validation (before decrypt)
        try:
            height_raw = float(child_data.get("height", 0))
            if not 30 <= height_raw * 30.48 <= 150:
                raise ValueError("Height out of valid range")
        except ValueError:
            logger.warning(f"[{request.client.host}] Invalid height data: {child_data.get('height')}")
            raise HTTPException(status_code=400, detail="Invalid height value")

        gender_raw = child_data.get("gender", "").lower()
        if gender_raw not in ["male", "female"]:
            logger.warning(f"[{request.client.host}] Invalid gender data: {gender_raw}")
            raise HTTPException(status_code=400, detail="Invalid gender value")

        if not child_data.get("date_of_birth"):
            logger.warning(f"[{request.client.host}] Missing DOB for child_id={child_id}")
            raise HTTPException(status_code=400, detail="Missing date of birth")

        # Decrypt sensitive fields
        name = decrypt_field(child_data.get("name"))
        gender = decrypt_field(child_data.get("gender"))
        dob = decrypt_field(child_data.get("date_of_birth"))
        allergies = decrypt_field(child_data.get("allergies"))

        height = height_raw * 30.48  # feet to cm
        weight = float(child_data.get("weight", 0))  # Optional use

        # Process DOB
        dob = dob.split("T")[0]
        dob = datetime.strptime(dob, "%Y-%m-%d")
        current_date = datetime.now()
        age_years = relativedelta(current_date, dob).years
        age_months = relativedelta(current_date, dob).months
        age = age_years * 12 + age_months

        if not (30 <= height <= 150 and 0 <= age <= 120):
            logger.warning(f"[{request.client.host}] Outlier detected. Age: {age}, Height: {height}")
            raise HTTPException(status_code=400, detail="Outlier input detected")

        # Encode gender
        gender_male = 1 if gender.lower() == "male" else 0
        gender_female = 1 if gender.lower() == "female" else 0

        df = pd.DataFrame({
            "Age (months)": [age],
            "Height (cm)": [height],
            "Gender_female": [gender_female],
            "Gender_male": [gender_male]
        })

        # === Optional: Model Integrity Check ===
        model_path = os.path.join(root_dir, 'lib', 'Model', 'random_forest_model.pkl')
        expected_hash = "PUT_YOUR_MODEL_HASH_HERE"
        actual_hash = hashlib.sha256(open(model_path, 'rb').read()).hexdigest()
        if actual_hash != expected_hash:
            logger.error(f"Model integrity check failed from {request.client.host}")
            raise HTTPException(status_code=500, detail="Model integrity verification failed")

        # Load model and encoder
        with open(model_path, "rb") as file:
            loaded_model = pickle.load(file)
        with open(os.path.join(root_dir, 'lib', 'Model', 'label_encoder.pkl'), "rb") as file:
            loaded_label_encoder = pickle.load(file)

        prediction = loaded_model.predict(df)
        nutrition_status = loaded_label_encoder.inverse_transform(prediction)[0]

        response_data = {
            "data": {
                "child_id": str(child_data["_id"]),
                "name": name,
                "age": age,
                "height": height,
                "gender": gender,
                "nutrition_status": nutrition_status,
            }
        }

        logger.info(f"[{request.client.host}] Prediction success for {name}, Age: {age}, Height: {height}")
        return JSONResponse(response_data, status_code=200)

    except Exception as e:
        logger.exception(f"Error during growth detection for child_id={child_id}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/growth/getGrowthData/{child_id}")
async def get_growth_data(child_id: str):
    try:
        growth_data = list(growth_collection.find({"child_id": child_id}).sort("date", 1))
        if not growth_data:
            raise HTTPException(status_code=404, detail="No growth data found for this child")
        response_data = {"message": "Growth data found", "data": growth_data}
        
        for data in growth_data:
            data["_id"] = str(data["_id"])

        for data in growth_data:
            if "date" in data:  # Replace "date" with the actual field name
                data["date"] = data["date"].isoformat()
        
    
        return JSONResponse(response_data, status_code=200)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
