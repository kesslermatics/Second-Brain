"""Book processing service — search, TOC extraction, chapter note generation, topic deep-dive."""

from app.services.ai_service import (
    generate_with_search, generate, generate_stream, generate_with_search_stream,
    generate_json, generate_with_search_sources, PRO_MODEL, FLASH_MODEL, DEFAULT_NOTE_PROMPT,
)
from app.config import get_settings
from app.categories import categories_prompt_block, normalize_category
import asyncio
import json
import io
import logging

logger = logging.getLogger(__name__)

# ── PDF text extraction ───────────────────────────────────────────────

def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF as a single string.

    Uses pypdf which is pure-Python and needs no system dependencies.
    Returns empty string on any failure so callers can fall back gracefully.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        logger.warning(f"PDF text extraction failed: {e}")
        return ""


def extract_pdf_toc_metadata(pdf_bytes: bytes) -> list[dict] | None:
    """Try to read the PDF's built-in outline/bookmark tree.

    Returns a flat list of {"title": str, "level": int} or None when no
    bookmarks are present (caller must fall back to AI-extraction).
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        outline = reader.outline
        if not outline:
            return None

        result: list[dict] = []
        counter: dict[int, int] = {}  # level → running chapter number

        def _walk(items, level: int = 1):
            ch_at_level = 0
            for item in items:
                if isinstance(item, list):
                    _walk(item, level + 1)
                else:
                    title = getattr(item, "title", None) or str(item)
                    # Build a dotted chapter_number like "2.3.1"
                    counter[level] = counter.get(level, 0) + 1
                    # Reset deeper levels when a shallower one advances
                    for deeper in list(counter.keys()):
                        if deeper > level:
                            del counter[deeper]
                    chapter_number = ".".join(str(counter.get(l, 1)) for l in range(1, level + 1))
                    result.append({
                        "chapter_number": chapter_number,
                        "title": title.strip(),
                        "level": level,
                    })
                    ch_at_level += 1

        _walk(outline)
        return result if result else None
    except Exception as e:
        logger.warning(f"PDF TOC extraction failed: {e}")
        return None


# ── PDF-aware TOC extraction ──────────────────────────────────────────

async def get_pdf_toc(pdf_bytes: bytes, book_title: str, authors: list[str]) -> dict:
    """Extract the TOC from the actual PDF, falling back to AI text analysis.

    Priority:
      1. PDF bookmark/outline metadata (instant, no AI cost)
      2. AI analysis of the first ~15 000 chars of extracted text
    """
    # 1. Native PDF outline
    toc_from_meta = extract_pdf_toc_metadata(pdf_bytes)
    if toc_from_meta:
        # Filter out front/back matter noise — English and German variants
        skip_keywords = {
            # German
            "vorwort", "geleitwort", "danksagung", "widmung",
            "inhaltsverzeichnis", "abbildungsverzeichnis", "tabellenverzeichnis",
            "abkürzungsverzeichnis", "glossar", "stichwortverzeichnis", "register",
            "literaturverzeichnis", "quellenverzeichnis", "bibliografie", "bibliography",
            "anhang", "nachwort", "über den autor", "titelseite", "impressum",
            # English
            "preface", "foreword", "acknowledgement", "acknowledgment", "dedication",
            "contents", "table of contents", "list of figures", "list of tables",
            "list of abbreviations", "glossary", "index",
            "references", "bibliography", "appendix", "afterword",
            "about the author", "title page", "copyright", "half title",
            "title card", "cover", "front matter", "back matter", "colophon",
        }
        filtered = [
            ch for ch in toc_from_meta
            if not any(kw in ch["title"].lower() for kw in skip_keywords)
        ]
        if filtered:
            return {"chapters": filtered, "total_chapters": len(filtered), "source": "pdf_metadata"}

    # 2. AI analysis of the raw text
    full_text = extract_pdf_text(pdf_bytes)
    if not full_text:
        # PDF has no extractable text (scanned image) — fall back to web search
        return await get_book_toc(book_title, authors)

    # Feed the first chunk of the book to the AI so it can spot the TOC section
    sample = full_text[:15000]
    authors_str = ", ".join(authors) if authors else "Unbekannt"
    prompt = f"""Das folgende ist der Anfang des Buches „{book_title}" von {authors_str}.
Extrahiere das vollständige Inhaltsverzeichnis direkt aus diesem Text.

BUCHTEXT (Anfang):
{sample}

Gib das Inhaltsverzeichnis als JSON zurück. Jeder Eintrag hat:
- "title": Kapitelname (genau wie im Text)
- "level": Verschachtelungstiefe (1 = Hauptkapitel, 2 = Unterkapitel, 3 = Unter-Unterkapitel)
- "chapter_number": Kapitelnummer als String (z.B. "1", "1.1", "1.1.1")

