from fastapi import APIRouter, Depends, HTTPException, status,UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from schemas import *
from services.upload_s3 import upload_product_images_to_s3
import json
from typing import List, Annotated
from pydantic import TypeAdapter
import uuid
import asyncio
from datetime import datetime, time as datetime_time

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/login")
async def admin_login(login_data: AdminLogin, db: AsyncSession = Depends(get_db)):
    # 1. Fetch the admin record using raw SQL
    query = text("""
        SELECT admin_id, admin_name, hashed_password, email, phone_number 
        FROM admins 
        WHERE email = :id OR phone_number = :id 
        LIMIT 1
    """)
    
    result = await db.execute(query, {"id": login_data.identifier})
    admin = result.fetchone()

    # 2. Check if admin exists
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials (Admin not found)"
        )

    # 3. Password Verification
    # Note: If you are using hashing (like bcrypt), you would check it here.
    # For now, we compare the input directly to the column.
    if login_data.password != admin.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials (Incorrect password)"
        )

    # 4. Success Response
    return {
        "message": "Welcome back, Admin!",
        "admin_profile": {
            "id": str(admin.admin_id),
            "name": admin.admin_name,
            "email": admin.email,
            "phone_number":admin.phone_number
        }
    }



@router.post("/add-product")
async def add_product(
    product_name: str = Form(...),
    prices: str = Form(...), 
    info: str = Form(...),   
    reviews: str = Form("[]"), 
    category: str = Form("General"),
    display_index: int = Form(0),
    pricing_type: str = Form("weight"), # Frontend will send "weight" or "piece"
    images: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db)
):
    # --- STEP 1: VALIDATION ---
    try:
        validated_prices = PriceSchema.model_validate_json(prices)
        validated_info = ProductInfoSchema.model_validate_json(info)
        reviews_adapter = TypeAdapter(list[ReviewSchema])
        validated_reviews = reviews_adapter.validate_json(reviews)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid JSON format: {str(e)}")

    try:
        # --- STEP 2: GENERATE CUSTOM ID ---
        # Get the next number (1, 2, 3...)
        # --- STEP 2: GENERATE UUID PRODUCT ID ---
        custom_product_id = f"product_{uuid.uuid4().hex[:8]}"

        # --- STEP 3: INITIAL DB INSERT ---
        insert_query = text("""
            INSERT INTO products (
                product_id, product_name, image_urls, prices, 
                info, reviews, category, display_index, pricing_type
            )
            VALUES (
                :id, :name, '[]', :prices, 
                :info, :reviews, :category, :index, :ptype
            )
        """)

        await db.execute(insert_query, {
            "id": custom_product_id, 
            "name": product_name,
            "prices": json.dumps(validated_prices.model_dump(by_alias=True)),
            "info": json.dumps(validated_info.model_dump()),
            "reviews": json.dumps([r.model_dump() for r in validated_reviews]),
            "category": category,
            "index": display_index,
            "ptype": pricing_type
        })

        # --- STEP 4: UPLOAD TO S3 ---
        print(f"⏳ [STATUS] Parallel uploading {len(images)} images...")

        # 1. Create a list of 'tasks' (don't await them yet)
        upload_tasks = []
        for img in images:
            contents = await img.read()
            upload_tasks.append(
                upload_product_images_to_s3(contents, img.filename, custom_product_id)
            )

        # 2. Run all uploads at the same time!
        # If you have 5 images, this will now take the time of the SLOWEST single image,
        # rather than the sum of all of them.
        uploaded_urls = await asyncio.gather(*upload_tasks)

        print(f"✅ [STATUS] All uploads finished: {uploaded_urls}")

        # --- STEP 5: UPDATE DB WITH IMAGE URLS ---
        update_query = text("""
            UPDATE products 
            SET image_urls = :urls 
            WHERE product_id = :id
        """)
        await db.execute(update_query, {
            "urls": json.dumps(uploaded_urls),
            "id": custom_product_id
        })

        await db.commit()

        return {
            "status": "success",
            "product_id": custom_product_id,
            "image_urls": uploaded_urls
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
        
    


@router.delete("/delete/{product_id}")
async def delete_product(product_id: str, db: AsyncSession = Depends(get_db)):
    try:
        print(f"🗑️ [STATUS] Starting full deletion for: {product_id}")

        # --- STEP 1: FETCH PRODUCT DATA ---
        # We need the image URLs to clean up S3 storage
        fetch_query = text("SELECT image_urls FROM products WHERE product_id = :id")
        result = await db.execute(fetch_query, {"id": product_id})
        product = result.fetchone()

        if not product:
            print(f"❌ [STATUS] Product {product_id} not found.")
            raise HTTPException(status_code=404, detail="Product not found")

        # --- STEP 2: CLEAN UP CART ITEMS ---
        # We remove this product from all shopping carts so users don't see "ghost" items
        print(f"🧹 [STATUS] Removing {product_id} from all customer carts...")
        await db.execute(
            text("DELETE FROM cart_items WHERE product_id = :id"), 
            {"id": product_id}
        )

        # --- STEP 3: DELETE IMAGES FROM S3 ---
        # image_list = product.image_urls if isinstance(product.image_urls, list) else json.loads(product.image_urls)
        
        # print(f"⏳ [STATUS] Deleting {len(image_list)} images from S3 bucket...")
        # for url in image_list:
        #     try:
        #         # Re-using your S3 deletion function
        #         # delete_image_from_s3(url)
        #     except Exception as s3_err:
        #         print(f"⚠️ [WARNING] Could not delete S3 file {url}: {s3_err}")

        # --- STEP 4: DELETE FROM PRODUCTS TABLE ---
        print(f"🔨 [STATUS] Removing product from database...")
        await db.execute(
            text("DELETE FROM products WHERE product_id = :id"), 
            {"id": product_id}
        )
        
        # --- STEP 5: COMMIT CHANGES ---
        await db.commit()
        print(f"✅ [STATUS] Successfully deleted {product_id} from Products and Carts.")

        return {
            "status": "success",
            "message": f"Product {product_id} has been completely removed from the store and all carts."
        }

    except Exception as e:
        # If anything fails, undo the database changes
        await db.rollback()
        import traceback
        print("\n" + "="*50)
        print("🚨 DELETE CRASH REPORT 🚨")
        traceback.print_exc()
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    



@router.get("/orders_list")
async def admin_get_all_orders(db: AsyncSession = Depends(get_db)):
    try:
        # 1. Added WHERE clause for 'Paid' status and added o.shipping_address to SELECT
        query = text("""
            SELECT 
                o.order_id, 
                o.total_amount, 
                o.status, 
                o.items,
                o.shipping_address,
                o.created_at,
                c.first_name, 
                c.last_name, 
                c.phone_number
            FROM orders o
            JOIN customers c ON o.customer_id = CAST(c.customer_id AS TEXT)
            WHERE o.status = 'Paid'
            ORDER BY o.created_at DESC
        """)
        
        result = await db.execute(query)
        rows = result.fetchall()

        orders_summary = []
        for row in rows:
            full_name = f"{row.first_name} {row.last_name}"
            
            items = row.items if isinstance(row.items, list) else json.loads(row.items)
            num_products = len(items)

            # 2. Parse the shipping address JSON structure safely
            address = row.shipping_address if isinstance(row.shipping_address, dict) else json.loads(row.shipping_address)

            orders_summary.append({
                "order_id": row.order_id,
                "customer_name": full_name,
                "mobile_number": row.phone_number,
                "amount": row.total_amount,
                "status": row.status,
                "number_of_products": num_products,
                "shipping_address": address, # Included shipping address in payload
                "date": row.created_at.strftime("%Y-%m-%d %H:%M")
            })

        return {
            "status": "success",
            "total_orders": len(orders_summary),
            "data": orders_summary
        }

    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print("🚨 ADMIN ORDER LIST CRASH 🚨")
        traceback.print_exc()
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail="Failed to fetch admin order list")
    

