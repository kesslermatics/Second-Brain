"""
AI Service — shared Gemini client and utility functions for all AI features.
Uses the new google-genai SDK.
"""

from google import genai
from google.genai import types
from app.config import get_settings
from typing import AsyncGenerator
import asyncio
import json
import re

settings = get_settings()

# ── Shared client (singleton) ─────────────────────────────────────────

_client: genai.Client | None = None


def get_client() -> genai.Client:
    """Get or create the shared Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


# ── Model constants ───────────────────────────────────────────────────

FLASH_MODEL = "gemini-3-flash-preview"
PRO_MODEL = "gemini-3.1-pro-preview"


async def generate(prompt: str, model: str = None, system_instruction: str = None, temperature: float = None, tools=None) -> str:
    """Generate content using the new SDK. Async-native."""
    client = get_client()
    model_name = model or FLASH_MODEL

    config = types.GenerateContentConfig()
    if system_instruction:
        config.system_instruction = system_instruction
    if temperature is not None:
        config.temperature = temperature
    if tools:
        config.tools = tools

    response = await client.aio.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )
    return response.text


async def generate_stream(
    prompt: str,
    model: str = None,
    system_instruction: str = None,
    temperature: float = None,
    tools=None,
) -> AsyncGenerator[dict, None]:
    """
    Stream content generation. Yields events:
    - {"type": "thinking", "content": "..."} — thought summaries (Pro model)
    - {"type": "chunk", "content": "..."} — response text chunks
    - {"type": "done"} — stream finished
    """
    client = get_client()
    model_name = model or FLASH_MODEL

    config = types.GenerateContentConfig()
    if system_instruction:
        config.system_instruction = system_instruction
    if temperature is not None:
        config.temperature = temperature
    if tools:
        config.tools = tools

    async for chunk in await client.aio.models.generate_content_stream(
        model=model_name,
        contents=prompt,
        config=config,
    ):
        # Handle thinking (thought parts in candidates)
        if chunk.candidates:
            for candidate in chunk.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'thought') and part.thought:
                            yield {"type": "thinking", "content": part.text or ""}

        # Handle text chunks
        if chunk.text:
            yield {"type": "chunk", "content": chunk.text}

    yield {"type": "done"}


async def generate_with_search(prompt: str, model: str = None, system_instruction: str = None) -> str:
    """Generate content with Google Search grounding enabled."""
    client = get_client()
    model_name = model or FLASH_MODEL

    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )
    if system_instruction:
        config.system_instruction = system_instruction

    response = await client.aio.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )
    return response.text


async def generate_with_search_stream(
    prompt: str,
    model: str = None,
    system_instruction: str = None,
) -> AsyncGenerator[dict, None]:
    """Stream content with Google Search grounding. Same event format as generate_stream."""
    client = get_client()
    model_name = model or FLASH_MODEL

    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )
    if system_instruction:
        config.system_instruction = system_instruction

    async for chunk in await client.aio.models.generate_content_stream(
        model=model_name,
        contents=prompt,
        config=config,
    ):
        if chunk.candidates:
            for candidate in chunk.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'thought') and part.thought:
                            yield {"type": "thinking", "content": part.text or ""}

        if chunk.text:
            yield {"type": "chunk", "content": chunk.text}

    yield {"type": "done"}


# ── Default Prompt Templates ──────────────────────────────────────────
# Placeholders: {{ORDNERSTRUKTUR}}, {{BENUTZEREINGABE}}
DEFAULT_NOTE_PROMPT = """Du bist ein Second Brain Assistent. Der Benutzer gibt dir Notizen oder Informationen, 
und du sollst diese strukturiert aufbereiten und vorschlagen, wo sie in der vorhandenen Ordnerstruktur 
gespeichert werden sollen.

Aktuelle Ordnerstruktur:
{{ORDNERSTRUKTUR}}

Benutzereingabe:
{{BENUTZEREINGABE}}

