from fastapi import APIRouter, Depends, HTTPException,UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from schemas import *
from services.upload_s3 import upload_product_images_to_s3, delete_image_from_s3
import json
from pydantic import TypeAdapter
import asyncio

# (Your existing router and POST endpoint are up here...)

router = APIRouter(prefix="/products", tags=["products"])

@router.get("/list")
async def get_all_products(
    # --- NEW: Query Parameters ---
    limit: Optional[int] = Query(None, description="Maximum number of products to return"),
    offset: int = Query(0, description="Number of products to skip"),
    db: AsyncSession = Depends(get_db)
):
    try:
        # 1. Base Query
        query_string = """
            SELECT 
                product_id, product_name, image_urls, prices, info, reviews, created_at,
                category, display_index, pricing_type
            FROM products 
            ORDER BY display_index ASC, created_at DESC
        """
        
        # 2. Dynamically add LIMIT and OFFSET based on what the frontend asks for
        params = {"offset": offset}
        
        if limit is not None:
            query_string += " LIMIT :limit"
            params["limit"] = limit
            
        query_string += " OFFSET :offset;"

        # 3. Execute the query
        query = text(query_string)
        result = await db.execute(query, params)
        rows = result.fetchall()

        # 4. Format the data
        products_list = []
        for row in rows:
            products_list.append({
                "product_id": row.product_id, 
                "product_name": row.product_name,
                "category": row.category,
                "display_index": row.display_index,
                "pricing_type": row.pricing_type,
                "image_urls": row.image_urls,
                "prices": row.prices,
                "info": row.info,
                "reviews": row.reviews,
                "created_at": row.created_at.isoformat() if row.created_at else None
            })

        return {
            "status": "success",
            "returned_count": len(products_list),
            "data": products_list
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    


@router.put("/update/{product_id}")
async def update_product(
    product_id: str, 
    product_name: Optional[str] = Form(None),
    prices: Optional[str] = Form(None), 
    info: Optional[str] = Form(None),   
    reviews: Optional[str] = Form(None), 
    
    # NEW: A JSON string of URLs the admin wants to KEEP. 
    # Example: '["https://d3a6tvcqrtqof5.cloudfront.net/products/product_1/image1.jpg"]'
    images_to_keep: Optional[str] = Form(None), 
    category: Optional[str] = Form(None),
    display_index: Optional[int] = Form(None),
    pricing_type: Optional[str] = Form(None),
    
    new_images: list[UploadFile] = File(default=[]), 
    db: AsyncSession = Depends(get_db)
):
    try:
        print(f"Updating: {product_id}")
        
        # --- STEP 1: FETCH EXISTING PRODUCT ---
        fetch_query = text("""
            SELECT product_name, image_urls, prices, info, reviews, 
                   category, display_index, pricing_type 
            FROM products 
            WHERE product_id = :id
        """)
        result = await db.execute(fetch_query, {"id": product_id})
        existing_product = result.fetchone()

        if not existing_product:
            raise HTTPException(status_code=404, detail="Product not found")

        # --- STEP 2: PREPARE BASIC DATA ---
        final_name = product_name if product_name else existing_product.product_name
        final_prices = existing_product.prices
        final_info = existing_product.info
        final_reviews = existing_product.reviews
        final_images = list(existing_product.image_urls)
        final_category = category if category is not None else existing_product.category
        final_display_index = display_index if display_index is not None else existing_product.display_index
        final_pricing_type = pricing_type if pricing_type is not None else existing_product.pricing_type

        # --- STEP 3: VALIDATE NEW JSON DATA ---
        if prices:
            validated_prices = PriceSchema.model_validate_json(prices)
            final_prices = validated_prices.model_dump(by_alias=True)
            
        if info:
            validated_info = ProductInfoSchema.model_validate_json(info)
            final_info = validated_info.model_dump()
            
        if reviews:
            reviews_adapter = TypeAdapter(list[ReviewSchema])
            validated_reviews = reviews_adapter.validate_json(reviews)
            final_reviews = [r.model_dump() for r in validated_reviews]

        # --- STEP 4: HANDLE IMAGE DELETIONS (NEW LOGIC) ---
        if images_to_keep is not None:
            # Parse the list of URLs the admin sent
            kept_urls = json.loads(images_to_keep)
            
            # Find images that are in the database but NOT in the kept_urls list
            # images_to_delete = [url for url in final_images if url not in kept_urls]
            
            # # Delete those missing images from AWS S3
            # for url in images_to_delete:
            #     delete_image_from_s3(url)
                
            # Update our final list so it only has the images we kept
            final_images = kept_urls

        # --- STEP 5: UPLOAD NEW IMAGES TO S3 ---
        # for img in new_images:
        #     if img.filename: 
        #         contents = await img.read()
        #         url = upload_product_images_to_s3(contents, img.filename, product_id)
        #         final_images.append(url) 

        if new_images:
            print(f"⏳ [STATUS] Updating product {product_id} with {len(new_images)} new images...")
            
            # 1. Prepare the tasks (don't execute them yet)
            tasks = []
            for img in new_images:
                if img.filename:
                    # We still await the local read because it's fast
                    contents = await img.read() 
                    
                    # Add the upload task to our list (calling the async version of the function)
                    tasks.append(upload_product_images_to_s3(contents, img.filename, product_id))

            # 2. Fire all uploads SIMULTANEOUSLY
            # This will now take ~2 seconds total, regardless of whether there is 1 image or 10.
            uploaded_urls = await asyncio.gather(*tasks)
            
            # 3. Add the new URLs to your final list
            final_images.extend(uploaded_urls)
            
            print(f"✅ [STATUS] Parallel upload complete for {product_id}")

        # --- STEP 6: SAVE UPDATES TO DATABASE ---
        update_query = text("""
            UPDATE products 
            SET product_name = :name, 
                prices = :prices, 
                info = :info, 
                reviews = :reviews,
                image_urls = :images,
                category = :category,
                display_index = :index,
                pricing_type = :ptype
            WHERE product_id = :id
        """)

        await db.execute(update_query, {
            "name": final_name,
            "prices": json.dumps(final_prices),
            "info": json.dumps(final_info),
            "reviews": json.dumps(final_reviews),
            "images": json.dumps(final_images),
            "category": final_category,
            "index": final_display_index,
            "ptype": final_pricing_type,
            "id": product_id
        })

        await db.commit()

        return {
            "status": "success",
            "message": f"{product_id} updated successfully",
            "updated_data": {
                "product_name": final_name,
                "image_urls": final_images
            }
        }

    except Exception as e:
        await db.rollback()
        import traceback
        print("\n" + "="*50)
        print("🚨 CRASH REPORT 🚨")
        traceback.print_exc()
        print("="*50 + "\n")
        raise HTTPException(status_code=500, detail=f"Error updating product: {str(e)}")