import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timezone
from database import get_db
from schemas import CreateCouponRequest, ValidateCouponRequest, UpdateCouponRequest

router = APIRouter(prefix="/coupons", tags=["Coupons"])

# ==========================================
# 1. ADMIN: CREATE COUPON
# ==========================================
@router.post("/admin/create_coupon")
async def admin_create_coupon(req: CreateCouponRequest, db: AsyncSession = Depends(get_db)):
    try:
        # Uppercase the code so "halwa10" and "HALWA10" are treated the same
        clean_code = req.code.strip().upper()

        insert_query = text("""
            INSERT INTO coupons (
                code, discount_type, discount_value, min_order_value, 
                max_discount, start_date, end_date, usage_limit, is_active
            ) VALUES (
                :code, :type, :value, :min_order, 
                :max_disc, :start, :end, :limit, :active
            )
        """)

        await db.execute(insert_query, {
            "code": clean_code,
            "type": req.discount_type.lower(),
            "value": req.discount_value,
            "min_order": req.min_order_value,
            "max_disc": req.max_discount,
            "start": req.start_date,
            "end": req.end_date,
            "limit": req.usage_limit,
            "active": req.is_active
        })
        
        await db.commit()
        return {"status": "success", "message": f"Coupon {clean_code} created successfully!"}

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create coupon: {str(e)}")



# ==========================================
# 2. coupons list
# ==========================================

@router.get("/admin/coupons_list")
async def admin_get_all_coupons(db: AsyncSession = Depends(get_db)):
    try:
        # Fetch all coupons, ordering by the most recently created first
        query = text("""
            SELECT 
                code, discount_type, discount_value, min_order_value, 
                max_discount, start_date, end_date, usage_limit, 
                used_count, is_active, created_at 
            FROM coupons 
            ORDER BY created_at DESC
        """)
        
        result = await db.execute(query)
        rows = result.fetchall()

        coupons_list = []
        for row in rows:
            coupons_list.append({
                "code": row.code,
                "discount_type": row.discount_type,
                "discount_value": row.discount_value,
                "min_order_value": row.min_order_value,
                "max_discount": row.max_discount,
                
                # We use .isoformat() to safely convert Python datetime objects to JSON strings.
                # If the date is NULL in the database, it safely returns None (null in JSON).
                "start_date": row.start_date.isoformat() if row.start_date else None,
                "end_date": row.end_date.isoformat() if row.end_date else None,
                
                "usage_limit": row.usage_limit,
                "used_count": row.used_count,
                "is_active": row.is_active,
                "created_at": row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else None
            })

        return {
            "status": "success",
            "total_coupons": len(coupons_list),
            "data": coupons_list
        }

    except Exception as e:
        import traceback
        print("\n🚨 ADMIN COUPON LIST CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch coupons list")



    


