import uuid
from sqlalchemy import Column, String, DateTime, Integer, text, ForeignKey, Float, DateTime, JSON, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from database import Base

def generate_customer_id():
    return f"cust_{uuid.uuid4().hex[:8]}"




class Customer(Base):
    __tablename__ = "customers"

    # Primary key using UUID
    # as_uuid=True ensures SQLAlchemy handles it as a Python UUID object
    customer_id = Column(
    String,
    primary_key=True,
    default=generate_customer_id,
    index=True
    )
    
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    phone_number = Column(String, unique=False, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    address = Column(JSONB, nullable=True)
    
    registration_date = Column(DateTime(timezone=True), server_default=func.now())



class Admin(Base):
    __tablename__ = "admins"

    admin_id = Column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid.uuid4, 
        index=True
    )
    
    admin_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone_number = Column(String, unique=True, index=True, nullable=False)

    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    addresses = Column(JSONB, nullable=True, default=list)


class Product(Base):
    __tablename__ = "products"

    product_id = Column(String, primary_key=True, index=True)
    product_name = Column(String, nullable=False)
    
    # JSONB Fields
    image_urls = Column(JSONB, default=[]) # ["url1", "url2"]
    prices = Column(JSONB, nullable=False) # {"kg": 100, "500g": 60, "250g": 35}
    info = Column(JSONB, nullable=False)   # {description, shelf_life, ingredients, etc}
    reviews = Column(JSONB, default=[])    # [{"name": "Girish", "stars": 5, "description": "Good"}]
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())




class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Renamed to be flexible. It holds EITHER a Guest UUID or a Customer ID
    user_identifier = Column(String, index=True, nullable=False) 
    
    product_id = Column(String, ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False)
    weight_variant = Column(String, nullable=False) 
    quantity = Column(Integer, default=1, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())



def generate_custom_order_id():
    # uuid.uuid4().hex generates a random 32-character string.
    # We slice [:10] to keep it short and readable, but still unique!
    # Result: "order_f4a2b9c8d1"
    return f"order_{uuid.uuid4().hex[:10]}"


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(
        String, 
        primary_key=True, 
        default=generate_custom_order_id, # Passes the function to SQLAlchemy
        index=True
    )
    customer_id = Column(String, index=True, nullable=False)
    
    # We save the exact items they bought as a JSON array (like a snapshot)
    items = Column(JSON, nullable=False) 
    
    # Where is it going?
    shipping_address = Column(JSON, nullable=False)
    
    # Financials
    total_amount = Column(Float, nullable=False)
    
    # Razorpay Details
    razorpay_order_id = Column(String, unique=True, nullable=False)
    razorpay_payment_id = Column(String, unique=True, nullable=False)
    
    # E.g., "Paid", "Shipped", "Delivered", "Rejected"
    status = Column(String, default="Paid", nullable=False) 
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())



class Coupon(Base):
    __tablename__ = "coupons"

    # The actual code users type (e.g., "HALWA100", "FESTIVE20")
    code = Column(String, primary_key=True, index=True) 
    
    # "percentage" or "flat"
    discount_type = Column(String, nullable=False) 
    discount_value = Column(Float, nullable=False) # e.g., 10 (for 10%) or 100 (for ₹100)
    
    # The conditions you asked for
    min_order_value = Column(Float, default=0.0)
    max_discount = Column(Float, nullable=True) # Cap the percentage discount
    
    # Date limits
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    
    # Total usage limits (e.g., First 100 people)
    usage_limit = Column(Integer, nullable=True) # If null, unlimited users can use it
    used_count = Column(Integer, server_default="0", nullable=False) # We add +1 every time someone pays
    
    # Admin kill switch (in case a code goes viral and you want to stop it manually)
    is_active = Column(Boolean, default=True) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CouponUsage(Base):
    """
    This is the Ledger. It permanently tracks WHO used WHICH coupon on WHAT order.
    """
    __tablename__ = "coupon_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    coupon_code = Column(String, ForeignKey("coupons.code"), nullable=False)
    customer_id = Column(String, nullable=False)
    order_id = Column(String, nullable=False) # The Razorpay order string
    used_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- THE MAGIC RULE ---
    # This forces PostgreSQL to throw an error if the same customer 
    # tries to use the same coupon code twice!
    __table_args__ = (
        UniqueConstraint('coupon_code', 'customer_id', name='uq_coupon_customer'),
    )