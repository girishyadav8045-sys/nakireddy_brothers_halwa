from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests
from dotenv import load_dotenv
import os
from pathlib import Path
from database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi import APIRouter, Depends, HTTPException
import uuid

BASE_DIR = Path(__file__).resolve().parent.parent
env_path = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=env_path)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
print(GOOGLE_CLIENT_ID)


router = APIRouter(prefix="/auth", tags=["Auth"])

# --- SCHEMAS ---
class GoogleLoginRequest(BaseModel):
    token: str

class CompleteProfileRequest(BaseModel):
    email: str
    first_name: str
    last_name: str
    phone_number: str

# ==========================================
# 1. THE TRAFFIC COP (Google Login)
# ==========================================
@router.post("/google")
async def verify_google_login(req: GoogleLoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        # 1. Verify token with Google
        idinfo = id_token.verify_oauth2_token(
            req.token, 
            requests.Request(), 
            GOOGLE_CLIENT_ID
        )
        
        email = idinfo['email']
        name = idinfo.get('name', 'Unknown')

        # print("-----------------------",email)

        # 2. Check if Admin
        admin_query = text("SELECT admin_id, admin_name FROM admins WHERE email = :email")
        admin_res = await db.execute(admin_query, {"email": email})
        admin_row = admin_res.fetchone()
        
        if admin_row:
            return {
                "status": "success", 
                "role": "admin", 
                "email": email,
                "admin_id": str(admin_row.admin_id), # <-- Hand this to the frontend developer!
                "message": f"Welcome back, {admin_row.admin_name}"
            }

        # 3. Check if Existing Customer
        cust_query = text("SELECT customer_id FROM customers WHERE email = :email")
        cust_res = await db.execute(cust_query, {"email": email})
        # print(cust_res)
        if cust_res.fetchone():
            return {
                "status": "success", 
                "role": "customer", 
                "email": email,
                "message": "Welcome back"
            }

        # 4. If neither, it's a NEW USER! Send them to the profile page.
        # print(email,name)
        return {
            "status": "success", 
            "role": "new_user", 
            "email": email, 
            "name": name,
            "message": "Please complete your profile"
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Google Token")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Authentication failed")


# ==========================================
# 2. SAVE NEW USER (Complete Profile)
# ==========================================
@router.post("/complete-profile")
async def complete_profile(req: CompleteProfileRequest, db: AsyncSession = Depends(get_db)):
    try:
        # # 1. Double check the phone number isn't already used
        # check_query = text("SELECT customer_id FROM customers WHERE phone_number = :phone")
        # check_res = await db.execute(check_query, {"phone": req.phone_number})
        # if check_res.fetchone():
        #     raise HTTPException(status_code=400, detail="Phone number already registered.")

        # 2. Generate custom ID
        new_cust_id = str(uuid.uuid4())

        # 3. Save to database
        # (Assuming your table has these exact column names)
        insert_query = text("""
            INSERT INTO customers (customer_id, first_name, last_name, email, phone_number)
            VALUES (:id, :fname, :lname, :email, :phone)
        """)
        
        await db.execute(insert_query, {
            "id": new_cust_id,
            "fname": req.first_name,
            "lname": req.last_name,
            "email": req.email,
            "phone": req.phone_number
        })
        
        await db.commit()

        return {
            "status": "success", 
            "message": "Profile created successfully!"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to create profile")