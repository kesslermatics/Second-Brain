from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=20, max_overflow=10)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Ensure note_type column exists (for existing databases)
        try:
            await conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS note_type VARCHAR(50) NOT NULL DEFAULT 'text'"
                )
            )
        except Exception:
            pass  # Column already exists or DB doesn't support IF NOT EXISTS
        # Ensure images table exists (for existing databases)
        try:
            await conn.execute(
                __import__('sqlalchemy').text(
                    "CREATE TABLE IF NOT EXISTS images ("
                    "id UUID PRIMARY KEY, "
                    "original_filename VARCHAR(512) NOT NULL, "
                    "stored_filename VARCHAR(512) NOT NULL, "
                    "content_type VARCHAR(100) NOT NULL, "
                    "file_size INTEGER NOT NULL, "
                    "file_path VARCHAR(1024) NOT NULL, "
                    "description TEXT, "
                    "folder_id UUID REFERENCES folders(id) ON DELETE SET NULL, "
                    "note_id UUID REFERENCES notes(id) ON DELETE SET NULL, "
                    "user_id UUID NOT NULL REFERENCES users(id), "
                    "embedded BOOLEAN DEFAULT FALSE, "
                    "created_at TIMESTAMPTZ DEFAULT NOW()"
                    ")"
                )
            )
        except Exception:
            pass
        # Ensure folders.parent_id has ON DELETE CASCADE (for existing databases)
        try:
            await conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE folders DROP CONSTRAINT IF EXISTS folders_parent_id_fkey"
                )
            )
            await conn.execute(
                __import__('sqlalchemy').text(
                    "ALTER TABLE folders ADD CONSTRAINT folders_parent_id_fkey "
                    "FOREIGN KEY (parent_id) REFERENCES folders(id) ON DELETE CASCADE"
                )
            )
        except Exception:
            pass
        # Ensure user_states table exists (for existing databases)
        try:
            await conn.execute(
                __import__('sqlalchemy').text(
                    "CREATE TABLE IF NOT EXISTS user_states ("
                    "id UUID PRIMARY KEY, "
                    "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                    "key VARCHAR(255) NOT NULL, "
                    "value TEXT NOT NULL DEFAULT '{}', "
                    "updated_at TIMESTAMPTZ DEFAULT NOW(), "
                    "CONSTRAINT uq_user_state_key UNIQUE (user_id, key)"
                    ")"
                )
            )
        except Exception:
            pass
        # Ensure courses / course_units / course_messages tables exist (Infinite Teacher)
        try:
            await conn.execute(
                __import__('sqlalchemy').text(
                    "CREATE TABLE IF NOT EXISTS courses ("
                    "id UUID PRIMARY KEY, "
                    "topic VARCHAR(512) NOT NULL, "
                    "title VARCHAR(512) NOT NULL, "
                    "description TEXT, "
                    "status VARCHAR(50) NOT NULL DEFAULT 'draft', "
                    "parent_course_id UUID REFERENCES courses(id) ON DELETE SET NULL, "
                    "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                    "created_at TIMESTAMPTZ DEFAULT NOW(), "
                    "updated_at TIMESTAMPTZ DEFAULT NOW()"
                    ")"
                )
            )
            await conn.execute(
                __import__('sqlalchemy').text(
                    "CREATE TABLE IF NOT EXISTS course_units ("
                    "id UUID PRIMARY KEY, "
                    "course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE, "
                    "unit_number VARCHAR(20) NOT NULL, "
                    "title VARCHAR(512) NOT NULL, "
                    "description TEXT, "
                    "learning_objectives JSONB, "
                    "level INTEGER NOT NULL DEFAULT 1, "
                    "enabled BOOLEAN NOT NULL DEFAULT TRUE, "
                    "status VARCHAR(50) NOT NULL DEFAULT 'pending', "
                    "order_index INTEGER NOT NULL DEFAULT 0, "
                    "created_at TIMESTAMPTZ DEFAULT NOW()"
                    ")"
                )
            )
            await conn.execute(
                __import__('sqlalchemy').text(
                    "CREATE TABLE IF NOT EXISTS course_messages ("
                    "id UUID PRIMARY KEY, "
                    "course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE, "
                    "unit_id UUID REFERENCES course_units(id) ON DELETE CASCADE, "
                    "role VARCHAR(50) NOT NULL, "
                    "content TEXT NOT NULL, "
                    "metadata JSONB, "
                    "created_at TIMESTAMPTZ DEFAULT NOW()"
                    ")"
                )
            )
        except Exception:
            pass
        # Ensure book columns exist on courses table (interactive book chapters)
        try:
            for col, dtype in [
                ("kind", "VARCHAR(50) NOT NULL DEFAULT 'teacher'"),
                ("book_authors", "JSONB"),
                ("book_year", "VARCHAR(20)"),
                ("book_isbn", "VARCHAR(50)"),
                ("book_publisher", "VARCHAR(255)"),
            ]:
                await conn.execute(
                    __import__('sqlalchemy').text(
                        f"ALTER TABLE courses ADD COLUMN IF NOT EXISTS {col} {dtype}"
                    )
                )
        except Exception:
            pass