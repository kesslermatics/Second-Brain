"""Book processing service — search, TOC extraction, chapter note generation, topic deep-dive."""

from app.services.ai_service import (
    generate_with_search, generate, generate_stream, generate_with_search_stream,
    generate_json, generate_with_search_sources, PRO_MODEL, FLASH_MODEL, DEFAULT_NOTE_PROMPT,
)
from app.config import get_settings
import json
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

        # 2. Open Library search by title + author.
        if title:
            try:
                r = await client.get(
                    "https://openlibrary.org/search.json",
                    params={"title": title, "author": author, "limit": 1, "fields": "cover_i,isbn"},
                )
                if r.status_code == 200:
                    docs = r.json().get("docs", [])
                    if docs:
                        cover_i = docs[0].get("cover_i")
                        if cover_i:
                            return f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
                        isbns = docs[0].get("isbn") or []
                        if isbns:
                            return f"https://covers.openlibrary.org/b/isbn/{isbns[0]}-L.jpg"
            except Exception as e:
                logger.warning(f"Open Library search cover lookup failed: {e}")

        # 3. Google Books fallback.
        if title:
            try:
                q = f'intitle:{title}'
                if author:
                    q += f'+inauthor:{author}'
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
                            # Google returns http + zoom=1; normalise to https and a larger image.
                            return thumb.replace("http://", "https://").replace("&edge=curl", "")
            except Exception as e:
                logger.warning(f"Google Books cover lookup failed: {e}")

    return None

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
    "description": "Kurze Beschreibung des Buchs in 2-3 Sätzen"
}}

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
        """Enrich a found book with a public cover image URL (best-effort)."""
        if book.get("found") and not book.get("cover_url"):
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
- Präambel, Vorwort, Geleitwort, Danksagung
- Inhaltsverzeichnis, Abbildungsverzeichnis, Tabellenverzeichnis
- Index, Stichwortverzeichnis, Register
- Glossar, Abkürzungsverzeichnis
- Literaturverzeichnis, Quellenverzeichnis, Bibliografie
- Anhang, Appendix
- Nachwort, Endwort, Schlusswort
- Über den Autor, About the Author

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
