from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient
from datetime import datetime, timedelta
import random, bcrypt
from lib.email_utils import send_otp_email
from lib.jwt_utils import create_access_token
from fastapi.responses import JSONResponse

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
        raise HTTPException(status_code=400, detail="Email already registered")
    generate_and_send_otp(user.email)
    # Temporarily store password hash for use after OTP verification
    password_hash = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt())
    otp_collection.update_one(
        {"email": user.email},
        {"$set": {"password": password_hash.decode()}},
        upsert=True
    )
    return JSONResponse(
        status_code=200,
        content={
            "message": "OTP sent to your email. Please verify to complete signup.",
            "email": user.email
        }
    )

@router.post("/signup-verify")
async def signup_verify(verify: OTPVerification):
    record = otp_collection.find_one({"email": verify.email})
    if not record or record["otp"] != verify.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="OTP expired")

    users_collection.insert_one({
        "email": verify.email,
        "password": record["password"]
    })
    otp_collection.delete_many({"email": verify.email})
    return {"message": "Signup successful"}

# ------------------ LOGIN ------------------

@router.post("/login")
async def login_request(user: User):
    db_user = users_collection.find_one({"email": user.email})
    if not db_user or not db_user.get("password"):
        raise HTTPException(status_code=400, detail="Invalid email or password")
    
    if not bcrypt.checkpw(user.password.encode(), db_user["password"].encode()):
        raise HTTPException(status_code=400, detail="Invalid email or password")
    
    # Send OTP
    try:
        generate_and_send_otp(user.email)
        print("OTP sent to email:", user.email)
    except Exception as e:
        print(f"Error sending email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send OTP email")
    
    return JSONResponse(
        status_code=200,
        content={
            "message": "OTP sent to your email. Please verify to login.",
            "user_id": str(db_user["_id"])  # Convert ObjectId to string
        }
    )

@router.post("/verify-otp")
async def login_verify(verify: OTPVerification):
    record = otp_collection.find_one({"email": verify.email})
    if not record or record["otp"] != verify.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="OTP expired")

    otp_collection.delete_many({"email": verify.email})
    user = users_collection.find_one({"email": verify.email})
    
    # Create JWT token
    token = create_access_token({"email": user["email"]})
    print(token)
    return {
        "message": "Login successful",
        "user_id": str(user["_id"]),
        "access_token": token
    }
