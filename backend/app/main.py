from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import get_settings
from app.database import init_db, async_session
from app.auth import create_admin_user
from app.services.vector_service import ensure_collection
from app.routes.auth_routes import router as auth_router
from app.routes.folder_routes import router as folder_router
from app.routes.note_routes import router as note_router
from app.routes.chat_routes import router as chat_router
from app.routes.ai_routes import router as ai_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting up Brain Backend...")
    await init_db()

    async with async_session() as db:
        await create_admin_user(db)

    await ensure_collection()
    print("Brain Backend ready!")
    yield
    # Shutdown
    print("Shutting down Brain Backend...")


app = FastAPI(
    title="Brain - Second Brain API",
    description="API for the Second Brain application",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
]
if settings.FRONTEND_URLS:
    for url in settings.FRONTEND_URLS.split(","):
        url = url.strip()
        if url:
            origins.append(url)
            if not url.startswith("http"):
                origins.append(f"https://{url}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth_router, prefix="/api")
app.include_router(folder_router, prefix="/api")
app.include_router(note_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(ai_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Brain - Second Brain API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
