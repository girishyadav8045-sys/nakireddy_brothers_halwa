from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import json
import uuid
from database import get_db
from services.upload_s3 import upload_category_images_to_s3
import asyncio
from typing import Optional


router = APIRouter(prefix="/categories", tags=["Categories"])

@router.get("/list")
async def get_categories_list(db: AsyncSession = Depends(get_db)):
    try:
        # 1. Grab unique categories from products AND join their metadata
        query = text("""
            SELECT 
                p.category_name,
                c.category_id,
                c.title,
                c.description,
                c.images,
                c.display_index
            FROM (
                SELECT DISTINCT category AS category_name 
                FROM products 
                WHERE category IS NOT NULL
            ) p
            LEFT JOIN category_metadata c ON p.category_name = c.category_name
            ORDER BY c.display_index ASC NULLS LAST, p.category_name ASC;
        """)
        
        result = await db.execute(query)
        rows = result.fetchall()

        categories_list = []
        for row in rows:
            # If the admin hasn't set up metadata yet, handle the nulls gracefully
            images_list = row.images if row.images else []
            if isinstance(images_list, str):
                images_list = json.loads(images_list)

            categories_list.append({
                "category_name": row.category_name, # The actual name from the products table
                "category_id": row.category_id,     # Will be null until admin updates it
                "title": row.title,
                "description": row.description,
                "images": images_list,
                "display_index": row.display_index or 0
            })

        return {
            "status": "success",
            "total_categories": len(categories_list),
            "data": categories_list
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch categories")
    





@router.put("/update/{category_name}")
async def update_category_metadata(
    category_name: str, 
    
    # --- FORM FIELDS ---
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    display_index: int = Form(0),
    images_to_keep: Optional[str] = Form("[]"), # JSON string of URLs to keep
    
    # --- FILE UPLOADS ---
    new_images: list[UploadFile] = File(default=[]), 
    
    db: AsyncSession = Depends(get_db)
):
    try:
        clean_name = category_name.strip()
        
        # 1. Check if category exists in products
        check_query = text("SELECT 1 FROM products WHERE category = :name LIMIT 1")
        res = await db.execute(check_query, {"name": clean_name})
        if not res.fetchone():
            raise HTTPException(status_code=404, detail=f"Category '{clean_name}' does not exist.")

        # 2. Parse the images the admin wants to keep
        try:
            final_images = json.loads(images_to_keep)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid format for images_to_keep")

        # 3. Handle NEW Image Uploads Concurrently
        if new_images:
            print(f"⏳ [STATUS] Parallel uploading {len(new_images)} category images...")
            tasks = []
            for img in new_images:
                if img.filename:
                    contents = await img.read()
                    tasks.append(upload_category_images_to_s3(contents, img.filename, clean_name))

            # Fire them all at once!
            uploaded_urls = await asyncio.gather(*tasks)
            final_images.extend(uploaded_urls)
            print(f"✅ [STATUS] Category uploads complete: {uploaded_urls}")

        # 4. Generate ID (Only used if this is the first time adding metadata)
        new_cat_id = f"cat_{uuid.uuid4().hex[:8]}"

        # 5. UPSERT the metadata to the database
        upsert_query = text("""
            INSERT INTO category_metadata (category_id, category_name, title, description, images, display_index)
            VALUES (:id, :name, :title, :description, :images, :index)
            
            ON CONFLICT (category_name) 
            DO UPDATE SET 
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                images = EXCLUDED.images,
                display_index = EXCLUDED.display_index;
        """)

        await db.execute(upsert_query, {
            "id": new_cat_id,
            "name": clean_name,
            "title": title,
            "description": description,
            "images": json.dumps(final_images),
            "index": display_index
        })

        await db.commit()

        return {
            "status": "success",
            "message": f"Metadata for '{clean_name}' updated successfully.",
            "images": final_images
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to update category metadata")