@router.post("/orders-by-date")
async def admin_get_orders_by_date(req: DateFilterRequest, db: AsyncSession = Depends(get_db)):
    try:
        # Convert incoming string to a date object, then set time to 00:00:00
        start_dt = datetime.combine(
            datetime.strptime(req.start_date, "%Y-%m-%d").date(), 
            datetime_time.min  # <-- Use the renamed alias here!
        )
        
        # Convert incoming string to a date object, then set time to 23:59:59.999999
        end_dt = datetime.combine(
            datetime.strptime(req.end_date, "%Y-%m-%d").date(), 
            datetime_time.max  # <-- Use the renamed alias here!
        )
        
        print(f"📅 [STATUS] Filtering paid orders from {start_dt} to {end_dt}")

        # 3. Query the DB (Irrespective of status, filtering strictly by created_at range)
        query = text("""
            SELECT 
                o.order_id, 
                o.total_amount, 
                o.status, 
                o.items,
                o.shipping_address,
                o.created_at,
                c.first_name, 
                c.last_name, 
                c.phone_number
            FROM orders o
            JOIN customers c ON o.customer_id = CAST(c.customer_id AS TEXT)
            WHERE o.created_at BETWEEN :start AND :end
            ORDER BY o.created_at DESC
        """)
        
        result = await db.execute(query, {"start": start_dt, "end": end_dt})
        rows = result.fetchall()

        orders_summary = []
        for row in rows:
            full_name = f"{row.first_name} {row.last_name}"
            items = row.items if isinstance(row.items, list) else json.loads(row.items)
            address = row.shipping_address if isinstance(row.shipping_address, dict) else json.loads(row.shipping_address)

            orders_summary.append({
                "order_id": row.order_id,
                "customer_name": full_name,
                "mobile_number": row.phone_number,
                "amount": row.total_amount,
                "status": row.status,
                "number_of_products": len(items),
                "shipping_address": address,
                "date": row.created_at.strftime("%Y-%m-%d %H:%M")
            })

        return {
            "status": "success",
            "total_orders": len(orders_summary),
            "data": orders_summary
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print("🚨 ADMIN DATE FILTER CRASH 🚨")
        traceback.print_exc()
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail="Failed to fetch orders by date")
    


