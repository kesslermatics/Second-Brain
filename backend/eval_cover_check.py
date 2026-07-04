"""Quick real test of the book-cover lookup across a few titles."""
import asyncio
from app.services.book_service import fetch_book_cover

CASES = [
    {"title": "Atomic Habits", "authors": ["James Clear"], "isbn": "9780735211292"},
    {"title": "Clean Code", "authors": ["Robert C. Martin"], "isbn": "9780132350884"},
    {"title": "Sapiens", "authors": ["Yuval Noah Harari"], "isbn": None},
    {"title": "Der kleine Prinz", "authors": ["Antoine de Saint-Exupéry"], "isbn": None},
]


async def main():
    for c in CASES:
        url = await fetch_book_cover(title=c["title"], authors=c["authors"], isbn=c["isbn"])
        print(f"{c['title']:<20} -> {url}")


if __name__ == "__main__":
    asyncio.run(main())
