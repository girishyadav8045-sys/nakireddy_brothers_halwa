import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from schemas import AdminAddressSchema

router = APIRouter(prefix="/admin_address", tags=["admin_address"])

@router.post("/admin/{admin_id}/add-address")
async def add_admin_address(admin_id: str, address_data: AdminAddressSchema, db: AsyncSession = Depends(get_db)):
    try:
        # 1. Fetch the admin's current addresses list (using plural 'addresses')
        query = text("SELECT addresses FROM admins WHERE admin_id = CAST(:id AS UUID)")
        result = await db.execute(query, {"id": admin_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Admin not found")

        # 2. Parse using row.addresses instead of row.address
        current_addresses = row.addresses if row.addresses is not None else []
        
        if isinstance(current_addresses, str):
            current_addresses = json.loads(current_addresses)

        # 3. Convert Pydantic schema to dictionary and inject a unique address ID
        new_address_dict = address_data.model_dump()
        new_address_dict["address_id"] = f"adrs_{uuid.uuid4().hex[:10]}"
        
        current_addresses.append(new_address_dict)

        # 4. Save back using the correct column name: addresses
        update_query = text("""
            UPDATE admins 
            SET addresses = :new_address_list 
            WHERE admin_id = CAST(:id AS UUID)
        """)
        
        await db.execute(update_query, {
            "new_address_list": json.dumps(current_addresses),
            "id": admin_id
        })
        
        await db.commit()

        return {
            "status": "success",
            "message": "Address added successfully to Admin profile.",
            "data": current_addresses
        }

    except Exception as e:
        await db.rollback()
        import traceback
        print("\n🚨 ADMIN ADDRESS CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to add address")
    

@router.get("/admin/{admin_id}/addresses")
async def get_admin_addresses(admin_id: str, db: AsyncSession = Depends(get_db)):
    try:
        # 1. Fetch using plural 'addresses'
        query = text("SELECT addresses FROM admins WHERE admin_id = CAST(:id AS UUID)")
        result = await db.execute(query, {"id": admin_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Admin not found")

        # 2. Extract using row.addresses instead of row.address
        address_list = row.addresses if row.addresses is not None else []
        
        if isinstance(address_list, str):
            address_list = json.loads(address_list)

        return {
            "status": "success",
            "total_addresses": len(address_list),
            "data": address_list
        }

    except HTTPException:
        raise 
    except Exception as e:
        import traceback
        print("\n🚨 FETCH ADMIN ADDRESS CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch addresses")
    


@router.delete("/admin/{admin_id}/delete-address/{address_id}")
async def delete_admin_address(admin_id: str, address_id: str, db: AsyncSession = Depends(get_db)):
    try:
        # 1. Fetch using plural 'addresses'
        query = text("SELECT addresses FROM admins WHERE admin_id = CAST(:id AS UUID)")
        result = await db.execute(query, {"id": admin_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Admin not found")

        # 2. Extract using row.addresses
        current_addresses = row.addresses if row.addresses is not None else []
        if isinstance(current_addresses, str):
            current_addresses = json.loads(current_addresses)

        # 3. Filter out the targeted address
        updated_addresses = [
            addr for addr in current_addresses 
            if addr.get("address_id") != address_id
        ]

        if len(current_addresses) == len(updated_addresses):
             raise HTTPException(status_code=404, detail="Address not found in admin profile")

        # 4. Update back into the plural 'addresses' column
        update_query = text("""
            UPDATE admins 
            SET addresses = :new_address_list 
            WHERE admin_id = CAST(:id AS UUID)
        """)
        
        await db.execute(update_query, {
            "new_address_list": json.dumps(updated_addresses),
            "id": admin_id
        })
        
        await db.commit()

        return {
            "status": "success",
            "message": "Address deleted successfully.",
            "data": updated_addresses 
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        print("\n🚨 ADMIN ADDRESS DELETE CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to delete address")