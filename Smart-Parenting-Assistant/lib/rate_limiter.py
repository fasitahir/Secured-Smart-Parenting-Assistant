from fastapi import Request, HTTPException, Depends
from lib.jwt_utils import verify_token
from datetime import datetime, timedelta

# In-memory store for request timestamps (replace with Redis for scale)
rate_limit_cache = {}

MAX_REQUESTS = 2
WINDOW_SECONDS = 60  # Time window

def rate_limiter(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = auth_header.split(" ")[1]
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_email = payload["email"]
    now = datetime.utcnow()

    if user_email not in rate_limit_cache:
        rate_limit_cache[user_email] = []

    # Remove expired timestamps
    rate_limit_cache[user_email] = [
        ts for ts in rate_limit_cache[user_email] if now - ts < timedelta(seconds=WINDOW_SECONDS)
    ]

    if len(rate_limit_cache[user_email]) >= MAX_REQUESTS:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Log this request
    rate_limit_cache[user_email].append(now)
