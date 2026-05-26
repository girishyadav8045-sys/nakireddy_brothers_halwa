import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from schemas import CustomerCreate, UniversalLogin
import json
from schemas import AddressSchema

router = APIRouter(prefix="/customers", tags=["customers"])

@router.post("/add-customer")
async def save_customer(customer: CustomerCreate, db: AsyncSession = Depends(get_db)):
    # 1. Prepare the Raw SQL Query
    # We use :variable_name for parameterization
    sql_query = text("""
        INSERT INTO customers (customer_id, first_name, last_name, email, phone_number)
        VALUES (:cid, :fn, :ln, :em, :ph)
        RETURNING customer_id;
    """)

    # 2. Generate a fresh UUID
    new_id = uuid.uuid4()

    try:
        # 3. Execute the query
        # We pass the parameters as a dictionary to avoid SQL injection
        result = await db.execute(
            sql_query, 
            {
                "cid": new_id,
                "fn": customer.first_name,
                "ln": customer.last_name,
                "em": customer.email,
                "ph": customer.phone_number
            }
        )
        
        # 4. Commit the transaction
        await db.commit()
        
        return {
            "message": "Customer saved successfully",
            "customer_id": new_id
        }

    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print("🚨 addcustomer crash report  🚨")
        traceback.print_exc() 
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail="customer details already present")
        
        # await db.rollback()
        # error_msg = str(e).lower()

        # # Check if it's a unique constraint violation first
        # if "unique constraint" in error_msg:
        #     if "email" in error_msg:
        #         raise HTTPException(
        #             status_code=400, 
        #             detail="This email address is already registered."
        #         )
            
        #     if "phone" in error_msg or "uq_customer_phone" in error_msg:
        #         raise HTTPException(
        #             status_code=400, 
        #             detail="This phone number is already registered."
        #         )

        # # Fallback for any other database errors
        # raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    


@router.post("/login")
async def login_flexible(login_data: UniversalLogin, db: AsyncSession = Depends(get_db)):
    # 1. Raw SQL query using OR logic
    # We use the same parameter :id for both checks
    query = text("""
        SELECT customer_id, first_name, last_name, email, phone_number, address
        FROM customers 
        WHERE email = :id OR phone_number = :id
        LIMIT 1;
    """)
    
    # 2. Execute
    result = await db.execute(query, {"id": login_data.identifier})
    customer = result.fetchone()

    # 3. Validation
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found. Please check your email/phone or sign up."
        )

    # 4. Success Response
    return {
        "message": "Login successful",
        "customer_details": {
            "first_name": customer.first_name,
            "last_name": customer.last_name,
            "email": customer.email,
            "phone_number": customer.phone_number,
            "customer_id": customer.customer_id
        }
    }




@router.post("/{customer_id}/address")
async def add_customer_address(
    customer_id: str,
    address_data: AddressSchema,
    db: AsyncSession = Depends(get_db)
):
    try:
        # --- STEP 1: Fetch the current customer ---
        query = text("SELECT address FROM customers WHERE customer_id = :id")
        result = await db.execute(query, {"id": customer_id})
        customer = result.fetchone()

        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        # --- STEP 2: Get current addresses or start a new list ---
        # asyncpg automatically parses the JSONB into a Python list
        current_addresses = customer.address if customer.address else []

        # --- STEP 3: Format the new address ---
        # Convert the Pydantic schema to a dictionary
        new_address = address_data.model_dump()
        
        # PRO-TIP: Give this specific address a unique ID so you can edit/delete it later!
        new_address["address_id"] = f"adrs_{uuid.uuid4().hex}"

        # --- STEP 4: Append to the list ---
        current_addresses.append(new_address)

        # --- STEP 5: Save the updated list back to the database ---
        update_query = text("""
            UPDATE customers 
            SET address = :new_addresses 
            WHERE customer_id = :id
        """)
        
        await db.execute(update_query, {
            # We dump it back to a string so PostgreSQL can save it as JSONB
            "new_addresses": json.dumps(current_addresses), 
            "id": customer_id
        })
        
        await db.commit()

        return {
            "status": "success",
            "message": "Address saved successfully!",
            "address_id": new_address["address_id"],
            "addresses": current_addresses # Returns the newly updated list
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/{customer_id}/addresses")
async def get_customer_addresses(
    customer_id: str,
    db: AsyncSession = Depends(get_db)
):
    try:
        # Just grab the address column from the database
        query = text("SELECT address FROM customers WHERE customer_id = :id")
        result = await db.execute(query, {"id": customer_id})
        customer = result.fetchone()

        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        # If it's None, just return an empty list
        addresses = customer.address if customer.address else []

        return {
            "status": "success",
            "total_saved": len(addresses),
            "data": addresses
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    




@router.get("/history/{customer_id}")
async def get_order_history(customer_id: str, db: AsyncSession = Depends(get_db)):
    try:
        # --- 1. Fetch all orders and LEFT JOIN with coupon ledger ---
        query = text("""
            SELECT 
                o.order_id, 
                o.items, 
                o.shipping_address, 
                o.total_amount, 
                o.status, 
                o.created_at,
                cu.coupon_code
            FROM orders o
            LEFT JOIN coupon_usage cu ON cu.order_id = o.razorpay_order_id
            WHERE o.customer_id = :cust_id 
            ORDER BY o.created_at DESC
        """)
        
        result = await db.execute(query, {"cust_id": customer_id})
        rows = result.fetchall()

        if not rows:
            return {
                "status": "success",
                "total_orders": 0,
                "data": []
            }

        # --- 2. Extract all unique product_ids ---
        product_ids = set()
        parsed_rows = [] 
        
        for row in rows:
            items = row.items if isinstance(row.items, list) else json.loads(row.items)
            address = row.shipping_address if isinstance(row.shipping_address, dict) else json.loads(row.shipping_address)
            
            for item in items:
                if "product_id" in item:
                    product_ids.add(str(item["product_id"]).strip())
                    
            parsed_rows.append((row, items, address))

        # --- 3. Fetch latest Names and Images in ONE query ---
        product_details_map = {}
        if product_ids:
            placeholders = ', '.join([f"'{pid}'" for pid in product_ids])
            details_query = text(f"""
                SELECT product_id, product_name, image_urls 
                FROM products 
                WHERE product_id IN ({placeholders})
            """)
            
            details_result = await db.execute(details_query)
            details_rows = details_result.fetchall()
            
            for d_row in details_rows:
                urls = d_row.image_urls if isinstance(d_row.image_urls, list) else json.loads(d_row.image_urls)
                product_details_map[str(d_row.product_id)] = {
                    "name": d_row.product_name,
                    "image": urls[0] if urls else None
                }

        # --- 4. Build the final response ---
        orders_list = []
        for row, items, address in parsed_rows:
            
            for item in items:
                p_id = str(item.get("product_id"))
                if p_id in product_details_map:
                    item["product_name"] = product_details_map[p_id]["name"]
                    item["image"] = product_details_map[p_id]["image"]
                else:
                    item["image"] = None 

            orders_list.append({
                "order_id": row.order_id, 
                "total_amount": row.total_amount,
                "status": row.status,
                "created_at": row.created_at.isoformat(), 
                
                # --- NEW FIELD ---
                # Returns the code (e.g., "WELCOME10") or None if no coupon was used
                "coupon_applied": row.coupon_code, 
                
                "shipping_address": address,
                "items": items
            })

        return {
            "status": "success",
            "total_orders": len(orders_list),
            "data": orders_list
        }

    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print("🚨 ORDER HISTORY CRASH REPORT 🚨")
        traceback.print_exc() 
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail="Failed to fetch order history.")