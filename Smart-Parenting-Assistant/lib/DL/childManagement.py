import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId
from typing import List
from datetime import datetime
from fastapi.responses import JSONResponse
from lib.encryption_utils import encrypt_field, decrypt_field

# ------------------ Logging Setup ------------------

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
log_dir = os.path.join(root_dir, "logs")
os.makedirs(log_dir, exist_ok=True)

log_file_path = os.path.join(log_dir, "child_management.log")

logger = logging.getLogger("child_management")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

# ------------------ FastAPI and DB Setup ------------------

client = MongoClient("mongodb://localhost:27017/")
db = client.smart_parenting
children_collection = db.children
growth_collection = db.growth_data

router = APIRouter()

# ------------------ Pydantic Model ------------------

class ChildModel(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    date_of_birth: str = Field(..., pattern=r"\d{4}-\d{2}-\d{2}")
    gender: str = Field(..., pattern=r"^(Male|Female|Other)$")
    allergies: str
    weight: float = Field(..., ge=1)
    height: float = Field(..., ge=0.5)
    parentId: str

# ------------------ Serializer ------------------

def child_serializer(child) -> dict:
    return {
        "id": str(child["_id"]),
        "name": decrypt_field(child["name"]),
        "date_of_birth": decrypt_field(child["date_of_birth"]),
        "gender": decrypt_field(child["gender"]),
        "allergies": decrypt_field(child["allergies"]),
        "weight": float(decrypt_field(child["weight"])),
        "height": float(decrypt_field(child["height"])),
        "parentId": child["parentId"]
    }

# ------------------ Routes ------------------

@router.post("/", response_model=dict)
async def add_child(child: ChildModel):
    try:
        encrypted_data = {
            "name": encrypt_field(child.name),
            "date_of_birth": encrypt_field(child.date_of_birth),
            "gender": encrypt_field(child.gender),
            "allergies": encrypt_field(child.allergies),
            "weight": encrypt_field(str(child.weight)),
            "height": encrypt_field(str(child.height)),
            "parentId": child.parentId
        }

        result = children_collection.insert_one(encrypted_data)

        if result.acknowledged:
            growth_data = {
                "child_id": str(result.inserted_id),
                "date": datetime.utcnow(),
                "weight": child.weight,
                "height": child.height,
                "milestone": "Initial Data"
            }
            growth_collection.insert_one(growth_data)
            logger.info(f"Parent {child.parentId} added new child: {child.name}")
            return JSONResponse({"message": "Child added successfully"}, status_code=201)
        else:
            raise HTTPException(status_code=500, detail="Failed to add child")
    except Exception as e:
        logger.error(f"Error adding child for parent {child.parentId}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[dict])
async def get_children_by_parent(parentId: str):
    children = children_collection.find({"parentId": parentId})
    children_list = [child_serializer(child) for child in children]
    if not children_list:
        logger.info(f"No children found for parent {parentId}")
        raise HTTPException(status_code=404, detail="No children found for this parent")
    logger.info(f"Fetched children for parent {parentId}")
    return children_list

@router.get("/{child_id}", response_model=dict)
async def get_child_by_id(child_id: str):
    child = children_collection.find_one({"_id": ObjectId(child_id)})
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    return child_serializer(child)

@router.put("/{child_id}", response_model=dict)
async def update_child(child_id: str, updated_child: ChildModel):
    try:
        existing = children_collection.find_one({"_id": ObjectId(child_id)})
        if not existing:
            raise HTTPException(status_code=404, detail="Child not found")

        old_data = child_serializer(existing)

        updated_fields = {}
        changes = []

        for field in updated_child.dict():
            old_value = old_data.get(field)
            new_value = getattr(updated_child, field)
            if str(old_value) != str(new_value):
                updated_fields[field] = encrypt_field(str(new_value)) if field not in ["parentId"] else new_value
                changes.append(f"{field} changed from '{old_value}' to '{new_value}'")

        if not updated_fields:
            logger.info(f"No changes detected for child {child_id} by parent {updated_child.parentId}")
            return {"message": "No updates made (data identical)"}

        children_collection.update_one({"_id": ObjectId(child_id)}, {"$set": updated_fields})

        growth_collection.find_one_and_update(
            {"child_id": child_id},
            {"$set": {"weight": updated_child.weight, "height": updated_child.height}},
            sort=[("date", -1)]
        )

        logger.info(f"Parent {updated_child.parentId} updated child {child_id}: " + "; ".join(changes))
        return {"message": "Child updated successfully"}
    except Exception as e:
        logger.error(f"Error updating child {child_id} by parent {updated_child.parentId}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{child_id}", response_model=dict)
async def delete_child(child_id: str):
    child = children_collection.find_one({"_id": ObjectId(child_id)})
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    parent_id = child.get("parentId")
    children_collection.delete_one({"_id": ObjectId(child_id)})
    growth_collection.delete_many({"child_id": child_id})
    logger.info(f"Parent {parent_id} deleted child {child_id}")
    return {"message": "Child deleted successfully"}
