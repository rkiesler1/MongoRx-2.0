import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware

from motor.motor_asyncio import AsyncIOMotorClient

from apps.trials.routers import trial_router, drug_router
from config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await startup_db_client()
        yield
    finally:
        await shutdown_db_client()
        
app = FastAPI(lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#@app.on_event("startup")
async def startup_db_client():
    app.mongodb_client = AsyncIOMotorClient(settings.DB_URL)
    app.mongodb = app.mongodb_client[settings.DB_NAME]

#@app.on_event("shutdown")
async def shutdown_db_client():
    app.mongodb_client.close()


app.include_router(trial_router, tags=["trials"], prefix="/trials")
app.include_router(drug_router, tags=["drugs"], prefix="/drugs")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        reload=settings.DEBUG_MODE,
        port=settings.PORT,
    )
