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

@router.get("/growth-detection")
async def detect_growth(child_id: str):
    try:
        # Fetch child data from the database
        child_data = children_collection.find_one({"_id": ObjectId(child_id)})

        if child_data is None:
            raise HTTPException(status_code=404, detail="Child not found or no data available")

        # Decrypt relevant fields
        name = decrypt_field(child_data.get("name"))
        gender = decrypt_field(child_data.get("gender"))
        dob = decrypt_field(child_data.get("date_of_birth"))
        allergies = decrypt_field(child_data.get("allergies"))

        # Print decrypted fields to ensure correctness
        print(f"Decrypted Name: {name}, Gender: {gender}, DOB: {dob}, Allergies: {allergies}")

        # Height and weight should be treated as numbers directly
        try:
            height = float(child_data.get("height", 0))  # Default to 0 if height is missing
            weight = float(child_data.get("weight", 0))  # Default to 0 if weight is missing
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid height or weight data")

        print(f"Height: {height}, Weight: {weight}")

        # Convert height from feet to centimeters
        height = height * 30.48  # Convert height from feet to centimeters

        # Decrypt date_of_birth and convert it to datetime
        if dob:
            dob = dob.split("T")[0]  # Extracts just "2024-05-24" if it's in ISO format
            dob = datetime.strptime(dob, "%Y-%m-%d")
        else:
            raise HTTPException(status_code=400, detail="Missing or invalid date of birth")

        # Get current date
        current_date = datetime.now()

        # Calculate age in years and months
        age_years = relativedelta(current_date, dob).years
        age_months = relativedelta(current_date, dob).months
        age = age_years * 12 + age_months
        
        print(f"Age: {age} months")

        # Check if required features are available
        if not (height and gender):
            raise HTTPException(status_code=400, detail="Missing required features (height, gender, age)")

        # Encode and preprocess input features
        gender_male = 0
        gender_female = 0
        if gender.lower() == "male":
            gender_male = 1
            gender_female = 0
        elif gender.lower() == "female":
            gender_female = 1
            gender_male = 0

        # Prepare data for prediction
        df = pd.DataFrame({
            "Age (months)": [age],
            "Height (cm)": [height],
            "Gender_female": [gender_female],
            "Gender_male": [gender_male]
        })

        # Set paths for model and label encoder
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        store_path = os.path.join(root_dir, 'lib', 'Model')

        model_path = store_path + "\\random_forest_model.pkl"
        label_encoder_path = store_path + "\\label_encoder.pkl"

        # Load the saved RandomForest model
        with open(model_path, "rb") as file:
            loaded_model = pickle.load(file)

        # Load the saved LabelEncoder
        with open(label_encoder_path, "rb") as file:
            loaded_label_encoder = pickle.load(file)

        # Make prediction
        prediction = loaded_model.predict(df)
        nutrition_status = loaded_label_encoder.inverse_transform(prediction)[0]

        # Prepare the response data
        data = {
            "child_id": str(child_data["_id"]),
            "name": name,  # Decrypted name
            "age": age,
            "height": height,
            "gender": gender,
            "nutrition_status": nutrition_status,
        }

        response_data = {
            "data": data
        }

        return JSONResponse(response_data, status_code=200)

    except Exception as e:
        print(f"Error during growth detection: {e}")
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