Antworte NUR mit dem JSON:
{{
    "chapters": [
        {{"chapter_number": "1", "title": "Einleitung", "level": 1}},
        {{"chapter_number": "1.1", "title": "Unterkapitel", "level": 2}}
    ],
    "total_chapters": 10
}}

Lasse folgende Einträge KOMPLETT WEG (sie haben keinen inhaltlichen Mehrwert):
- Titelseite, Impressum, Copyright, Half Title, Title Card, Cover
- Vorwort, Geleitwort, Danksagung, Widmung
- Preface, Foreword, Acknowledgements, Dedication
- Inhaltsverzeichnis, Abbildungsverzeichnis, Tabellenverzeichnis, Abkürzungsverzeichnis
- Table of Contents, List of Figures, List of Tables, List of Abbreviations
- Index, Stichwortverzeichnis, Register, Glossar, Glossary
- Literaturverzeichnis, Quellenverzeichnis, Bibliografie, Bibliography, References
- Anhang, Appendix, Nachwort, Afterword, Colophon
- Über den Autor, About the Author, Front Matter, Back Matter"""

    result = await generate_json(prompt, BOOK_TOC_SCHEMA, model=PRO_MODEL, temperature=0.1)
    if result and isinstance(result, dict) and result.get("chapters"):
        result["source"] = "pdf_text_ai"
        result.setdefault("total_chapters", len(result["chapters"]))
        return result

    # Ultimate fallback: web search (like the non-PDF path)
    fallback = await get_book_toc(book_title, authors)
    fallback["source"] = "web_search_fallback"
    return fallback


# ── PDF-aware chapter note ────────────────────────────────────────────

# How many characters of PDF text to feed per chapter.
# ~12 000 chars ≈ 3 000 tokens — leaves plenty of room for the full prompt
# while keeping costs reasonable for long books.
PDF_CHAPTER_CHARS = 12_000


def _slice_chapter_text(full_text: str, chapter: dict, all_chapters: list[dict]) -> str:
    """Best-effort: find the chapter's text block inside the full PDF text.

    Strategy: search for the chapter title, then read until the next chapter title
    or PDF_CHAPTER_CHARS characters, whichever comes first.
    """
    title = chapter["title"].strip()
    # Try an exact search first, then a case-insensitive search
    idx = full_text.find(title)
    if idx == -1:
        idx = full_text.lower().find(title.lower())
    if idx == -1:
        # Cannot locate — return empty so the AI knows there's no context
        return ""

    # Find end: position of the NEXT chapter's title (any level)
    end_idx = len(full_text)
    for other in all_chapters:
        if other["chapter_number"] == chapter["chapter_number"]:
            continue
        other_title = other["title"].strip()
        pos = full_text.find(other_title, idx + len(title))
        if pos == -1:
            pos = full_text.lower().find(other_title.lower(), idx + len(title))
        if pos != -1 and pos < end_idx:
            end_idx = pos

    snippet = full_text[idx: idx + min(PDF_CHAPTER_CHARS, end_idx - idx)]
    return snippet.strip()


async def generate_chapter_note_from_pdf(
    pdf_text: str,
    book_title: str,
    authors: list[str],
    chapter: dict,
    all_chapters: list[dict],
    folder_structure: list[dict],
    existing_tags: list[str] | None = None,
    existing_note_titles: list[str] | None = None,
) -> dict:
    """Generate a chapter note using the actual PDF text as source of truth.

    Falls back to the normal (web-search) path if no text can be located for
    the chapter — so quality degrades gracefully instead of erroring out.
    """
    authors_str = ", ".join(authors) if authors else "Unbekannt"
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"
    chapter_ref = f"Kapitel {chapter['chapter_number']}: {chapter['title']}"

    chapter_text = _slice_chapter_text(pdf_text, chapter, all_chapters)

    if not chapter_text:
        # No text found → fall back to AI-knowledge path
        return await generate_chapter_note(
            book_title=book_title,
            authors=authors,
            chapter=chapter,
            folder_structure=folder_structure,
            existing_tags=existing_tags,
            existing_note_titles=existing_note_titles,
        )

    dedup_block = ""
    if existing_note_titles:
        titles_list = "\n".join(f"- {t}" for t in existing_note_titles)
        dedup_block = f"""
BEREITS EXISTIERENDE NOTIZEN zu diesem Buch (aus vorherigen Kapiteln):
{titles_list}

