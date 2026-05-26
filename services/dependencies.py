from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from services.jwt_handler import verify_access_token

# This automatically looks for the 'Authorization: Bearer <token>' header from the frontend
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """The general Bouncer: Checks if the user is logged in at all."""
    token = credentials.credentials
    payload = verify_access_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired token. Please log in again."
        )
        
    return payload # Returns the dictionary, e.g., {"user_id": "cust_123", "role": "customer"}

async def get_admin_user(current_user: dict = Depends(get_current_user)):
    """The VIP Bouncer: Checks if the logged-in user is specifically an Admin."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=403, 
            detail="Access Denied. Admins only."
        )
    return current_user