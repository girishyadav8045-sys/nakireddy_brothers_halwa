import jwt
from datetime import datetime, timedelta, timezone

# 🚨 IMPORTANT: In production, store this in a .env file!
# This is the "Master Key" used to sign the wristbands.
SECRET_KEY = "my_super_secret_halwa_key_12345" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7 # The token expires after a week

def create_access_token(data: dict):
    """Takes user data and turns it into a secure JWT string."""
    to_encode = data.copy()
    
    # Add an expiration date to the payload
    expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    
    # Mathematically sign the token using your secret key
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_access_token(token: str):
    """Reads the JWT string and returns the user data if valid."""
    try:
        # This will automatically check the signature and the expiration date!
        decoded_data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded_data
    except jwt.ExpiredSignatureError:
        return None # The token is too old
    except jwt.InvalidTokenError:
        return None # Someone tried to fake the token