WICHTIGE REGEL ZUR VERMEIDUNG VON DUPLIKATEN:
- Wiederhole KEINE Inhalte, die in den oben genannten Notizen bereits behandelt wurden.
- Wenn ein Konzept bereits als Notiz existiert, verweise kurz darauf statt es erneut zu erklären.
- Verwende ANDERE Beispiele als in vorherigen Kapiteln — bringe frische, kapitelspezifische Beispiele.
"""

    prompt = f"""Du bist ein Second Brain Assistent. Erstelle eine ausführliche, gut strukturierte Notiz
für das folgende Buchkapitel. Der Inhalt MUSS ausschließlich auf dem bereitgestellten Buchtext basieren —
erfinde oder ergänze NICHTS, das nicht im Text steht.

Buch: "{book_title}" von {authors_str}
Kapitel: {chapter_ref}
{dedup_block}

BUCHTEXT FÜR DIESES KAPITEL:
\"\"\"
{chapter_text}
\"\"\"

Erstelle die Notiz im folgenden JSON-Format (NUR das JSON, kein anderer Text):
{{
    "suggested_folder": "Bücher/{book_title}",
    "suggested_title": "{chapter_ref}",
    "formatted_content": "Der formatierte Inhalt der Notiz in Markdown",
    "suggested_tags": ["tag1", "tag2"]
}}

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen. Erstelle neue nur wenn nötig.

