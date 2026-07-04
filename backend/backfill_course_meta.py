"""One-off backfill: assign a category (and a book cover, where missing) to
existing courses and books that predate those features.

Safe to run repeatedly — only touches rows where the field is still empty.

Run:
  python3 backfill_course_meta.py            # categories + covers
  python3 backfill_course_meta.py --dry-run  # show what would change
  python3 backfill_course_meta.py --covers-only
  python3 backfill_course_meta.py --categories-only
"""

import argparse
import asyncio

from sqlalchemy import select

from app.database import async_session
from app.models import Course
from app.categories import categories_prompt_block, normalize_category, CATEGORIES
from app.services.ai_service import generate_json, FLASH_MODEL
from app.services.book_service import fetch_book_cover


CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {"category": {"type": "string"}},
    "required": ["category"],
}


async def classify(title: str, description: str, authors_kind: str) -> str:
    """Ask the fast model to assign one canonical category."""
    prompt = f"""Ordne das folgende {authors_kind} GENAU EINER Kategorie zu.

TITEL: "{title}"
BESCHREIBUNG: {description or '(keine)'}

{categories_prompt_block()}

Antworte nur mit dem JSON: {{"category": "..."}}"""
    try:
        res = await generate_json(prompt, CATEGORY_SCHEMA, model=FLASH_MODEL, temperature=0)
        if res and isinstance(res, dict):
            return normalize_category(res.get("category"))
    except Exception as e:
        print(f"    ! classify failed: {e}")
    return normalize_category(None)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--covers-only", action="store_true")
    ap.add_argument("--categories-only", action="store_true")
    args = ap.parse_args()

    do_categories = not args.covers_only
    do_covers = not args.categories_only

    async with async_session() as db:
        courses = (await db.execute(select(Course))).scalars().all()
        print(f"Found {len(courses)} course(s). "
              f"Categories: {do_categories}, Covers: {do_covers}, Dry-run: {args.dry_run}\n")

        changed = 0
        for c in courses:
            is_book = (c.kind or "teacher") == "book"
            updates = []

            if do_categories and not c.category:
                cat = await classify(
                    c.title, c.description or "",
                    "Buch" if is_book else "Lernkurs (Thema)",
                )
                updates.append(f"category={cat!r}")
                if not args.dry_run:
                    c.category = cat

            if do_covers and is_book and not c.book_cover_url:
                cover = await fetch_book_cover(
                    title=c.title, authors=c.book_authors or [], isbn=c.book_isbn,
                )
                if cover:
                    updates.append("cover=set")
                    if not args.dry_run:
                        c.book_cover_url = cover
                else:
                    updates.append("cover=not-found")

            if updates:
                changed += 1
                print(f"  {c.title[:45]:<47} -> {', '.join(updates)}")

        if not args.dry_run and changed:
            await db.commit()
            print(f"\nCommitted changes to {changed} course(s).")
        elif args.dry_run:
            print(f"\nDry-run — {changed} course(s) would change. Nothing written.")
        else:
            print("\nNothing to backfill — all courses already have categories/covers.")

    # Verify the category list is what we expect
    print(f"\n({len(CATEGORIES)} canonical categories available.)")


if __name__ == "__main__":
    asyncio.run(main())
