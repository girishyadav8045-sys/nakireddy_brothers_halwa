from dotenv import load_dotenv
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from schemas import CreatePaymentOrderRequest, VerifyPaymentRequest
import razorpay
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone

router = APIRouter(prefix="/payments", tags=["Payments"])

BASE_DIR = Path(__file__).resolve().parent.parent
env_path = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=env_path)

Razor_Key = os.getenv("Razor_API_Key")
Razor_Key_Secre = os.getenv("Razor_Key_Secret")

print(Razor_Key)
print(Razor_Key_Secre)

client = razorpay.Client(auth=(Razor_Key, Razor_Key_Secre))


# @router.post("/create-order")
# async def create_order(req: CreatePaymentOrderRequest, db: AsyncSession = Depends(get_db)):
#     try:
#         # 1. Calculate the exact total from the database (Re-use your cart logic!)
#         # DO NOT let the frontend tell you the price. Calculate it here.
#         query = text("""
#             SELECT c.weight_variant, c.quantity, p.prices
#             FROM cart_items c
#             JOIN products p ON c.product_id = p.product_id
#             WHERE c.user_identifier = :user_id
#         """)
#         result = await db.execute(query, {"user_id": req.customer_id})
#         rows = result.fetchall()

#         # print(rows)

#         if not rows:
#             raise HTTPException(status_code=400, detail="Cart is empty")

#         subtotal = 0.0
#         for row in rows:
#             prices_dict = row.prices if isinstance(row.prices, dict) else json.loads(row.prices)
#             item_price = float(prices_dict.get(row.weight_variant, 0))
#             subtotal += (item_price * row.quantity)

#         # gst = round(subtotal * 0.05, 2)
#         # shipping = 50.0 if subtotal < 999 else 0.0
#         # grand_total = subtotal + gst + shipping
#         grand_total = subtotal

#         # 2. Razorpay expects the amount in PAISE (multiply INR by 100)
#         amount_in_paise = int(grand_total * 100)

#         # 3. Create the order in Razorpay
#         order_data = {
#             "amount": amount_in_paise,
#             "currency": "INR",
#             "receipt": f"receipt_{req.customer_id[:10]}", # Just a tracking string
#             "payment_capture": 1 # Auto-capture the payment
#         }
        
#         razorpay_order = client.order.create(data=order_data)

#         # 4. Return the Razorpay Order ID to the frontend
#         return {
#             "status": "success",
#             "razorpay_order_id": razorpay_order['id'],
#             "amount": grand_total,
#             "currency": "INR",
#             "key_id": Razor_Key # Frontend needs this to open the popup
#         }

#     except Exception as e:
#         import traceback
#         print("\n" + "="*50)
#         print("🚨 PAYMENT CRASH REPORT 🚨")
#         traceback.print_exc() 
#         print("="*50 + "\n")
#         raise HTTPException(status_code=500, detail=str(e))