Bitte antworte im folgenden JSON-Format (NUR das JSON, kein anderer Text):
{
    "suggested_folder": "pfad/zum/ordner",
    "suggested_title": "Titel der Notiz",
    "formatted_content": "Der formatierte Inhalt der Notiz in Markdown"
}

Regeln:
- Wenn ein passender Ordner existiert, verwende diesen
- Wenn kein passender Ordner existiert, schlage einen neuen Pfad vor
- Der Titel soll kurz und beschreibend sein
- Schreibe den Inhalt in der Sprache der Benutzereingabe

Formatierungsregeln für formatted_content (sehr wichtig!):
- Strukturiere den Inhalt gut mit Markdown-Headings (##, ###)
- Verwende **Fettdruck** für Schlüsselbegriffe und *Kursiv* für Betonungen
- Verwende Aufzählungslisten und verschachtelte Listen für Hierarchien
- Verwende Tabellen (| Spalte 1 | Spalte 2 |) für Vergleiche und Übersichten
- Verwende Admonitions/Callouts im folgenden Format für besondere Inhalte:
  > [!MERKSATZ]
  > Für wichtige Zitate oder Kernaussagen

  > [!TIPP]
  > Für praktische Tipps und Anwendungshinweise

  > [!WICHTIG]
  > Für kritische Informationen die man sich merken muss

  > [!DEFINITION]
  > Für Begriffserklärungen und Definitionen
  
  > [!BEISPIEL]
  > Für konkrete Beispiele

  > [!WARNUNG]
  > Für häufige Fehler oder Missverständnisse

- Verwende Code-Blöcke (```) nur wenn tatsächlich Code, Formeln oder technische Inhalte vorkommen
- Trenne logische Abschnitte mit horizontalen Linien (---) wenn sinnvoll
- Mache KEINEN Blocktext — nutze viele Absätze, Listen und die oben genannten Blöcke
- Die Notiz soll visuell ansprechend und leicht scanbar sein
- Schreibe die Notiz IMMER in neutraler Form — sachlich, klar und informativ. Vermeide die Ich-Form."""

# Placeholders: {{KONTEXT}}, {{CHATVERLAUF}}, {{FRAGE}}
DEFAULT_RAG_PROMPT = """Du bist ein intelligenter Second Brain Assistent. Beantworte die Frage des Benutzers 
basierend auf den folgenden Notizen aus seinem Second Brain. Wenn die Notizen nicht ausreichen, 
um die Frage vollständig zu beantworten, sage das ehrlich und gib trotzdem dein Bestes.

Relevante Notizen aus dem Second Brain:
{{KONTEXT}}

{{CHATVERLAUF}}

Aktuelle Frage: {{FRAGE}}

Bitte antworte:
- Strukturiert und klar
- Mit Bezug auf die Quellen wenn möglich
- In der Sprache der Frage
- Nutze Markdown für Formatierung"""

# Placeholders: {{AKTUELLE_NOTIZ}}, {{ANWEISUNG}}
DEFAULT_EDIT_PROMPT = """Du bist ein Notiz-Editor. Bearbeite die folgende Notiz gemäß der Anweisung des Benutzers.
Gib NUR den bearbeiteten Inhalt zurück, keinen anderen Text.

Aktuelle Notiz:
{{AKTUELLE_NOTIZ}}

Anweisung: {{ANWEISUNG}}

Bearbeitete Notiz:"""


def get_default_prompts() -> dict:
    """Return all default prompt templates."""
    return {
        "note_prompt": DEFAULT_NOTE_PROMPT,
        "qa_prompt": DEFAULT_RAG_PROMPT,
        "edit_prompt": DEFAULT_EDIT_PROMPT,
    }


async def process_note_input(user_input: str, folder_structure: list[dict], custom_prompt: str = None, existing_tags: list[str] = None) -> dict:
    """Process user input and suggest where to save it as a note."""
    folder_tree_str = json.dumps(folder_structure, indent=2, default=str)

    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"
    tags_instruction = f"""\n\nBestehende Tags im System: {tags_str}

Füge dem JSON-Ergebnis ein Feld "suggested_tags" hinzu — ein Array von 2-5 passenden Tags.
Bevorzuge bestehende Tags wenn sie passen (exakt gleicher Name). Erstelle neue Tags nur wenn nötig.
Verwende Kleinbuchstaben und Bindestriche statt Leerzeichen.
Beispiel: "suggested_tags": ["python", "machine-learning", "tutorial"]"""

    prompt_template = custom_prompt or DEFAULT_NOTE_PROMPT
    prompt = (
        prompt_template
        .replace("{{ORDNERSTRUKTUR}}", folder_tree_str)
        .replace("{{BENUTZEREINGABE}}", user_input)
    ) + tags_instruction

    text = (await generate(prompt, temperature=0.4)).strip()

    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        text = json_match.group()

    try:
        result = json.loads(text)
        return {
            "suggested_folder": result.get("suggested_folder", ""),
            "suggested_title": result.get("suggested_title", ""),
            "formatted_content": result.get("formatted_content", ""),
            "suggested_tags": result.get("suggested_tags", []),
        }
    except json.JSONDecodeError:
        return {
            "suggested_folder": "",
            "suggested_title": "Neue Notiz",
            "formatted_content": user_input,
            "suggested_tags": [],
        }


async def answer_with_rag(question: str, context_notes: list[dict], chat_history: list[dict] = None, custom_prompt: str = None) -> str:
    """Answer a question using RAG context. Uses Pro model for quality."""
    context_str = ""
    for note in context_notes:
        context_str += f"\n--- Notiz: {note['title']} (Pfad: {note['folder_path']}) ---\n"
        context_str += f"{note['content_preview']}\n"

    history_str = ""
    if chat_history:
        for msg in chat_history[-10:]:
            role = "Benutzer" if msg["role"] == "user" else "Assistent"
            history_str += f"{role}: {msg['content']}\n"

    chat_history_block = f"Bisheriger Chatverlauf:\n{history_str}" if history_str else ""

    prompt_template = custom_prompt or DEFAULT_RAG_PROMPT
    prompt = (
        prompt_template
        .replace("{{KONTEXT}}", context_str)
        .replace("{{CHATVERLAUF}}", chat_history_block)
        .replace("{{FRAGE}}", question)
    )

    return await generate(prompt, model=PRO_MODEL)


async def edit_note_with_ai(current_content: str, instruction: str, custom_prompt: str = None) -> str:
    """Edit a note based on AI instruction."""
    prompt_template = custom_prompt or DEFAULT_EDIT_PROMPT
    prompt = (
        prompt_template
        .replace("{{AKTUELLE_NOTIZ}}", current_content)
        .replace("{{ANWEISUNG}}", instruction)
    )

    return (await generate(prompt)).strip()


# ── AI: Tag suggestion ────────────────────────────────────────────────

async def suggest_tags(title: str, content: str, existing_tags: list[str]) -> list[str]:
    """Suggest tags for a note, preferring existing tags to avoid duplicates."""
    existing_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    prompt = f"""Du bist ein Tag-Generator für ein Second Brain System.
Analysiere die folgende Notiz und schlage 2-5 passende Tags vor.

WICHTIG: Bevorzuge Tags aus der bestehenden Tag-Liste, um Duplikate zu vermeiden!
Verwende Kleinbuchstaben, keine Leerzeichen (nutze Bindestriche statt Leerzeichen).

Bestehende Tags: {existing_str}

Notiz-Titel: {title}
Notiz-Inhalt (Auszug): {content[:1500]}

Antworte NUR mit einem JSON-Array von Strings, z.B.: ["tag1", "tag2", "tag3"]"""

    text = (await generate(prompt, temperature=0.3)).strip()

    json_match = re.search(r'\[[\s\S]*?\]', text)
    if json_match:
        try:
            tags = json.loads(json_match.group())
            return [str(t).lower().strip() for t in tags if isinstance(t, str)]
        except json.JSONDecodeError:
            pass
    return []


# ── AI: Flashcard generation ──────────────────────────────────────────

async def generate_flashcards(title: str, content: str, max_cards: int = 5) -> list[dict]:
    """Generate question-answer flashcards from a note."""
    prompt = f"""Du bist ein Lernkarten-Generator. Erstelle aus der folgenden Notiz {max_cards} Lernkarten 
im Frage-Antwort-Format. Die Fragen sollen das Verständnis der Kernkonzepte testen.

Notiz-Titel: {title}
Notiz-Inhalt:
{content[:3000]}

Antworte NUR mit einem JSON-Array:
[
    {{"question": "Frage 1?", "answer": "Antwort 1"}},
    {{"question": "Frage 2?", "answer": "Antwort 2"}}
]"""

    text = (await generate(prompt, temperature=0.5)).strip()

    json_match = re.search(r'\[[\s\S]*\]', text)
    if json_match:
        try:
            cards = json.loads(json_match.group())
            return [
                {"question": c.get("question", ""), "answer": c.get("answer", "")}
                for c in cards
                if isinstance(c, dict) and c.get("question") and c.get("answer")
            ]
        except json.JSONDecodeError:
            pass
    return []


# ── AI: Link suggestion (find related notes) ─────────────────────────

async def suggest_links(note_title: str, note_content: str, candidate_notes: list[dict]) -> list[str]:
    """Suggest which candidate notes are semantically related to the given note."""
    candidates_str = "\n".join(
        f"- ID: {c['id']}, Titel: {c['title']}, Auszug: {c['preview'][:200]}"
        for c in candidate_notes
    )

    prompt = f"""Analysiere die Hauptnotiz und die Kandidaten. Welche Kandidaten sind inhaltlich verwandt?
Antworte NUR mit einem JSON-Array der IDs der verwandten Notizen, z.B.: ["id1", "id2"]
Wähle nur wirklich zusammenhängende Notizen (max 5). Bei keinem Zusammenhang: []

Hauptnotiz:
Titel: {note_title}
Inhalt (Auszug): {note_content[:1000]}

Kandidaten:
{candidates_str}"""

    text = (await generate(prompt, temperature=0.2)).strip()

    json_match = re.search(r'\[[\s\S]*?\]', text)
    if json_match:
        try:
            ids = json.loads(json_match.group())
            return [str(i) for i in ids]
        except json.JSONDecodeError:
            pass
    return []


# ── AI: Chat title ────────────────────────────────────────────────────

async def generate_chat_title(first_message: str) -> str:
    """Generate a short, descriptive chat title from the first user message."""
    prompt = f"""Erstelle einen sehr kurzen Titel (max 5 Wörter) für eine Chat-Konversation, 
die mit folgender Nachricht beginnt. Der Titel soll den Kern der Anfrage zusammenfassen.
Antworte NUR mit dem Titel, ohne Anführungszeichen oder zusätzlichen Text.

Nachricht: {first_message[:500]}

Titel:"""

    try:
        title = (await generate(prompt, temperature=0.3)).strip().strip('"\'')
        if len(title) > 60:
            title = title[:57] + "..."
        return title or first_message[:50]
    except Exception:
        return first_message[:50] + ("..." if len(first_message) > 50 else "")


# ── AI: Summarization ─────────────────────────────────────────────────

async def generate_summary(notes: list[dict], scope_label: str) -> str:
    """Generate a summary across multiple notes."""
    notes_str = ""
    for n in notes[:20]:
        notes_str += f"\n### {n['title']}\n{n['content'][:500]}\n"

    prompt = f"""Du bist ein Second Brain Assistent. Erstelle eine umfassende Zusammenfassung 
aller folgenden Notizen aus dem Bereich "{scope_label}".

Die Zusammenfassung soll:
- Die wichtigsten Themen und Erkenntnisse hervorheben
- Verbindungen zwischen den Notizen aufzeigen
- Gut strukturiert und in Markdown formatiert sein
- Praktische Schlussfolgerungen enthalten

Notizen:
{notes_str}

Zusammenfassung:"""

    return await generate(prompt, model=PRO_MODEL)
