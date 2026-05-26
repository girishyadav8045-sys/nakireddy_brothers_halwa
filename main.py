from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from routers import customers, admin_controls, products, cart, payments, admin_address, coupons, auth

# Import your async engine and Base from database.py
from database import engine, Base, AsyncSessionLocal
import models
# Import your routers (assuming you have a file like routers/tasks.py)
# from routers import tasks 

# --- Lifespan for Table Creation ---
# In async, we use a lifespan to handle startup/shutdown logic
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Logic ---
    print("Creating tables...")
    async with engine.begin() as conn:
        # This safely runs the synchronous create_all in an async environment
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully!")
    
    yield # The app runs here
    
    # --- Shutdown Logic (Optional) ---
    print("Shutting down...")
    await engine.dispose()

app = FastAPI(title="Halwa Backend", lifespan=lifespan)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Dependency ---
# This replaces your old get_db with an async version
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# --- Routes ---
@app.get("/")
async def root():
    return {"status": "Halwa API is running smoothly"}

# To include your routers folder logic:
app.include_router(customers.router)
app.include_router(admin_controls.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(payments.router)
app.include_router(admin_address.router)
app.include_router(coupons.router)
app.include_router(auth.router)