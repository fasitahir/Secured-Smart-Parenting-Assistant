from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient
from datetime import datetime, timedelta
import random, bcrypt
from lib.email_utils import send_otp_email
from lib.jwt_utils import create_access_token
from fastapi.responses import JSONResponse
import os
import logging

client = MongoClient("mongodb://localhost:27017/")
db = client.smart_parenting
users_collection = db.users
otp_collection = db.otp_verifications

router = APIRouter()

# Models
class User(BaseModel):
    email: EmailStr
    password: str

class OTPVerification(BaseModel):
    email: EmailStr
    otp: str

# ------------------ Logging Setup ------------------

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
log_dir = os.path.join(root_dir, "logs")
os.makedirs(log_dir, exist_ok=True)

log_file_path = os.path.join(log_dir, "authentication.log")

logger = logging.getLogger("authentication")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)



# Generate and store OTP
def generate_and_send_otp(email: str):
    otp = str(random.randint(100000, 999999))
    otp_collection.delete_many({"email": email})  # Invalidate previous OTPs
    otp_collection.insert_one({
        "email": email,
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=5)
    })
    send_otp_email(email, otp)

# ------------------ SIGNUP ------------------
@router.post("/signup")
async def signup_request(user: User):
    if users_collection.find_one({"email": user.email}):
        logger.warning(f"Signup attempt with already registered email: {user.email}")
        raise HTTPException(status_code=400, detail="Email already registered")

    logger.info(f"Initiating signup process for: {user.email}")
    generate_and_send_otp(user.email)
    password_hash = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt())
    
    otp_collection.update_one(
        {"email": user.email},
        {"$set": {"password": password_hash.decode()}},
        upsert=True
    )
    logger.info(f"OTP sent and password hash stored for: {user.email}")

    return JSONResponse(
        status_code=200,
        content={
            "message": "OTP sent to your email. Please verify to complete signup.",
            "email": user.email
        }
    )


@router.post("/signup-verify")
async def signup_verify(verify: OTPVerification):
    logger.info(f"Verifying signup OTP for: {verify.email}")
    record = otp_collection.find_one({"email": verify.email})

    if not record or record["otp"] != verify.otp:
        logger.warning(f"Invalid OTP attempt for: {verify.email}")
        raise HTTPException(status_code=400, detail="Invalid OTP")

    if datetime.utcnow() > record["expires_at"]:
        logger.warning(f"Expired OTP attempt for: {verify.email}")
        raise HTTPException(status_code=400, detail="OTP expired")

    users_collection.insert_one({
        "email": verify.email,
        "password": record["password"]
    })
    otp_collection.delete_many({"email": verify.email})
    logger.info(f"Signup completed successfully for: {verify.email}")
    
    return {"message": "Signup successful"}

# ------------------ LOGIN ------------------

@router.post("/login")
async def login_request(user: User):
    logger.info(f"Login attempt for: {user.email}")
    db_user = users_collection.find_one({"email": user.email})

    if not db_user or not db_user.get("password"):
        logger.warning(f"Login failed (user not found or password missing): {user.email}")
        raise HTTPException(status_code=400, detail="Invalid email or password")
    
    if not bcrypt.checkpw(user.password.encode(), db_user["password"].encode()):
        logger.warning(f"Invalid password attempt for: {user.email}")
        raise HTTPException(status_code=400, detail="Invalid email or password")
    
    try:
        generate_and_send_otp(user.email)
        logger.info(f"OTP sent for login verification to: {user.email}")
    except Exception as e:
        logger.error(f"Error sending OTP email to {user.email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send OTP email")
    
    return JSONResponse(
        status_code=200,
        content={
            "message": "OTP sent to your email. Please verify to login.",
            "user_id": str(db_user["_id"])
        }
    )
@router.post("/verify-otp")
async def login_verify(verify: OTPVerification):
    logger.info(f"Verifying login OTP for: {verify.email}")
    record = otp_collection.find_one({"email": verify.email})

    if not record or record["otp"] != verify.otp:
        logger.warning(f"Invalid OTP attempt for login: {verify.email}")
        raise HTTPException(status_code=400, detail="Invalid OTP")

    if datetime.utcnow() > record["expires_at"]:
        logger.warning(f"Expired OTP attempt for login: {verify.email}")
        raise HTTPException(status_code=400, detail="OTP expired")

    otp_collection.delete_many({"email": verify.email})
    user = users_collection.find_one({"email": verify.email})
    token = create_access_token({"email": user["email"]})
    logger.info(f"Login successful for: {verify.email}")

    return {
        "message": "Login successful",
        "user_id": str(user["_id"]),
        "access_token": token
    }