# ==========================================
# 5. ADMIN: UPDATE COUPON DETAILS
# ==========================================
@router.put("/admin/update_coupon/{code}")
async def admin_update_coupon(code: str, req: UpdateCouponRequest, db: AsyncSession = Depends(get_db)):
    try:
        clean_code = code.strip().upper()

        # 1. Fetch the existing coupon
        fetch_query = text("""
            SELECT discount_type, discount_value, min_order_value, max_discount, 
                   start_date, end_date, usage_limit, is_active 
            FROM coupons WHERE code = :code
        """)
        result = await db.execute(fetch_query, {"code": clean_code})
        existing_coupon = result.fetchone()

        if not existing_coupon:
            raise HTTPException(status_code=404, detail="Coupon not found.")

        # 2. Merge old data with new data
        # If the Admin provided a new value, use it. Otherwise, keep the old value.
        updated_data = {
            "type": req.discount_type.lower() if req.discount_type else existing_coupon.discount_type,
            "value": req.discount_value if req.discount_value is not None else existing_coupon.discount_value,
            "min_order": req.min_order_value if req.min_order_value is not None else existing_coupon.min_order_value,
            "max_disc": req.max_discount if req.max_discount is not None else existing_coupon.max_discount,
            "start": req.start_date if req.start_date is not None else existing_coupon.start_date,
            "end": req.end_date if req.end_date is not None else existing_coupon.end_date,
            "limit": req.usage_limit if req.usage_limit is not None else existing_coupon.usage_limit,
            "active": req.is_active if req.is_active is not None else existing_coupon.is_active,
            "code": clean_code
        }

        # 3. Save the updated details back to the database
        update_query = text("""
            UPDATE coupons 
            SET discount_type = :type,
                discount_value = :value,
                min_order_value = :min_order,
                max_discount = :max_disc,
                start_date = :start,
                end_date = :end,
                usage_limit = :limit,
                is_active = :active
            WHERE code = :code
        """)

        await db.execute(update_query, updated_data)
        await db.commit()

        return {
            "status": "success",
            "message": f"Coupon {clean_code} has been successfully updated."
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        print("\n🚨 COUPON UPDATE CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error updating coupon details")

    



# ==========================================
# 3. ADMIN: HARD DELETE COUPON
# ==========================================
@router.delete("/admin/delete_coupon/{code}")
async def admin_delete_coupon(code: str, db: AsyncSession = Depends(get_db)):
    try:
        clean_code = code.strip().upper()

        # 1. Fetch the coupon to see if it exists
        query = text("SELECT used_count FROM coupons WHERE code = :code")
        result = await db.execute(query, {"code": clean_code})
        coupon = result.fetchone()

        if not coupon:
            raise HTTPException(status_code=404, detail="Coupon not found.")

        # 2. The Safety Check
        # if coupon.used_count > 0:
        #     raise HTTPException(
        #         status_code=400, 
        #         detail=f"Cannot delete '{clean_code}' because it has been used {coupon.used_count} times. Please deactivate it instead."
        #     )

        # 3. Safe to delete
        delete_query = text("DELETE FROM coupons WHERE code = :code")
        await db.execute(delete_query, {"code": clean_code})
        
        await db.commit()
        return {"status": "success", "message": f"Coupon {clean_code} permanently deleted."}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        print("\n🚨 COUPON DELETE CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error deleting coupon")


# ==========================================
# 4. ADMIN: TOGGLE COUPON STATUS (Soft Delete)
# ==========================================
@router.put("/admin/toggle_coupon/{code}")
async def admin_toggle_coupon(code: str, db: AsyncSession = Depends(get_db)):
    try:
        clean_code = code.strip().upper()

        # 1. Fetch the current status
        query = text("SELECT is_active FROM coupons WHERE code = :code")
        result = await db.execute(query, {"code": clean_code})
        coupon = result.fetchone()

        if not coupon:
            raise HTTPException(status_code=404, detail="Coupon not found.")

        # 2. Flip the status (If True, make False. If False, make True)
        new_status = not coupon.is_active
        status_text = "Activated" if new_status else "Deactivated"

        update_query = text("UPDATE coupons SET is_active = :status WHERE code = :code")
        await db.execute(update_query, {"status": new_status, "code": clean_code})
        
        await db.commit()
        
        return {
            "status": "success", 
            "message": f"Coupon {clean_code} has been {status_text}.",
            "is_active": new_status
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Error toggling coupon status")
    


#active coupons
@router.get("/active_coupons/{customer_id}")
async def get_active_public_coupons(customer_id: str,db: AsyncSession = Depends(get_db)):
    try:
        now = datetime.now(timezone.utc)
        
        # Only fetch coupons that are active, haven't hit their usage limit, 
        # and are within their valid date range.
        query = text("""
                SELECT 
                    c.code,
                    c.discount_type,
                    c.discount_value,
                    c.min_order_value,
                    c.max_discount,
                    c.end_date
                FROM coupons c
                WHERE c.is_active = true

                AND (c.usage_limit IS NULL OR c.used_count < c.usage_limit)

                AND (c.start_date IS NULL OR c.start_date <= :now)

                AND (c.end_date IS NULL OR c.end_date >= :now)

                -- Exclude coupons already used by this customer
                AND NOT EXISTS (
                    SELECT 1
                    FROM coupon_usage cu
                    WHERE cu.coupon_code = c.code
                    AND cu.customer_id = :customer_id
                )
            """)
        
        result = await db.execute(query, {
            "now": now,
            "customer_id": customer_id
        })
        rows = result.fetchall()

        public_coupons = []
        for row in rows:
            # Create a nice description for the UI to display
            if row.discount_type == "flat":
                desc = f"Flat ₹{row.discount_value} OFF on orders above ₹{row.min_order_value}"
            else:
                desc = f"Get {row.discount_value}% OFF"
                if row.max_discount:
                    desc += f" up to ₹{row.max_discount}"
                desc += f" on orders above ₹{row.min_order_value}"

            public_coupons.append({
                "code": row.code,
                "description": desc,
                "min_order_value": row.min_order_value,
                "expires_at": row.end_date.isoformat() if row.end_date else None
            })
            
        print(public_coupons)

        return {
            "status": "success",
            "data": public_coupons
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch active coupons")