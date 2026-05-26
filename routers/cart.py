from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
import json
from models import *
from datetime import datetime, timezone

# Import the schemas we just made
from schemas import CartAddRequest, CartMergeRequest, ValidateCouponRequest

router = APIRouter(prefix="/cart", tags=["Cart"])

# ==========================================
# 1. ADD TO CART (Or Update Quantity if exists)
# ==========================================
@router.post("/add")
async def add_to_cart(req: CartAddRequest, db: AsyncSession = Depends(get_db)):
    try:
        # Check if this exact item (same product & same weight) is already in the cart
        check_query = text("""
            SELECT id, quantity FROM cart_items 
            WHERE user_identifier = :user_id 
              AND product_id = :prod_id 
              AND weight_variant = :weight
        """)
        result = await db.execute(check_query, {
            "user_id": req.user_identifier,
            "prod_id": req.product_id,
            "weight": req.weight_variant
        })
        existing_item = result.fetchone()

        print(req.product_id)

        if existing_item:
            # If it exists, just add to the existing quantity
            update_query = text("""
                UPDATE cart_items SET quantity = quantity + :qty
                WHERE id = :item_id
            """)
            await db.execute(update_query, {"qty": req.quantity, "item_id": existing_item.id})
        else:
            # If it's new, insert a new row
            insert_query = text("""
                INSERT INTO cart_items (user_identifier, product_id, weight_variant, quantity)
                VALUES (:user_id, :prod_id, :weight, :qty)
            """)
            await db.execute(insert_query, {
                "user_id": req.user_identifier,
                "prod_id": req.product_id,
                "weight": req.weight_variant,
                "qty": req.quantity
            })

        await db.commit()
        return {"status": "success", "message": "Item added to cart"}
    except Exception as e:
        await db.rollback()
        import traceback
        print("\n" + "="*50)
        print("🚨 CRASH REPORT 🚨")
        traceback.print_exc() 
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 2. GET CART DETAILS & MATH (For the UI)
# ==========================================
@router.get("/{user_identifier}")
async def get_cart(user_identifier: str, db: AsyncSession = Depends(get_db)):
    try:
        # Join the cart table with the products table to get prices and names
        query = text("""
            SELECT c.id as cart_item_id, c.weight_variant, c.quantity,
                   p.product_id, p.product_name, p.prices, p.image_urls
            FROM cart_items c
            JOIN products p ON c.product_id = p.product_id
            WHERE c.user_identifier = :user_id
            ORDER BY c.created_at ASC
        """)
        
        result = await db.execute(query, {"user_id": user_identifier})
        rows = result.fetchall()

        cart_items = []
        subtotal = 0.0

        for row in rows:
            # 1. Parse the prices JSON (e.g., {"kg": 120, "250g": 35})
            # asyncpg usually returns JSONB as a dict, but if it's a string, we load it
            prices_dict = row.prices if isinstance(row.prices, dict) else json.loads(row.prices)
            
            # 2. Find the exact price for the weight the user chose
            item_price = float(prices_dict.get(row.weight_variant, 0))
            item_total = item_price * row.quantity
            
            subtotal += item_total

            cart_items.append({
                "cart_item_id": row.cart_item_id,
                "product_id": row.product_id,
                "product_name": row.product_name,
                "weight_variant": row.weight_variant,
                "quantity": row.quantity,
                "unit_price": item_price,
                "item_total": item_total,
                # Grab just the first image for the cart thumbnail
                "thumbnail": row.image_urls[0] if row.image_urls else None 
            })

        return {
            "status": "success",
            "summary": {
                "total_items": sum(item["quantity"] for item in cart_items),
                "subtotal": subtotal,
            
            },
            "items": cart_items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 3. UPDATE ITEM QUANTITY (+ / - buttons)
# ==========================================
@router.put("/update/{cart_item_id}")
async def update_quantity(cart_item_id: int, quantity: int, db: AsyncSession = Depends(get_db)):
    print(quantity)
    try:
        if quantity <= 0:
            # If they hit minus down to 0, just delete the item
            return await remove_item(cart_item_id, db)
            
        query = text("UPDATE cart_items SET quantity = :qty WHERE id = :id")
        await db.execute(query, {"qty": quantity, "id": cart_item_id})
        await db.commit()
        return {"status": "success", "message": "Quantity updated"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 4. REMOVE SINGLE ITEM (Trash Can icon)
# ==========================================
@router.delete("/remove/{cart_item_id}")
async def remove_item(cart_item_id: int, db: AsyncSession = Depends(get_db)):
    try:
        query = text("DELETE FROM cart_items WHERE id = :id")
        await db.execute(query, {"id": cart_item_id})
        await db.commit()
        return {"status": "success", "message": "Item removed from cart"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 5. CLEAR ENTIRE CART ("Clear Cart" text)
# ==========================================
@router.delete("/clear/{user_identifier}")
async def clear_cart(user_identifier: str, db: AsyncSession = Depends(get_db)):
    try:
        query = text("DELETE FROM cart_items WHERE user_identifier = :user_id")
        await db.execute(query, {"user_id": user_identifier})
        await db.commit()
        return {"status": "success", "message": "Cart cleared"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 6. MERGE GUEST CART TO CUSTOMER
# ==========================================
@router.put("/merge")
async def merge_cart(req: CartMergeRequest, db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            UPDATE cart_items 
            SET user_identifier = :customer_id 
            WHERE user_identifier = :guest_id
        """)
        result = await db.execute(query, {
            "customer_id": req.customer_id,
            "guest_id": req.guest_id
        })
        await db.commit()
        return {
            "status": "success", 
            "items_transferred": result.rowcount
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    



    


# ==========================================
# 2. USER: VALIDATE COUPON (The 5-Step Gauntlet)
# ==========================================
@router.post("/validate_coupon")
async def validate_coupon(req: ValidateCouponRequest, db: AsyncSession = Depends(get_db)):
    try:
        clean_code = req.coupon_code.strip().upper()
        now = datetime.now(timezone.utc)

        # --- GATE 1 & 2: Fetch Coupon and Check Dates/Active Status ---
        coupon_query = text("SELECT * FROM coupons WHERE code = :code")
        result = await db.execute(coupon_query, {"code": clean_code})
        coupon = result.fetchone()

        print(coupon)

        if not coupon:
            print("FAILED: Coupon not found")
            raise HTTPException(status_code=404, detail="Invalid coupon code.")
            
        if not coupon.is_active:
            print("FAILED: Coupon inactive")
            raise HTTPException(status_code=400, detail="This coupon is no longer active.")
        
        # Date checks (if dates are set)
        if coupon.start_date and now < coupon.start_date:
            print("FAILED: Coupon not started yet")
            raise HTTPException(status_code=400, detail="This coupon is not valid yet.")
        if coupon.end_date and now > coupon.end_date:
            print("FAILED: Coupon expired")
            raise HTTPException(status_code=400, detail="This coupon has expired.")

        # --- GATE 3: Global Usage Limit ---
        if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
            print("FAILED: Usage limit reached")
            raise HTTPException(status_code=400, detail="This coupon has reached its usage limit.")

        # --- GATE 4: One-Per-Customer Check (The Ledger) ---
        usage_query = text("""
            SELECT id FROM coupon_usage 
            WHERE coupon_code = :code AND customer_id = :cust_id
        """)
        usage_result = await db.execute(usage_query, {"code": clean_code, "cust_id": req.customer_id})
        if usage_result.fetchone():
            print("FAILED: Customer already used coupon")
            raise HTTPException(status_code=400, detail="You have already used this coupon.")

        # --- GATE 5: Cart Value Check (Calculate from DB!) ---
        cart_query = text("""
            SELECT c.weight_variant, c.quantity, p.prices
            FROM cart_items c
            JOIN products p ON c.product_id = p.product_id
            WHERE c.user_identifier = :user_id
        """)
        cart_result = await db.execute(cart_query, {"user_id": req.customer_id})
        rows = cart_result.fetchall()

        if not rows:
            print("FAILED: Cart empty")
            raise HTTPException(status_code=400, detail="Your cart is empty.")

        subtotal = 0.0
        for row in rows:
            prices_dict = row.prices if isinstance(row.prices, dict) else json.loads(row.prices)
            item_price = float(prices_dict.get(row.weight_variant, 0))
            subtotal += (item_price * row.quantity)

        if subtotal < coupon.min_order_value:
            print("FAILED: Minimum order value not reached")
            raise HTTPException(status_code=400, detail=f"Add ₹{coupon.min_order_value - subtotal} more to use this coupon.")

        # --- FINAL STEP: Calculate the Discount ---
        discount_amount = 0.0
        
        if coupon.discount_type == "flat":
            discount_amount = coupon.discount_value
        elif coupon.discount_type == "percentage":
            # Example: 10% off -> subtotal * (10 / 100)
            calculated_discount = subtotal * (coupon.discount_value / 100)
            
            # Apply the cap if max_discount exists
            if coupon.max_discount is not None and calculated_discount > coupon.max_discount:
                discount_amount = coupon.max_discount
            else:
                discount_amount = calculated_discount

        # Prevent the discount from making the cart negative
        discount_amount = min(discount_amount, subtotal)
        final_total = subtotal - discount_amount

        return {
            "status": "success",
            "message": "Coupon applied successfully!",
            "data": {
                "subtotal": round(subtotal, 2),
                "discount_amount": round(discount_amount, 2),
                "final_total": round(final_total, 2)
            }
        }

    except HTTPException:
        raise # Pass through our custom error messages cleanly
    except Exception as e:
        import traceback
        print("\n🚨 COUPON VALIDATE CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error validating coupon")
