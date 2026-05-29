import boto3
from botocore.client import Config
import uuid
import os
import mimetypes
from io import BytesIO
from datetime import datetime  
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import load_dotenv



BASE_DIR = Path(__file__).resolve().parent.parent
env_path = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=env_path)

S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")







# S3_BUCKET = "sample-geolocation-tester"
# S3_REGION = "ap-south-1"  # ap-south-1

# s3_client = boto3.client(
#     "s3",
#     aws_access_key_id=S3_ACCESS_KEY,
#     aws_secret_access_key=S3_SECRET_KEY,
#     region_name=S3_REGION,
#     config=Config(signature_version='s3v4')
# )

# CLOUDFRONT_URL = "https://d3a6tvcqrtqof5.cloudfront.net"
# s3_executor = ThreadPoolExecutor(max_workers=10)

# def sync_s3_upload(file_content: bytes, filename: str, product_id: str):
#     """The actual blocking boto3 call"""
#     s3_key = f"products/{product_id}/{filename}"
    
#     s3_client.upload_fileobj(
#         BytesIO(file_content),
#         S3_BUCKET,
#         s3_key,
#         ExtraArgs={
#             "ContentType": "image/jpeg",
#             "ContentDisposition": "inline" 
#         }
#     )
#     return f"{CLOUDFRONT_URL}/{s3_key}"

# async def upload_product_images_to_s3(file_content: bytes, filename: str, product_id: str):
#     """Async wrapper that runs the upload in a separate thread"""
#     loop = asyncio.get_running_loop()
#     # This offloads the work to the thread pool so the API stays responsive
#     return await loop.run_in_executor(
#         s3_executor, 
#         sync_s3_upload, 
#         file_content, 
#         filename, 
#         product_id
#     )



def delete_image_from_s3(image_url: str):
    """Deletes an image from the S3 bucket using its CloudFront URL"""
    try:
        # Your exact CloudFront domain
        domain = "https://d3a6tvcqrtqof5.cloudfront.net/" 
        
        # Check if the URL contains your domain
        if image_url.startswith(domain):
            # Remove the domain to get the exact S3 file path (key)
            s3_key = image_url.replace(domain, "")
            
            # Delete it from S3
            s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
            print(f"✅ Successfully deleted from S3: {s3_key}")
    except Exception as e:
        print(f"❌ Warning: Failed to delete {image_url} from S3. Error: {e}")




















S3_BUCKET = "nakireddy-brothers"
S3_REGION = "ap-south-1"  # ap-south-1

s3_client = boto3.client(
    "s3",
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
    config=Config(signature_version='s3v4')
)

CLOUDFRONT_URL = "https://deo15mwrimufp.cloudfront.net"
s3_executor = ThreadPoolExecutor(max_workers=10)

def sync_s3_upload(file_content: bytes, filename: str, product_id: str):
    """The actual blocking boto3 call"""
    s3_key = f"database-images/products/{product_id}/{filename}"
    
    s3_client.upload_fileobj(
        BytesIO(file_content),
        S3_BUCKET,
        s3_key,
        ExtraArgs={
            "ContentType": "image/jpeg",
            "ContentDisposition": "inline" 
        }
    )
    return f"{CLOUDFRONT_URL}/{s3_key}"

async def upload_product_images_to_s3(file_content: bytes, filename: str, product_id: str):
    """Async wrapper that runs the upload in a separate thread"""
    loop = asyncio.get_running_loop()
    # This offloads the work to the thread pool so the API stays responsive
    return await loop.run_in_executor(
        s3_executor, 
        sync_s3_upload, 
        file_content, 
        filename, 
        product_id
    )








# ------------------categories----------------------------

def sync_s3_category_upload(file_content: bytes, filename: str, category_name: str):
    """The actual blocking boto3 call for Categories"""
    # Clean the category name so it doesn't create weird folder names with spaces
    safe_cat_name = category_name.replace(" ", "_").lower()
    s3_key = f"database-images/categories/{safe_cat_name}/{filename}"
    
    s3_client.upload_fileobj(
        BytesIO(file_content),
        S3_BUCKET,
        s3_key,
        ExtraArgs={
            "ContentType": "image/jpeg",
            "ContentDisposition": "inline" 
        }
    )
    return f"{CLOUDFRONT_URL}/{s3_key}"


async def upload_category_images_to_s3(file_content: bytes, filename: str, category_name: str):
    """Async wrapper that runs the upload in a separate thread"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        s3_executor, 
        sync_s3_category_upload, 
        file_content, 
        filename, 
        category_name
    )