@router.post("/create-order")
async def create_order(req: CreatePaymentOrderRequest, db: AsyncSession = Depends(get_db)):
    try:
        # 1. Calculate the raw subtotal from the database
        query = text("""
            SELECT c.weight_variant, c.quantity, p.prices
            FROM cart_items c
            JOIN products p ON c.product_id = p.product_id
            WHERE c.user_identifier = :user_id
        """)
        result = await db.execute(query, {"user_id": req.customer_id})
        rows = result.fetchall()

        if not rows:
            raise HTTPException(status_code=400, detail="Cart is empty")

        subtotal = 0.0
        for row in rows:
            prices_dict = row.prices if isinstance(row.prices, dict) else json.loads(row.prices)
            item_price = float(prices_dict.get(row.weight_variant, 0))
            subtotal += (item_price * row.quantity)

        grand_total = subtotal
        discount_amount = 0.0

        # ==================================================
        # 2. RE-VALIDATE COUPON & CALCULATE DISCOUNT 
        # ==================================================
        if req.coupon_code:
            clean_code = req.coupon_code.strip().upper()
            now = datetime.now(timezone.utc)

            # Fetch coupon
            coupon_query = text("SELECT * FROM coupons WHERE code = :code")
            c_res = await db.execute(coupon_query, {"code": clean_code})
            coupon = c_res.fetchone()

            if not coupon or not coupon.is_active:
                raise HTTPException(status_code=400, detail="Invalid or inactive coupon.")
            if coupon.start_date and now < coupon.start_date:
                raise HTTPException(status_code=400, detail="Coupon not valid yet.")
            if coupon.end_date and now > coupon.end_date:
                raise HTTPException(status_code=400, detail="Coupon expired.")
            if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
                raise HTTPException(status_code=400, detail="Coupon usage limit reached.")
            if subtotal < coupon.min_order_value:
                raise HTTPException(status_code=400, detail=f"Minimum order value is ₹{coupon.min_order_value}.")

            # Ledger Check (One per customer)
            usage_query = text("SELECT id FROM coupon_usage WHERE coupon_code = :code AND customer_id = :cust_id")
            usage_result = await db.execute(usage_query, {"code": clean_code, "cust_id": req.customer_id})
            if usage_result.fetchone():
                raise HTTPException(status_code=400, detail="You have already used this coupon.")

            # Calculate math
            if coupon.discount_type == "flat":
                discount_amount = coupon.discount_value
            elif coupon.discount_type == "percentage":
                calc_discount = subtotal * (coupon.discount_value / 100)
                discount_amount = min(calc_discount, coupon.max_discount) if coupon.max_discount else calc_discount

            discount_amount = min(discount_amount, subtotal) # Prevent negative total
            grand_total = subtotal - discount_amount


        # ==================================================
        # 3. CREATE RAZORPAY ORDER
        # ==================================================
        amount_in_paise = int(grand_total * 100)

        order_data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": f"receipt_{req.customer_id[:10]}",
            "payment_capture": 1,
            # MAGIC TRICK: We store the coupon in Razorpay's 'notes' so we remember it later!
            "notes": {
                "coupon_code": req.coupon_code.strip().upper() if req.coupon_code else ""
            }
        }
        
        razorpay_order = client.order.create(data=order_data)

        return {
            "status": "success",
            "razorpay_order_id": razorpay_order['id'],
            "subtotal": subtotal,
            "discount": discount_amount,
            "final_amount": grand_total,
            "currency": "INR",
            "key_id": Razor_Key 
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print("\n🚨 ORDER CREATION CRASH 🚨")
        traceback.print_exc() 
        raise HTTPException(status_code=500, detail=str(e))
    
    



# @router.post("/verify")
# async def verify_payment(req: VerifyPaymentRequest, db: AsyncSession = Depends(get_db)):
#     try:
#         # --- 1. VERIFY THE CRYPTOGRAPHIC SIGNATURE ---
#         # If a hacker tries to fake this, it will immediately throw an error and stop.
#         client.utility.verify_payment_signature({
#             'razorpay_order_id': req.razorpay_order_id,
#             'razorpay_payment_id': req.razorpay_payment_id,
#             'razorpay_signature': req.razorpay_signature
#         })

#         # --- 2. FETCH THE SHIPPING ADDRESS ---
#         # Look inside the customer's JSON address array to find the specific one they chose
#         addr_query = text("SELECT address FROM customers WHERE customer_id = :id")
#         addr_result = await db.execute(addr_query, {"id": req.customer_id})
#         customer = addr_result.fetchone()

#         if not customer or not customer.address:
#             raise HTTPException(status_code=400, detail="Customer or addresses not found")

#         # Find the exact address using Python list comprehension
#         selected_address = next((a for a in customer.address if a.get("address_id") == req.address_id), None)
        
#         if not selected_address:
#             raise HTTPException(status_code=400, detail="Invalid shipping address selected")

#         # --- 3. FETCH THE CART ITEMS & CALCULATE FINAL TOTAL ---
#         cart_query = text("""
#             SELECT c.weight_variant, c.quantity, p.product_id, p.product_name, p.prices
#             FROM cart_items c
#             JOIN products p ON c.product_id = p.product_id
#             WHERE c.user_identifier = :user_id
#         """)
#         cart_result = await db.execute(cart_query, {"user_id": req.customer_id})
#         rows = cart_result.fetchall()

#         if not rows:
#             raise HTTPException(status_code=400, detail="Cart is empty, cannot verify payment for empty cart.")

#         subtotal = 0.0
#         final_items_snapshot = [] # We save exactly what they bought here

#         for row in rows:
#             prices_dict = row.prices if isinstance(row.prices, dict) else json.loads(row.prices)
#             item_price = float(prices_dict.get(row.weight_variant, 0))
#             item_total = item_price * row.quantity
#             subtotal += item_total
            
#             # Create a receipt line item
#             final_items_snapshot.append({
#                 "product_id": row.product_id,
#                 "product_name": row.product_name,
#                 "weight_variant": row.weight_variant,
#                 "quantity": row.quantity,
#                 "unit_price": item_price,
#                 "total_price": item_total
#             })

#         # Optional: Add GST and Shipping to your subtotal here if you are charging for them!
#         grand_total = subtotal 

#         # --- 4. SAVE THE ORDER TO THE DATABASE ---
#         # Since we use raw SQL, we generate the custom ID manually right here
#         new_order_id = f"order_{uuid.uuid4().hex[:10]}"

#         insert_order_query = text("""
#             INSERT INTO orders (
#                 order_id, customer_id, items, shipping_address, total_amount, 
#                 razorpay_order_id, razorpay_payment_id, status
#             ) 
#             VALUES (
#                 :new_id, :cust_id, :items, :address, :total, 
#                 :rzp_order_id, :rzp_payment_id, 'Paid'
#             )
#         """)

#         await db.execute(insert_order_query, {
#             "new_id": new_order_id, # <-- We pass the generated ID here!
#             "cust_id": req.customer_id,
#             "items": json.dumps(final_items_snapshot),
#             "address": json.dumps(selected_address),
#             "total": grand_total,
#             "rzp_order_id": req.razorpay_order_id,
#             "rzp_payment_id": req.razorpay_payment_id
#         })

#         if used_coupon_code:
#             print(f"🎟️ Locking in coupon usage for: {used_coupon_code}")
            
#             # 1. Add +1 to the total usage count
#             update_coupon_query = text("""
#                 UPDATE coupons 
#                 SET used_count = used_count + 1 
#                 WHERE code = :code
#             """)
#             await db.execute(update_coupon_query, {"code": used_coupon_code})

#             # 2. Add a record to the Ledger so this customer can't use it again
#             insert_ledger_query = text("""
#                 INSERT INTO coupon_usage (coupon_code, customer_id, order_id)
#                 VALUES (:code, :cust_id, :ord_id)
#             """)
#             await db.execute(insert_ledger_query, {
#                 "code": used_coupon_code,
#                 "cust_id": customer_id,
#                 "ord_id": razorpay_order_id
#             })

#         # --- 5. CLEAR THE CUSTOMER'S CART ---
#         clear_cart_query = text("DELETE FROM cart_items WHERE user_identifier = :user_id")
#         await db.execute(clear_cart_query, {"user_id": req.customer_id})

#         # --- 6. COMMIT EVERYTHING ---
#         # We only commit at the very end. If anything fails above, the DB rolls back and stays safe!
#         await db.commit()

#         return {
#             "status": "success",
#             "message": "Payment verified! Order placed successfully."
#         }

#     except razorpay.errors.SignatureVerificationError:
#         await db.rollback()
#         raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")
#     except Exception as e:
#         await db.rollback()
#         import traceback
#         print("\n" + "="*50)
#         print("🚨 VERIFY CRASH REPORT 🚨")
#         traceback.print_exc() 
#         print("="*50 + "\n")
#         raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify")
async def verify_payment(req: VerifyPaymentRequest, db: AsyncSession = Depends(get_db)):
    try:
        # --- 1. VERIFY THE CRYPTOGRAPHIC SIGNATURE ---
        client.utility.verify_payment_signature({
            'razorpay_order_id': req.razorpay_order_id,
            'razorpay_payment_id': req.razorpay_payment_id,
            'razorpay_signature': req.razorpay_signature
        })

        # --- 2. FETCH ORDER DETAILS FROM RAZORPAY ---
        # This is the magic step! We ask Razorpay for the order we just verified.
        # This gives us the exact amount they paid AND the hidden coupon notes.
        rzp_order = client.order.fetch(req.razorpay_order_id)
        
        # Razorpay amounts are in paise. Divide by 100 to get exact Rupees paid.
        grand_total = rzp_order.get('amount', 0) / 100.0 
        
        # Safely extract the coupon code we hid in the notes during create_order
        notes = rzp_order.get('notes', {})
        used_coupon_code = notes.get('coupon_code') if notes else None


        # --- 3. FETCH THE SHIPPING ADDRESS ---
        addr_query = text("SELECT address FROM customers WHERE customer_id = :id")
        addr_result = await db.execute(addr_query, {"id": req.customer_id})
        customer = addr_result.fetchone()

        if not customer or not customer.address:
            raise HTTPException(status_code=400, detail="Customer or addresses not found")

        selected_address = next((a for a in customer.address if a.get("address_id") == req.address_id), None)
        
        if not selected_address:
            raise HTTPException(status_code=400, detail="Invalid shipping address selected")


        # --- 4. FETCH THE CART ITEMS FOR THE RECEIPT ---
        cart_query = text("""
            SELECT c.weight_variant, c.quantity, p.product_id, p.product_name, p.prices
            FROM cart_items c
            JOIN products p ON c.product_id = p.product_id
            WHERE c.user_identifier = :user_id
        """)
        cart_result = await db.execute(cart_query, {"user_id": req.customer_id})
        rows = cart_result.fetchall()

        if not rows:
            raise HTTPException(status_code=400, detail="Cart is empty, cannot verify payment for empty cart.")

        final_items_snapshot = [] 
        for row in rows:
            prices_dict = row.prices if isinstance(row.prices, dict) else json.loads(row.prices)
            item_price = float(prices_dict.get(row.weight_variant, 0))
            
            final_items_snapshot.append({
                "product_id": row.product_id,
                "product_name": row.product_name,
                "weight_variant": row.weight_variant,
                "quantity": row.quantity,
                "unit_price": item_price,
                "total_price": item_price * row.quantity
            })


        # --- 5. SAVE THE ORDER TO THE DATABASE ---
        new_order_id = f"order_{uuid.uuid4().hex[:10]}"

        insert_order_query = text("""
            INSERT INTO orders (
                order_id, customer_id, items, shipping_address, total_amount, 
                razorpay_order_id, razorpay_payment_id, status
            ) 
            VALUES (
                :new_id, :cust_id, :items, :address, :total, 
                :rzp_order_id, :rzp_payment_id, 'Paid'
            )
        """)

        await db.execute(insert_order_query, {
            "new_id": new_order_id, 
            "cust_id": req.customer_id,
            "items": json.dumps(final_items_snapshot),
            "address": json.dumps(selected_address),
            "total": grand_total, # <-- Uses the EXACT amount Razorpay charged
            "rzp_order_id": req.razorpay_order_id,
            "rzp_payment_id": req.razorpay_payment_id
        })


        # --- 6. LOCK IN THE COUPON LOGIC ---
        if used_coupon_code:
            print(f"🎟️ Locking in coupon usage for: {used_coupon_code}")
            
            update_coupon_query = text("""
                UPDATE coupons 
                SET used_count = used_count + 1 
                WHERE code = :code
            """)
            await db.execute(update_coupon_query, {"code": used_coupon_code})

            insert_ledger_query = text("""
                INSERT INTO coupon_usage (coupon_code, customer_id, order_id)
                VALUES (:code, :cust_id, :ord_id)
            """)
            await db.execute(insert_ledger_query, {
                "code": used_coupon_code,
                "cust_id": req.customer_id,        # Fixed variable name
                "ord_id": req.razorpay_order_id    # Fixed variable name
            })


        # --- 7. CLEAR THE CUSTOMER'S CART ---
        clear_cart_query = text("DELETE FROM cart_items WHERE user_identifier = :user_id")
        await db.execute(clear_cart_query, {"user_id": req.customer_id})


        # --- 8. COMMIT EVERYTHING ---
        await db.commit()

        return {
            "status": "success",
            "message": "Payment verified! Order placed successfully.",
            "order_id": new_order_id
        }

    except razorpay.errors.SignatureVerificationError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")
    except Exception as e:
        await db.rollback()
        import traceback
        print("\n" + "="*50)
        print("🚨 VERIFY CRASH REPORT 🚨")
        traceback.print_exc() 
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail=str(e))