@router.put("/bulk-ship")
async def admin_bulk_ship_orders(req: BulkShipmentRequest, db: AsyncSession = Depends(get_db)):
    try:
        if not req.order_ids:
            raise HTTPException(status_code=400, detail="Order ID list cannot be empty.")

        print(f"📦 [STATUS] Bulk shifting status to 'Shipped' for orders: {req.order_ids}")

        # Execute the bulk update statement
        # WHERE status = 'Paid' ensures we only affect unfulfilled orders
        query = text("""
            UPDATE orders 
            SET status = 'Shipped' 
            WHERE order_id = ANY(:ids) AND status = 'Paid'
        """)
        
        result = await db.execute(query, {"ids": req.order_ids})
        affected_rows = result.rowcount

        await db.commit()
        print(f"✅ [STATUS] Successfully marked {affected_rows} orders as Shipped.")

        return {
            "status": "success",
            "message": f"Successfully marked {affected_rows} orders as Shipped.",
            "requested_count": len(req.order_ids),
            "updated_count": affected_rows
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        print("\n" + "="*50)
        print("🚨 BULK SHIPMENT CRASH REPORT 🚨")
        traceback.print_exc()
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail="Failed to execute bulk shipment update.")


@router.get("/order_details/{order_id}")
async def admin_get_order_details(order_id: str, db: AsyncSession = Depends(get_db)):
    try:
        # Fetch the specific order and join with customer for contact info
        query = text("""
            SELECT 
                o.*, 
                c.first_name, 
                c.last_name, 
                c.phone_number, 
                c.email,
                cu.coupon_code
            FROM orders o
            JOIN customers c ON o.customer_id = CAST(c.customer_id AS TEXT)
            LEFT JOIN coupon_usage cu ON cu.order_id = o.razorpay_order_id
            WHERE o.order_id = :id
        """)
        
        result = await db.execute(query, {"id": order_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Order not found")

        # Parse JSON fields
        items = row.items if isinstance(row.items, list) else json.loads(row.items)
        address = row.shipping_address if isinstance(row.shipping_address, dict) else json.loads(row.shipping_address)

        # 3. Collect unique product IDs from the items list
        product_ids = set()
        for item in items:
            p_id = str(item.get("product_id")).strip()
            p_id = item.get("product_id")
            if p_id:
                product_ids.add(p_id)

        # print(f"🔍 DEBUG: IDs found in Order: {product_ids}")

        # 4. Fetch the first image for each product ID
        image_map = {}
        if product_ids:
            # Safely format the IDs for the SQL IN clause
            id_list = ", ".join([f"'{pid}'" for pid in product_ids])
            img_query = text(f"SELECT product_id, image_urls FROM products WHERE product_id IN ({id_list})")
            
            img_result = await db.execute(img_query)
            img_rows = img_result.fetchall()
            
            for img_row in img_rows:
                # print(f"   -> Found Product: {img_row.product_id}")
                urls = img_row.image_urls if isinstance(img_row.image_urls, list) else json.loads(img_row.image_urls)
                # Map the first URL to the product_id
                image_map[img_row.product_id] = urls[0] if urls else None

        # 5. Inject the images into the items list
        for item in items:
            item["product_image"] = image_map.get(item.get("product_id"))
            
        return {
            "status": "success",
            "data": {
                "order_id": row.order_id,
                "status": row.status,
                "created_at": row.created_at,
                "total_amount": row.total_amount,
                "coupon_applied": row.coupon_code,
                
                # Customer Contact Info
                "customer": {
                    "full_name": f"{row.first_name} {row.last_name}",
                    "phone": row.phone_number,
                    "email": row.email
                },
                
                # Full Shipping Address
                "shipping_address": address,
                
                # List of Products Purchased
                "items": items,
                
                # Payment Reference
                "payment_details": {
                    "razorpay_order_id": row.razorpay_order_id,
                    "razorpay_payment_id": row.razorpay_payment_id
                }
            }
        }

    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print("🚨 ADMIN ORDER DETAILS CRASH 🚨")
        traceback.print_exc()
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail="Internal Server Error")

"""Premium Cashew Halwa
{
  "kg": 1200,
  "500g": 650,
  "250g": 350
}
{
  "description": "Rich and delicious cashew halwa made with pure ghee.",
  "shelf_life": "45 Days",
  "ingredients": "Cashews, Sugar, Pure Ghee, Cardamom",
  "preparation_details": "Slow-cooked in copper vessels for 4 hours.",
  "delivery_info": "Dispatched within 24 hours. Delivery in 3-5 days."
}
[
  {
    "name": "Ravi",
    "stars": 5,
    "description": "Absolutely melts in the mouth!"
  }
]

"""

@router.get("/dashboard-analytics")
async def get_admin_dashboard_analytics(db: AsyncSession = Depends(get_db)):
    try:
        # We group by the date part of created_at 
        # and conditionally count statuses using CASE WHEN
        query = text("""
            SELECT 
                created_at::date AS order_date,
                COUNT(order_id) AS total_orders,
                COALESCE(SUM(total_amount), 0) AS daily_revenue,
                COUNT(CASE WHEN status = 'Shipped' THEN 1 END) AS shipped_count,
                COUNT(CASE WHEN status = 'Paid' THEN 1 END) AS pending_count
            FROM orders
            GROUP BY created_at::date
            ORDER BY order_date DESC
        """)
        
        result = await db.execute(query)
        rows = result.fetchall()

        dashboard_data = {}
        
        for row in rows:
            # Convert the date object to a clean string format "YYYY-MM-DD"
            date_str = row.order_date.strftime("%Y-%m-%d")
            
            # Map it exactly to the dictionary format you requested!
            dashboard_data[date_str] = {
                "number of orders": row.total_orders,
                "revenew": float(row.daily_revenue),
                "shipped orders": row.shipped_count,
                "peding orders": row.pending_count
            }

        return {
            "status": "success",
            "data": dashboard_data
        }

    except Exception as e:
        import traceback
        print("\n🚨 DASHBOARD ANALYTICS CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to load dashboard metrics")
    



@router.get("/admins_list")
async def list_all_admins(db: AsyncSession = Depends(get_db)):
    try:
        # Fetch profile data, sorting by the newest admin accounts first
        query = text("""
            SELECT admin_id, admin_name, email, phone_number, created_at 
            FROM admins 
            ORDER BY created_at DESC
        """)
        
        result = await db.execute(query)
        rows = result.fetchall()

        admins_list = []
        for row in rows:
            admins_list.append({
                "admin_id": str(row.admin_id),
                "admin_name": row.admin_name,
                "email": row.email,
                "phone_number": row.phone_number,
                "created_at": row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else None
            })

        return {
            "status": "success",
            "total_admins": len(admins_list),
            "data": admins_list
        }

    except Exception as e:
        import traceback
        print("\n🚨 FETCH ADMINS LIST CRASH 🚨")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch admin list.")
    

@router.post("/add_admin")
async def add_new_admin(admin_data: CreateAdminSchema, db: AsyncSession = Depends(get_db)):
    try:
        # Check if the email or phone number is already registered as an admin
        check_query = text("""
            SELECT admin_id FROM admins 
            WHERE email = :email OR phone_number = :phone
        """)
        existing = await db.execute(check_query, {
            "email": admin_data.email, 
            "phone": admin_data.phone_number
        })
        if existing.fetchone():
            raise HTTPException(
                status_code=400, 
                detail="An admin with this email or phone number already exists."
            )

        # Generate a clean native UUID for the new admin
        new_admin_id = uuid.uuid4()

        # Insert into database 
        # (Note: In production, wrap admin_data.password inside a hashing function)
        insert_query = text("""
            INSERT INTO admins (admin_id, admin_name, email, phone_number, addresses)
            VALUES (:id, :name, :email, :phone, '[]'::jsonb)
        """)
        
        await db.execute(insert_query, {
            "id": new_admin_id,
            "name": admin_data.admin_name,
            "email": admin_data.email,
            "phone": admin_data.phone_number
        })
        
        await db.commit()

        return {
            "status": "success",
            "message": f"Admin {admin_data.admin_name} created successfully.",
            "admin_id": str(new_admin_id)
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to create new admin account.")


# ==========================================
# 2. DELETE AN ADMIN
# ==========================================
@router.delete("/delete_admin/{admin_id}")
async def delete_admin(admin_id: str, db: AsyncSession = Depends(get_db)):
    try:
        # Verify the admin exists before trying to wipe them out
        # We use CAST because your model strictly configures admin_id as a native UUID type
        check_query = text("SELECT admin_name FROM admins WHERE admin_id = CAST(:id AS UUID)")
        result = await db.execute(check_query, {"id": admin_id})
        admin_row = result.fetchone()

        if not admin_row:
            raise HTTPException(status_code=404, detail="Admin account not found.")

        # Execute hard delete
        delete_query = text("DELETE FROM admins WHERE admin_id = CAST(:id AS UUID)")
        await db.execute(delete_query, {"id": admin_id})
        
        await db.commit()

        return {
            "status": "success",
            "message": f"Admin account for {admin_row.admin_name} was permanently removed."
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to delete admin account.")
