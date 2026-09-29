#!/usr/bin/env python3
"""Rebuild every Qdrant vector using the configured OpenAI embedding model.

Usage (from backend/):
    python reindex_embeddings.py --recreate          # full rebuild
    python reindex_embeddings.py --recreate --resume # skip already-indexed IDs

--resume reads the existing IDs from the Qdrant collection and skips them.
Use it after a failed run to continue where it stopped without re-doing work.

--recreate is always required to avoid mixing vector spaces.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.database import async_session
from app.models import Folder, Image, Note
from app.services.vector_service import (
    COLLECTION_NAME,
    _get_qdrant,
    recreate_collection,
    upsert_note_embedding,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _existing_ids() -> set[str]:
    """Return all point IDs already in the Qdrant collection."""
    client = _get_qdrant()
    ids: set[str] = set()
    offset = None
    while True:
        result, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1000,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        for point in result:
            ids.add(str(point.id))
        if next_offset is None:
            break
        offset = next_offset
    return ids


async def main(recreate: bool, resume: bool) -> None:
    if not recreate:
        raise SystemExit(
            "Refusing to mix vector spaces — re-run with --recreate.\n"
            "Add --resume to continue a previously interrupted run."
        )

    if resume:
        logger.info("Resume mode: reading already-indexed IDs from Qdrant …")
        skip_ids = await asyncio.to_thread(_existing_ids)
        logger.info("Found %d already-indexed records — skipping them.", len(skip_ids))
    else:
        await asyncio.to_thread(recreate_collection)
        skip_ids = set()

    count = 0
    skipped = 0

    async with async_session() as db:
        # ── Notes ──────────────────────────────────────────────────────────────
        rows = (
            await db.execute(
                select(Note, Folder.path).join(Folder, Note.folder_id == Folder.id)
            )
        ).all()

        for note, folder_path in rows:
            note_id = str(note.id)
            if note_id in skip_ids:
                skipped += 1
                continue
            try:
                await asyncio.to_thread(
                    upsert_note_embedding,
                    note_id, str(note.user_id), note.title, note.content, folder_path,
                )
                count += 1
                if count % 50 == 0:
                    logger.info("Reindexed %d records (skipped %d)", count, skipped)
            except Exception as exc:
                logger.error("Failed to embed note %s (%s): %s", note_id, note.title[:60], exc)

        # ── Image / document descriptions ──────────────────────────────────────
        image_rows = (
            await db.execute(
                select(Image, Folder.path)
                .outerjoin(Folder, Image.folder_id == Folder.id)
                .where(Image.description.isnot(None))
            )
        ).all()

        for image, folder_path in image_rows:
            image_id = str(image.id)
            if image_id in skip_ids:
                skipped += 1
                continue
            try:
                await asyncio.to_thread(
                    upsert_note_embedding,
                    image_id, str(image.user_id), image.original_filename,
                    image.description or "", folder_path or "Uploads",
                )
                image.embedded = True
                count += 1
                if count % 50 == 0:
                    logger.info("Reindexed %d records (skipped %d)", count, skipped)
            except Exception as exc:
                logger.error("Failed to embed image %s (%s): %s", image_id, image.original_filename, exc)

        await db.commit()

    logger.info(
        "Reindex complete: %d newly indexed, %d skipped (already present).",
        count, skipped,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate", action="store_true",
        help="Required safety flag — confirms intentional rebuild.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip IDs already present in the collection instead of wiping it.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.recreate, args.resume))
