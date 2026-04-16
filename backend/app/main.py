import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from app.config import get_settings
from app.database import init_db, async_session
from app.auth import create_admin_user
from app.services.vector_service import ensure_collection
from app.services.backup_service import start_backup_scheduler, stop_backup_scheduler
from app.routes.auth_routes import router as auth_router
from app.routes.folder_routes import router as folder_router
from app.routes.note_routes import router as note_router
from app.routes.chat_routes import router as chat_router
from app.routes.ai_routes import router as ai_router
from app.routes.settings_routes import router as settings_router
from app.routes.tag_routes import router as tag_router
from app.routes.search_routes import router as search_router
from app.routes.version_routes import router as version_router
from app.routes.link_routes import router as link_router
from app.routes.sr_routes import router as sr_router
from app.routes.dashboard_routes import router as dashboard_router
from app.routes.export_routes import router as export_router
from app.routes.summary_routes import router as summary_router
from app.routes.stream_routes import router as stream_router
from app.routes.upload_routes import router as upload_router
from app.routes.image_routes import router as image_router
from app.routes.book_routes import router as book_router
from app.routes.state_routes import router as state_router
from app.routes.teacher_routes import router as teacher_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    import time
    t0 = time.time()
    print("Starting up Brain Backend...")
    await init_db()
    print(f"  DB init: {time.time()-t0:.1f}s")

    t1 = time.time()
    async with async_session() as db:
        await create_admin_user(db)
    print(f"  Admin user: {time.time()-t1:.1f}s")

    t2 = time.time()
    await ensure_collection()
    print(f"  Qdrant collection: {time.time()-t2:.1f}s")

    t3 = time.time()
    start_backup_scheduler()
    print(f"  Backup scheduler: {time.time()-t3:.1f}s")

    print(f"Brain Backend ready! (total: {time.time()-t0:.1f}s)")
    yield
    # Shutdown
    stop_backup_scheduler()
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
        url = url.strip().rstrip("/")
        if url:
            origins.append(url)
            if not url.startswith("http"):
                origins.append(f"https://{url}")

print(f"[CORS] Allowed origins: {origins}")

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
app.include_router(settings_router, prefix="/api")
app.include_router(tag_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(version_router, prefix="/api")
app.include_router(link_router, prefix="/api")
app.include_router(sr_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(summary_router, prefix="/api")
app.include_router(stream_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(image_router, prefix="/api")
app.include_router(book_router, prefix="/api")
app.include_router(state_router, prefix="/api")
app.include_router(teacher_router, prefix="/api")

# Serve uploaded files statically
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.get("/")
async def root():
    return {"message": "Brain - Second Brain API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
