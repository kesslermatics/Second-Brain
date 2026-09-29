#!/usr/bin/env python3
"""Rebuild every Qdrant vector using the configured OpenAI embedding model.

Usage (from backend):
    python reindex_embeddings.py --recreate

--recreate deliberately deletes only ``brain_notes_openai``. The historical
collection remains untouched, so this is safe to rerun after a failure.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.database import async_session
from app.models import Folder, Image, Note
from app.services.vector_service import recreate_collection, upsert_note_embedding

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(recreate: bool) -> None:
    if not recreate:
        raise SystemExit("Refusing to mix vector spaces. Re-run with --recreate.")
    await asyncio.to_thread(recreate_collection)
    count = 0
    async with async_session() as db:
        notes = (await db.execute(select(Note, Folder.path).join(Folder, Note.folder_id == Folder.id))).all()
        for note, folder_path in notes:
            await asyncio.to_thread(upsert_note_embedding, str(note.id), str(note.user_id), note.title, note.content, folder_path)
            count += 1
            if count % 50 == 0:
                logger.info("Reindexed %s notes/files", count)

        images = (await db.execute(select(Image, Folder.path).outerjoin(Folder, Image.folder_id == Folder.id)
                                   .where(Image.description.isnot(None)))).all()
        for image, folder_path in images:
            # Image descriptions can be searched even when no note was created for the upload.
            await asyncio.to_thread(
                upsert_note_embedding, str(image.id), str(image.user_id), image.original_filename,
                image.description or "", folder_path or "Uploads",
            )
            image.embedded = True
            count += 1
            if count % 50 == 0:
                logger.info("Reindexed %s notes/files", count)
        await db.commit()
    logger.info("Reindex complete: %s records in the OpenAI collection", count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recreate", action="store_true", help="Delete and rebuild the OpenAI-only collection")
    args = parser.parse_args()
    asyncio.run(main(args.recreate))
