"""Book processing service — search, TOC extraction, chapter note generation, topic deep-dive."""

import google.generativeai as genai
from google.ai.generativelanguage_v1beta import types as glm_types
from app.services.ai_service import get_gemini_model, DEFAULT_NOTE_PROMPT
from app.config import get_settings
import asyncio
import json
import re

# Google Search grounding tool (google_search_retrieval is deprecated)
GOOGLE_SEARCH_TOOL = glm_types.Tool(google_search=glm_types.Tool.GoogleSearch())

settings = get_settings()


async def search_book(query: str) -> dict:
    """Search for a book using Gemini with Google Search grounding and return structured info."""
    model = get_gemini_model()

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

    response = await asyncio.to_thread(model.generate_content, prompt, tools=[GOOGLE_SEARCH_TOOL])
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

    response = await asyncio.to_thread(model.generate_content, prompt, tools=[GOOGLE_SEARCH_TOOL])
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

    response = await asyncio.to_thread(model.generate_content, prompt, tools=[GOOGLE_SEARCH_TOOL])
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


async def generate_topic_note(
    topic: str,
    book_title: str,
    authors: list[str],
    existing_tags: list[str] = None,
) -> dict:
    """Generate a note for an arbitrary topic in the context of a book."""
    model = get_gemini_model()

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

    response = await asyncio.to_thread(model.generate_content, prompt, tools=[GOOGLE_SEARCH_TOOL])
    text = response.text.strip()

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
    model = get_gemini_model()

    prompt = f"""Du bist ein Second Brain Assistent. Bearbeite die folgende Notiz basierend auf der Anweisung.

AKTUELLE NOTIZ:
{current_content}

ANWEISUNG: {instruction}

Gib NUR den neuen, vollständigen Notiz-Inhalt zurück (Markdown). Kein JSON, keine Erklärung, nur der Inhalt."""

    response = await asyncio.to_thread(model.generate_content, prompt)
    return response.text.strip()


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
    model = get_gemini_model()
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

        response = await asyncio.to_thread(model.generate_content, prompt)
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

        response = await asyncio.to_thread(model.generate_content, prompt, tools=[GOOGLE_SEARCH_TOOL])

    return response.text.strip()