Formatierungsregeln für formatted_content (sehr wichtig!):
- Beginne mit einer kurzen Einordnung: Aus welchem Buch, welches Kapitel
- Strukturiere den Inhalt gut mit Markdown-Headings (##, ###)
- Verwende **Fettdruck** für Schlüsselbegriffe
- Verwende Aufzählungslisten für Hierarchien
- Verwende Callouts für wichtige Konzepte:
  > [!MERKSATZ]
  > Für Kernaussagen aus dem Text
  
  > [!BEISPIEL]
  > Für konkrete Beispiele aus dem Buchtext
  
  > [!DEFINITION]
  > Für Begriffserklärungen aus dem Text

- Fasse die WESENTLICHEN Inhalte des Kapitels zusammen — NUR was wirklich im Text steht
- Schreibe sachlich, klar und informativ in neutraler Form
- Die Notiz soll wie eine gute Zusammenfassung sein, die man zum Lernen nutzen kann
- Schreibe in der Sprache des Buches"""

    result = await generate_json(prompt, {
        "type": "object",
        "properties": {
            "suggested_folder": {"type": "string"},
            "suggested_title": {"type": "string"},
            "formatted_content": {"type": "string"},
            "suggested_tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["suggested_folder", "suggested_title", "formatted_content", "suggested_tags"],
    }, model=PRO_MODEL, temperature=0.3)

    if result and isinstance(result, dict) and result.get("formatted_content"):
        return {
            "suggested_folder": result.get("suggested_folder", f"Bücher/{book_title}"),
            "suggested_title": result.get("suggested_title", chapter_ref),
            "formatted_content": result["formatted_content"],
            "suggested_tags": result.get("suggested_tags", []),
        }

    # JSON parse failed — fall back
    return await generate_chapter_note(
        book_title=book_title,
        authors=authors,
        chapter=chapter,
        folder_structure=folder_structure,
        existing_tags=existing_tags,
        existing_note_titles=existing_note_titles,
    )
import re
import httpx

settings = get_settings()


# ── Structured output schemas ─────────────────────────────────────────

BOOK_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "title": {"type": "string"},
        "authors": {"type": "array", "items": {"type": "string"}},
        "year": {"type": "integer"},
        "publisher": {"type": "string"},
        "isbn": {"type": "string"},
        "language": {"type": "string"},
        "pages": {"type": "integer"},
        "description": {"type": "string"},
        "category": {"type": "string"},
        "suggestion": {"type": "string"},
    },
    "required": ["found"],
}


async def fetch_book_cover(
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
) -> str | None:
    """Find a public cover image URL for a book.

    Strategy (all key-free public APIs, best-effort — returns None on any failure):
      1. Open Library by ISBN (most reliable when we have an ISBN)
      2. Open Library search by title + author -> cover from the best doc
      3. Google Books volume search -> thumbnail

    Only returns a URL that actually resolves to an image.
    """
    import logging
    logger = logging.getLogger(__name__)

    clean_isbn = re.sub(r"[^0-9Xx]", "", isbn or "") if isbn else ""
    author = (authors[0] if authors else "") or ""

    # The AI often returns a long title with a subtitle ("Main: subtitle"), which
    # rarely matches catalogue records. Search with the short main title too.
    def _short_title(t: str) -> str:
        return re.split(r"[:–—\-]", t, 1)[0].strip() if t else t

    title_variants: list[str] = []
    for t in (title, _short_title(title or "")):
        t = (t or "").strip()
        if t and t not in title_variants:
            title_variants.append(t)

    async def _ol_search(client, t: str, with_author: bool) -> str | None:
        params = {"title": t, "limit": 1, "fields": "cover_i,isbn"}
        if with_author and author:
            params["author"] = author
        r = await client.get("https://openlibrary.org/search.json", params=params)
        if r.status_code != 200:
            return None
        docs = r.json().get("docs", [])
        if not docs:
            return None
        cover_i = docs[0].get("cover_i")
        if cover_i:
            return f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
        isbns = docs[0].get("isbn") or []
        if isbns:
            return f"https://covers.openlibrary.org/b/isbn/{isbns[0]}-L.jpg"
        return None

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        # 1. Open Library by ISBN — use the data API so we only return a real cover.
        if clean_isbn:
            try:
                r = await client.get(
                    "https://openlibrary.org/api/books",
                    params={"bibkeys": f"ISBN:{clean_isbn}", "format": "json", "jscmd": "data"},
                )
                if r.status_code == 200:
                    data = r.json().get(f"ISBN:{clean_isbn}", {})
                    cover = (data.get("cover") or {}).get("large") or (data.get("cover") or {}).get("medium")
                    if cover:
                        return cover
            except Exception as e:
                logger.warning(f"Open Library ISBN cover lookup failed: {e}")

        # 2. Open Library search: full title+author, short title+author, short title only.
        for t in title_variants:
            for with_author in (True, False):
                try:
                    url = await _ol_search(client, t, with_author)
                    if url:
                        return url
                except Exception as e:
                    logger.warning(f"Open Library search cover lookup failed: {e}")

        # 3. Google Books fallback — plain query is more forgiving than intitle/inauthor.
        for t in title_variants:
            try:
                q = f"{t} {author}".strip()
                r = await client.get(
                    "https://www.googleapis.com/books/v1/volumes",
                    params={"q": q, "maxResults": 1},
                )
                if r.status_code == 200:
                    items = r.json().get("items", [])
                    if items:
                        links = items[0].get("volumeInfo", {}).get("imageLinks", {})
                        thumb = links.get("thumbnail") or links.get("smallThumbnail")
                        if thumb:
                            # Google returns http + zoom=1; normalise to https, larger image.
                            return thumb.replace("http://", "https://").replace("&edge=curl", "")
            except Exception as e:
                logger.warning(f"Google Books cover lookup failed: {e}")

    return None


async def _url_is_image(client: "httpx.AsyncClient", url: str) -> bool:
    """Return True if the URL actually serves a real (non-empty) image."""
    try:
        r = await client.get(url, headers={"Range": "bytes=0-2048"})
        if r.status_code not in (200, 206):
            return False
        ctype = r.headers.get("content-type", "")
        if not ctype.startswith("image"):
            return False
        # Open Library placeholder / empty covers are a few bytes; require some size.
        clen = r.headers.get("content-length")
        if clen is not None and int(clen) < 1000:
            return False
        if not clen and len(r.content) < 500:
            return False
        return True
    except Exception:
        return False


async def fetch_cover_candidates(
    title: str | None = None,
    authors: list[str] | None = None,
    isbn: str | None = None,
    limit: int = 12,
) -> list[str]:
    """Return several VERIFIED candidate cover URLs so the user can pick one.

    Uses forgiving free-text search across Open Library (multiple query variants)
    and Google Books, then validates every candidate URL actually serves a real
    image — so the UI never shows blanks/404s and the count is honest.
    """
    import logging
    logger = logging.getLogger(__name__)

    clean_isbn = re.sub(r"[^0-9Xx]", "", isbn or "") if isbn else ""
    author = (authors[0] if authors else "") or ""

    def _short_title(t: str) -> str:
        return re.split(r"[:–—\-]", t, 1)[0].strip() if t else t

    title_variants: list[str] = []
    for t in (title, _short_title(title or "")):
        t = (t or "").strip()
        if t and t not in title_variants:
            title_variants.append(t)

    raw: list[str] = []

    def _add(url: str | None):
        if url and url not in raw:
            raw.append(url)

    # `?default=false` makes Open Library return 404 (not a blank placeholder)
    # for missing covers, so validation can filter them cleanly.
    def _ol_id(cover_i) -> str:
        return f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg?default=false"

    def _ol_isbn(i) -> str:
        return f"https://covers.openlibrary.org/b/isbn/{i}-L.jpg?default=false"

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        if clean_isbn:
            _add(_ol_isbn(clean_isbn))

        # Open Library — free-text `q=` search is far more forgiving than title=.
        # Try: "title author", "title", "shorttitle author", "shorttitle".
        queries: list[str] = []
        for t in title_variants:
            if author:
                queries.append(f"{t} {author}")
            queries.append(t)
        for q in queries:
            if len(raw) >= limit * 2:
                break
            try:
                r = await client.get(
                    "https://openlibrary.org/search.json",
                    params={"q": q, "limit": 8, "fields": "cover_i,isbn"},
                )
                if r.status_code == 200:
                    for doc in r.json().get("docs", []):
                        cover_i = doc.get("cover_i")
                        if cover_i:
                            _add(_ol_id(cover_i))
                        for isbn_c in (doc.get("isbn") or [])[:1]:
                            _add(_ol_isbn(isbn_c))
            except Exception as e:
                logger.warning(f"OL candidates failed: {e}")

        # Google Books — try free query AND intitle/inauthor.
        gb_queries = []
        for t in title_variants:
            gb_queries.append(f"{t} {author}".strip())
            gb_queries.append(f'intitle:{t}' + (f'+inauthor:{author}' if author else ''))
        for q in gb_queries:
            if len(raw) >= limit * 2:
                break
            try:
                r = await client.get(
                    "https://www.googleapis.com/books/v1/volumes",
                    params={"q": q, "maxResults": 8},
                )
                if r.status_code == 200:
                    for item in r.json().get("items", []):
                        links = item.get("volumeInfo", {}).get("imageLinks", {})
                        thumb = links.get("thumbnail") or links.get("smallThumbnail")
                        if thumb:
                            _add(thumb.replace("http://", "https://").replace("&edge=curl", ""))
            except Exception as e:
                logger.warning(f"Google Books candidates failed: {e}")

        # Validate all candidates concurrently — keep only real images.
        results = await asyncio.gather(*[_url_is_image(client, u) for u in raw])
        verified = [u for u, ok in zip(raw, results) if ok]

    return verified[:limit]


BOOK_TOC_SCHEMA = {
    "type": "object",
    "properties": {
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chapter_number": {"type": "string"},
                    "title": {"type": "string"},
                    "level": {"type": "integer"},
                },
                "required": ["chapter_number", "title", "level"],
            },
        },
        "total_chapters": {"type": "integer"},
    },
    "required": ["chapters"],
}


async def search_book(query: str) -> dict:
    """Search for a book using Gemini with Google Search grounding and return structured info."""

    prompt = f"""Suche nach dem Buch: "{query}"

Finde das passendste Buch und gib die Informationen im folgenden JSON-Format zurück.
Antworte NUR mit dem JSON, kein anderer Text:

{{
    "found": true,
    "title": "Vollständiger Buchtitel",
    "authors": ["Autor 1", "Autor 2"],
    "year": 2020,
    "publisher": "Verlag",
    "isbn": "ISBN wenn verfügbar",
    "language": "Deutsch/English/etc",
    "pages": 300,
    "description": "Kurze Beschreibung des Buchs in 2-3 Sätzen",
    "category": "Eine Kategorie aus der Liste unten"
}}

KATEGORIE:
{categories_prompt_block()}

Wenn kein passendes Buch gefunden wird:
{{
    "found": false,
    "suggestion": "Meintest du vielleicht...?"
}}"""

    # Ground the lookup in a real web search first, then structure it.
    research, _sources = await generate_with_search_sources(
        f"Finde bibliografische Daten (Titel, Autoren, Jahr, Verlag, ISBN, Seitenzahl, Kurzbeschreibung) zum Buch: {query}",
        model=PRO_MODEL,
    )
    structured_prompt = prompt
    if research:
        structured_prompt += f"\n\nRECHERCHE-ERGEBNIS:\n{research[:2500]}"

    async def _attach_cover(book: dict) -> dict:
        """Enrich a found book with a cover image URL + normalised category."""
        if book.get("found"):
            book["category"] = normalize_category(book.get("category"))
            if not book.get("cover_url"):
                cover = await fetch_book_cover(
                    title=book.get("title"),
                    authors=book.get("authors"),
                    isbn=book.get("isbn"),
                )
                if cover:
                    book["cover_url"] = cover
        return book

    result = await generate_json(structured_prompt, BOOK_SEARCH_SCHEMA, model=PRO_MODEL, temperature=0.2)
    if result and isinstance(result, dict):
        return await _attach_cover(result)

    # Fallback: legacy free-text + regex
    text = (await generate_with_search(prompt, model=PRO_MODEL)).strip()
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return await _attach_cover(json.loads(json_match.group()))
        except json.JSONDecodeError:
            pass

    return {"found": False, "suggestion": "Konnte kein passendes Buch finden."}


async def get_book_toc(book_title: str, authors: list[str]) -> dict:
    """Get the full table of contents for a book using Gemini with grounding."""

    authors_str = ", ".join(authors)

    prompt = f"""Erstelle das vollständige Inhaltsverzeichnis für das Buch:
"{book_title}" von {authors_str}

Gib das Inhaltsverzeichnis als JSON zurück. Jeder Eintrag hat:
- "title": Kapitelname
- "level": Verschachtelungstiefe (1 = Hauptkapitel, 2 = Unterkapitel, 3 = Unterunterkapitel)
- "chapter_number": Kapitelnummer als String (z.B. "1", "1.1", "1.1.1")

Antworte NUR mit dem JSON:
{{
    "chapters": [
        {{"chapter_number": "1", "title": "Einleitung", "level": 1}},
        {{"chapter_number": "1.1", "title": "Unterkapitel", "level": 2}},
        {{"chapter_number": "2", "title": "Nächstes Kapitel", "level": 1}}
    ],
    "total_chapters": 25
}}

WICHTIG: Gib ALLE Kapitel, Unterkapitel und Unterunterkapitel an, nicht nur die Hauptkapitel.
Sei so vollständig wie möglich basierend auf dem tatsächlichen Inhaltsverzeichnis des Buches.

Lasse folgende Einträge KOMPLETT WEG (sie haben keinen inhaltlichen Mehrwert):
- Präambel, Vorwort, Geleitwort, Danksagung, Widmung
- Titelseite, Impressum, Copyright, Half Title, Title Card, Cover
- Preface, Foreword, Acknowledgements, Dedication
- Inhaltsverzeichnis, Abbildungsverzeichnis, Tabellenverzeichnis
- Table of Contents, List of Figures, List of Tables, List of Abbreviations
- Index, Stichwortverzeichnis, Register
- Glossar, Abkürzungsverzeichnis, Glossary
- Literaturverzeichnis, Quellenverzeichnis, Bibliografie, Bibliography, References
- Anhang, Appendix, Colophon
- Nachwort, Endwort, Schlusswort, Afterword
- Über den Autor, About the Author, Front Matter, Back Matter

Nur inhaltliche Kapitel mit echtem Lerninhalt sollen aufgelistet werden."""

    # Ground the TOC in real search, then structure it strictly.
    research, _sources = await generate_with_search_sources(
        f"Suche das vollständige, exakte Inhaltsverzeichnis (alle Kapitel und Unterkapitel mit Nummern) "
        f"des Buches \"{book_title}\" von {authors_str}.",
        model=PRO_MODEL,
    )
    structured_prompt = prompt
    if research:
        structured_prompt += f"\n\nRECHERCHIERTES INHALTSVERZEICHNIS:\n{research[:6000]}"

    result = await generate_json(structured_prompt, BOOK_TOC_SCHEMA, model=PRO_MODEL, temperature=0.2)
    if result and isinstance(result, dict) and result.get("chapters"):
        result.setdefault("total_chapters", len(result["chapters"]))
        return result

    # Fallback: legacy free-text + regex
    text = (await generate_with_search(prompt, model=PRO_MODEL)).strip()
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return {"chapters": [], "total_chapters": 0}


async def generate_chapter_note(
    book_title: str,
    authors: list[str],
    chapter: dict,
    folder_structure: list[dict],
    existing_tags: list[str] = None,
    custom_prompt: str = None,
    existing_note_titles: list[str] | None = None,
) -> dict:
    """Generate a structured note for a specific book chapter."""

    authors_str = ", ".join(authors)
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    chapter_ref = f"Kapitel {chapter['chapter_number']}: {chapter['title']}"

    # Build deduplication context
    dedup_block = ""
    if existing_note_titles:
        titles_list = "\n".join(f"- {t}" for t in existing_note_titles)
        dedup_block = f"""
BEREITS EXISTIERENDE NOTIZEN zu diesem Buch (aus vorherigen Kapiteln):
{titles_list}

WICHTIGE REGEL ZUR VERMEIDUNG VON DUPLIKATEN:
- Wiederhole KEINE Inhalte, die in den oben genannten Notizen bereits behandelt wurden.
- Wenn ein Konzept bereits als Notiz existiert, verweise kurz darauf statt es erneut zu erklären.
- Verwende ANDERE Beispiele als in vorherigen Kapiteln — bringe frische, kapitelspezifische Beispiele.
"""

    prompt = f"""Du bist ein Second Brain Assistent. Erstelle eine ausführliche, gut strukturierte Notiz 
für das folgende Buchkapitel:

Buch: "{book_title}" von {authors_str}
Kapitel: {chapter_ref}
{dedup_block}

Erstelle die Notiz im folgenden JSON-Format (NUR das JSON, kein anderer Text):
{{
    "suggested_folder": "Bücher/{book_title}",
    "suggested_title": "{chapter_ref}",
    "formatted_content": "Der formatierte Inhalt der Notiz in Markdown",
    "suggested_tags": ["tag1", "tag2"]
}}

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen. Erstelle neue nur wenn nötig.

Formatierungsregeln für formatted_content (sehr wichtig!):
- Beginne mit einer kurzen Einordnung: Aus welchem Buch, welches Kapitel
- Strukturiere den Inhalt gut mit Markdown-Headings (##, ###)
- Verwende **Fettdruck** für Schlüsselbegriffe
- Verwende Aufzählungslisten für Hierarchien
- Verwende Callouts für wichtige Konzepte:
  > [!MERKSATZ]
  > Für Kernaussagen
  
  > [!BEISPIEL]
  > Für konkrete Beispiele aus dem Buch
  
  > [!DEFINITION]
  > Für Begriffserklärungen

- Fasse die WESENTLICHEN Inhalte des Kapitels zusammen — nicht nur Überschriften
- Schreibe sachlich, klar und informativ in neutraler Form
- Die Notiz soll wie eine gute Zusammenfassung sein, die man zum Lernen nutzen kann
- Schreibe in der Sprache des Buches"""

    text = (await generate_with_search(prompt, model=PRO_MODEL)).strip()

    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            result = json.loads(json_match.group())
            return {
                "suggested_folder": result.get("suggested_folder", f"Bücher/{book_title}"),
                "suggested_title": result.get("suggested_title", chapter_ref),
                "formatted_content": result.get("formatted_content", ""),
                "suggested_tags": result.get("suggested_tags", []),
            }
        except json.JSONDecodeError:
            pass

    return {
        "suggested_folder": f"Bücher/{book_title}",
        "suggested_title": chapter_ref,
        "formatted_content": f"Fehler beim Generieren der Notiz für {chapter_ref}.",
        "suggested_tags": [],
    }


async def generate_topic_note(
    topic: str,
    book_title: str,
    authors: list[str],
    existing_tags: list[str] = None,
) -> dict:
    """Generate a note for an arbitrary topic in the context of a book."""

    authors_str = ", ".join(authors)
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    prompt = f"""Du bist ein Second Brain Assistent. Erstelle eine ausführliche, gut strukturierte Notiz
zum folgenden Thema, das im Kontext des Buches "{book_title}" von {authors_str} relevant ist:

Thema: {topic}

Die Notiz soll das Thema allgemein und umfassend behandeln — nicht nur im Buchkontext, 
sondern als eigenständige Wissensnotiz, die auch ohne das Buch nützlich ist.

Erstelle die Notiz im folgenden JSON-Format (NUR das JSON, kein anderer Text):
{{
    "suggested_folder": "Bücher/{book_title}/Themen",
    "suggested_title": "{topic}",
    "formatted_content": "Der formatierte Inhalt der Notiz in Markdown",
    "suggested_tags": ["tag1", "tag2"]
}}

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen. Erstelle neue nur wenn nötig.

Formatierungsregeln für formatted_content (sehr wichtig!):
- Beginne mit einer kurzen Einordnung: Was ist {topic} und warum ist es relevant
- Strukturiere den Inhalt gut mit Markdown-Headings (##, ###)
- Verwende **Fettdruck** für Schlüsselbegriffe
- Verwende Aufzählungslisten für Hierarchien
- Verwende Callouts für wichtige Konzepte:
  > [!MERKSATZ]
  > Für Kernaussagen
  
  > [!DEFINITION]
  > Für Begriffserklärungen
  
  > [!BEISPIEL]
  > Für konkrete Beispiele

- Schreibe sachlich, klar und informativ in neutraler Form
- Die Notiz soll wie ein guter Lexikon-/Wikipedia-Eintrag sein, den man zum Lernen nutzen kann
- Schreibe in der Sprache des Buches"""

    text = (await generate_with_search(prompt)).strip()

    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            result = json.loads(json_match.group())
            return {
                "suggested_folder": result.get("suggested_folder", f"Bücher/{book_title}/Themen"),
                "suggested_title": result.get("suggested_title", topic),
                "formatted_content": result.get("formatted_content", ""),
                "suggested_tags": result.get("suggested_tags", []),
            }
        except json.JSONDecodeError:
            pass

    return {
        "suggested_folder": f"Bücher/{book_title}/Themen",
        "suggested_title": topic,
        "formatted_content": f"Fehler beim Generieren der Notiz für {topic}.",
        "suggested_tags": [],
    }


async def ai_edit_book_content(current_content: str, instruction: str) -> str:
    """Edit book-generated content based on an instruction (no note_id needed)."""

    prompt = f"""Du bist ein Second Brain Assistent. Bearbeite die folgende Notiz basierend auf der Anweisung.

AKTUELLE NOTIZ:
{current_content}

ANWEISUNG: {instruction}

Gib NUR den neuen, vollständigen Notiz-Inhalt zurück (Markdown). Kein JSON, keine Erklärung, nur der Inhalt."""

    return (await generate(prompt, model=PRO_MODEL)).strip()


async def generate_chapter_summary(
    book_title: str,
    authors: list[str],
    chapter_number: str,
    chapter_title: str,
    chat_history: list[dict] | None = None,
) -> str:
    """Generate a rich chapter summary from chat history or AI knowledge.

    If chat_history is provided, the summary is based on what was actually discussed.
    Otherwise, AI generates a summary from its own knowledge + Google Search.
    """
    authors_str = ", ".join(authors) if authors else "Unbekannt"

    if chat_history and len([m for m in chat_history if m.get("role") in ("user", "assistant")]) >= 2:
        # Build summary from actual conversation
        conversation_text = "\n".join(
            f"{'Tutor' if m['role'] == 'assistant' else 'Lerner'}: {m['content']}"
            for m in chat_history
            if m.get("role") in ("user", "assistant")
        )
        # Truncate if very long
        if len(conversation_text) > 15000:
            conversation_text = conversation_text[:15000] + "\n... (gekürzt)"

        prompt = f"""Du bist ein Second Brain Assistent. Erstelle eine hochwertige, gut strukturierte Zusammenfassung
für das Buchkapitel basierend auf der folgenden Lern-Konversation.

Buch: "{book_title}" von {authors_str}
Kapitel {chapter_number}: {chapter_title}

KONVERSATION:
{conversation_text}

AUFGABE: Erstelle eine Zusammenfassung, die:
1. Die Kernkonzepte und Hauptaussagen des Kapitels klar darstellt
2. Gut mit Markdown strukturiert ist (##, ###, Listen, **Fettdruck**)
3. Callouts für wichtige Merksätze verwendet:
   > [!MERKSATZ]
   > Kernaussage hier
   
   > [!DEFINITION]
   > Begriffserklärung hier
   
   > [!BEISPIEL]
   > Konkretes Beispiel hier

4. Leicht zu scannen ist — man soll auf einen Blick die Hauptpunkte erfassen können
5. Wie eine gute Vorlesungsmitschrift aufgebaut ist: Übersicht → Details → Kernerkenntnisse
6. In der Sprache des Buches geschrieben ist

Gib NUR den Markdown-Inhalt zurück, kein JSON, keine Erklärung.
Beginne NICHT mit dem Kapiteltitel als Heading (der wird separat angezeigt)."""

        response_text = await generate(prompt, model=PRO_MODEL)
    else:
        # No chat history — generate from AI knowledge
        prompt = f"""Du bist ein Second Brain Assistent. Erstelle eine hochwertige, gut strukturierte Zusammenfassung
für das folgende Buchkapitel:

Buch: "{book_title}" von {authors_str}
Kapitel {chapter_number}: {chapter_title}

AUFGABE: Erstelle eine Zusammenfassung, die:
1. Die Kernkonzepte und Hauptaussagen des Kapitels klar darstellt
2. Gut mit Markdown strukturiert ist (##, ###, Listen, **Fettdruck**)
3. Callouts für wichtige Merksätze verwendet:
   > [!MERKSATZ]
   > Kernaussage hier
   
   > [!DEFINITION]
   > Begriffserklärung hier
   
   > [!BEISPIEL]
   > Konkretes Beispiel hier

4. Leicht zu scannen ist — man soll auf einen Blick die Hauptpunkte erfassen können
5. Wie eine gute Vorlesungsmitschrift aufgebaut ist: Übersicht → Details → Kernerkenntnisse
6. In der Sprache des Buches geschrieben ist

Gib NUR den Markdown-Inhalt zurück, kein JSON, keine Erklärung.
Beginne NICHT mit dem Kapiteltitel als Heading (der wird separat angezeigt)."""

        response_text = await generate_with_search(prompt, model=PRO_MODEL)

    return response_text.strip()
