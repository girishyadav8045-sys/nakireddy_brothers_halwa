from pydantic import BaseModel, EmailStr,  Field, ConfigDict
from typing import List, Optional
from datetime import datetime

class CustomerCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone_number: str


class UniversalLogin(BaseModel):
    identifier: str  # This can be the email OR the phone number

class AdminLogin(BaseModel):
    identifier: str  # Email or Phone Number
    password: str


class PriceSchema(BaseModel):
    kg: Optional[float] = None
    g500: Optional[float] = Field(None, alias="500g")
    g250: Optional[float] = Field(None, alias="250g")

    model_config = ConfigDict(extra='allow')

class NutrientSchema(BaseModel):
    name: str       # e.g., "Protein", "Sugar"
    amount: str     # e.g., "5g", "10mg"

class ProductInfoSchema(BaseModel):
    description: str
    shelf_life: str
    ingredients: str
    preparation_details: str
    delivery_info: str
    nutrients: List[NutrientSchema] = []

class ReviewSchema(BaseModel):
    name: str
    stars: float = Field(..., ge=1, le=5)
    description: str


class CartAddRequest(BaseModel):
    user_identifier: str  # Can be the Guest UUID or the real Customer ID
    product_id: str
    weight_variant: str   # e.g., "250g", "kg"
    quantity: int = 1

class CartMergeRequest(BaseModel):
    guest_id: str
    customer_id: str



class AddressSchema(BaseModel):
    name: str
    phone_number: str
    house_number: str
    street: str
    landmark: Optional[str] = None  # Optional, in case they don't have one
    village: str
    mandal: str
    dist: str
    state: str
    pincode: str

class AdminAddressSchema(BaseModel):
    name: str
    phone_number: str
    house_number: str
    street: str
    landmark: Optional[str] = None
    village: str
    mandal: str
    dist: str
    state: str
    pincode: str


class DateFilterRequest(BaseModel):
    start_date: str  # Format expected: "YYYY-MM-DD"
    end_date: Optional[str] = None  # Format expected: "YYYY-MM-DD"


class BulkShipmentRequest(BaseModel):
    order_ids: list[str]





class CreatePaymentOrderRequest(BaseModel):
    customer_id: str
    address_id: str # The address they chose to ship to
    coupon_code: Optional[str] = None # <-- ADD THIS LINE



class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    customer_id: str   # <-- Python crashed because this was missing
    address_id: str



class CreateCouponRequest(BaseModel):
    code: str
    discount_type: str # Must be 'percentage' or 'flat'
    discount_value: float
    min_order_value: float = 0.0
    max_discount: Optional[float] = None # E.g., Max ₹500 off
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    usage_limit: Optional[int] = None
    is_active: bool = True

class ValidateCouponRequest(BaseModel):
    coupon_code: str
    customer_id: str


class UpdateCouponRequest(BaseModel):
    # Notice we DO NOT include 'code' here. The code cannot be changed.
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    min_order_value: Optional[float] = None
    max_discount: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    usage_limit: Optional[int] = None
    is_active: Optional[bool] = None



class CreateAdminSchema(BaseModel):
    admin_name: str
    email: EmailStr
    phone_number: str
