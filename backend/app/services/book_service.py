"""Book processing service — search, TOC extraction, chapter note generation."""

import google.generativeai as genai
from app.services.ai_service import get_gemini_model, DEFAULT_NOTE_PROMPT
from app.config import get_settings
import json
import re

settings = get_settings()


async def search_book(query: str) -> dict:
    """Search for a book using Gemini with Google Search grounding and return structured info."""
    model = get_gemini_model()

    # Use Google Search grounding to find accurate book info
    search_tool = genai.protos.Tool(
        google_search_retrieval=genai.protos.GoogleSearchRetrieval()
    )

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

    response = model.generate_content(prompt, tools=[search_tool])
    text = response.text.strip()

    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return {"found": False, "suggestion": "Konnte kein passendes Buch finden."}


async def get_book_toc(book_title: str, authors: list[str]) -> dict:
    """Get the full table of contents for a book using Gemini with grounding."""
    model = get_gemini_model()

    search_tool = genai.protos.Tool(
        google_search_retrieval=genai.protos.GoogleSearchRetrieval()
    )

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
Sei so vollständig wie möglich basierend auf dem tatsächlichen Inhaltsverzeichnis des Buches."""

    response = model.generate_content(prompt, tools=[search_tool])
    text = response.text.strip()

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
) -> dict:
    """Generate a structured note for a specific book chapter."""
    model = get_gemini_model()

    authors_str = ", ".join(authors)
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    # Use grounding to get accurate chapter content
    search_tool = genai.protos.Tool(
        google_search_retrieval=genai.protos.GoogleSearchRetrieval()
    )

    chapter_ref = f"Kapitel {chapter['chapter_number']}: {chapter['title']}"

    prompt = f"""Du bist ein Second Brain Assistent. Erstelle eine ausführliche, gut strukturierte Notiz 
für das folgende Buchkapitel:

Buch: "{book_title}" von {authors_str}
Kapitel: {chapter_ref}

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

    response = model.generate_content(prompt, tools=[search_tool])
    text = response.text.strip()

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
