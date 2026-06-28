"""
Agentic Workspace Service — executes multi-step AI plans over the user's notes.

The agent operates in a loop:
1. Receives user instruction + context (folder structure, recent notes, etc.)
2. Decides which "tools" to call (search, read, create, update, delete)
3. Executes tools, accumulates results
4. Produces a final list of "proposals" (changes to be applied)

The frontend can then show these proposals as diffs and let the user accept/reject.
"""

import json
import re
import asyncio
from typing import Optional
from uuid import UUID

import google.generativeai as genai
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.models import Note, Folder, Tag, note_tags
from app.services.vector_service import hybrid_search

settings = get_settings()
_genai_configured = False


def _ensure_genai():
    global _genai_configured
    if not _genai_configured:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _genai_configured = True


def _get_model():
    _ensure_genai()
    return genai.GenerativeModel("gemini-2.5-flash-preview-05-20")


async def _generate(model, prompt: str) -> str:
    response = await asyncio.to_thread(model.generate_content, prompt)
    return response.text


# ── Tool implementations ──────────────────────────────────────────────

async def _tool_search(query: str, user_id: str, db: AsyncSession, limit: int = 10) -> list[dict]:
    """Semantic + full-text search over all notes."""
    results = await hybrid_search(query=query, user_id=user_id, db=db, limit=limit)
    return [
        {
            "note_id": r["note_id"],
            "title": r["title"],
            "folder_path": r["folder_path"],
            "preview": r["content_preview"][:500],
            "score": r["score"],
        }
        for r in results
    ]


async def _tool_read_note(note_id: str, user_id: str, db: AsyncSession) -> Optional[dict]:
    """Read full content of a specific note."""
    try:
        note = await db.get(Note, UUID(note_id))
    except (ValueError, TypeError):
        return None
    if not note or str(note.user_id) != user_id:
        return None
    folder = await db.get(Folder, note.folder_id)
    # Get tags
    tag_result = await db.execute(
        select(Tag.name)
        .join(note_tags, Tag.id == note_tags.c.tag_id)
        .where(note_tags.c.note_id == note.id)
    )
    tag_names = [row[0] for row in tag_result.all()]
    return {
        "note_id": str(note.id),
        "title": note.title,
        "content": note.content,
        "folder_path": folder.path if folder else "",
        "tags": tag_names,
        "updated_at": note.updated_at.isoformat() if note.updated_at else "",
    }


async def _tool_list_folders(user_id: str, db: AsyncSession) -> list[dict]:
    """List all folders for the user."""
    result = await db.execute(
        select(Folder)
        .where(Folder.user_id == UUID(user_id))
        .order_by(Folder.path)
    )
    folders = result.scalars().all()
    return [{"id": str(f.id), "name": f.name, "path": f.path} for f in folders]


async def _tool_list_notes_in_folder(folder_path: str, user_id: str, db: AsyncSession) -> list[dict]:
    """List all notes in a specific folder (by path)."""
    folder_result = await db.execute(
        select(Folder).where(Folder.path == folder_path, Folder.user_id == UUID(user_id))
    )
    folder = folder_result.scalar_one_or_none()
    if not folder:
        return []
    notes_result = await db.execute(
        select(Note).where(Note.folder_id == folder.id).order_by(Note.updated_at.desc())
    )
    notes = notes_result.scalars().all()
    return [
        {"note_id": str(n.id), "title": n.title, "preview": n.content[:200]}
        for n in notes
    ]


# ── Agent Loop ────────────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """Du bist ein agentischer Assistent für ein Second Brain / Notiz-System.
Du kannst Notizen suchen, lesen, erstellen, bearbeiten und löschen.

Du arbeitest in einer Schleife: Du analysierst die Anfrage, führst Tools aus, und erstellst dann Vorschläge.

## Verfügbare Tools (als JSON-Objekte in deiner Antwort):

1. `{"tool": "search", "query": "..."}` — Semantische Suche über alle Notizen
2. `{"tool": "read_note", "note_id": "..."}` — Vollständige Notiz lesen
3. `{"tool": "list_folders"}` — Alle Ordner auflisten
4. `{"tool": "list_notes", "folder_path": "..."}` — Notizen in einem Ordner auflisten
5. `{"tool": "think", "thought": "..."}` — Deine Überlegungen dokumentieren (wird dem User als "Denkt nach..." angezeigt)

## Wenn du fertig bist, antworte mit Proposals:

```json
{"done": true, "summary": "Zusammenfassung was ich gemacht habe", "proposals": [...]}
```

Jeder Proposal hat einen dieser Typen:
- `{"type": "create", "folder_path": "...", "title": "...", "content": "...", "tags": [...], "reason": "..."}`
- `{"type": "update", "note_id": "...", "new_title": "...", "new_content": "...", "reason": "..."}`
- `{"type": "delete", "note_id": "...", "reason": "..."}`

## Wichtige Regeln:
- Denke Schritt für Schritt — nutze `think` um deinen Denkprozess zu zeigen
- Suche IMMER zuerst nach relevanten bestehenden Notizen bevor du neue erstellst
- Achte auf die bestehende Ordnerstruktur und passe dich an
- Verwende die Sprache der Notizen / des Benutzers
- Erstelle Notizen in gut formatiertem Markdown
- Du kannst mehrere Tools pro Schritt aufrufen — gib sie als JSON-Array zurück
- Wenn du Informationen brauchst, nutze die Tools statt zu raten
- Schreibe NUR gültiges JSON als Antwort (Array von Tool-Calls ODER das finale done-Objekt)
- Führe maximal 5 Schleifen-Iterationen durch
"""


async def run_agent(
    instruction: str,
    user_id: str,
    db: AsyncSession,
    auto_accept: bool = False,
) -> dict:
    """
    Run the agent loop. Returns a dict with:
    - steps: list of {type, content} — thinking steps, tool calls, results
    - proposals: list of proposed changes
    - summary: final summary text
    """
    model = _get_model()

    # Gather initial context
    folders = await _tool_list_folders(user_id, db)
    folder_tree_str = "\n".join(f"  📁 {f['path']}" for f in folders) or "(keine Ordner vorhanden)"

    messages_context = f"""## Aktuelle Ordnerstruktur:
{folder_tree_str}

## Benutzer-Anfrage:
{instruction}

Beginne mit deiner Analyse. Nutze Tools um relevante Notizen zu finden und den Kontext zu verstehen.
Antworte mit einem JSON-Array von Tool-Aufrufen oder dem finalen done-Objekt."""

    conversation = [
        {"role": "user", "parts": [AGENT_SYSTEM_PROMPT + "\n\n" + messages_context]}
    ]

    steps = []
    proposals = []
    summary = ""
    max_iterations = 6

    for iteration in range(max_iterations):
        # Generate next step
        raw_response = await _generate(model, _format_conversation(conversation))

        # Parse the response
        cleaned = _extract_json(raw_response)

        if cleaned is None:
            steps.append({"type": "error", "content": f"Konnte Antwort nicht parsen: {raw_response[:200]}"})
            break

        # Check if done
        if isinstance(cleaned, dict) and cleaned.get("done"):
            summary = cleaned.get("summary", "Fertig.")
            proposals = cleaned.get("proposals", [])
            steps.append({"type": "done", "content": summary})
            break

        # Process tool calls
        tool_calls = cleaned if isinstance(cleaned, list) else [cleaned]
        tool_results = []

        for call in tool_calls:
            if not isinstance(call, dict):
                continue

            tool_name = call.get("tool", "")

            if tool_name == "think":
                thought = call.get("thought", "")
                steps.append({"type": "thinking", "content": thought})
                tool_results.append({"tool": "think", "result": "OK"})

            elif tool_name == "search":
                query = call.get("query", "")
                steps.append({"type": "tool_call", "content": f"🔍 Suche: \"{query}\""})
                results = await _tool_search(query, user_id, db)
                steps.append({"type": "tool_result", "content": f"Gefunden: {len(results)} Ergebnisse"})
                tool_results.append({"tool": "search", "query": query, "results": results})

            elif tool_name == "read_note":
                note_id = call.get("note_id", "")
                steps.append({"type": "tool_call", "content": f"📖 Lese Notiz: {note_id}"})
                result = await _tool_read_note(note_id, user_id, db)
                if result:
                    steps.append({"type": "tool_result", "content": f"Gelesen: \"{result['title']}\" ({len(result['content'])} Zeichen)"})
                else:
                    steps.append({"type": "tool_result", "content": f"Notiz nicht gefunden: {note_id}"})
                tool_results.append({"tool": "read_note", "note_id": note_id, "result": result})

            elif tool_name == "list_folders":
                steps.append({"type": "tool_call", "content": "📁 Liste Ordner auf"})
                result = await _tool_list_folders(user_id, db)
                steps.append({"type": "tool_result", "content": f"{len(result)} Ordner gefunden"})
                tool_results.append({"tool": "list_folders", "result": result})

            elif tool_name == "list_notes":
                folder_path = call.get("folder_path", "")
                steps.append({"type": "tool_call", "content": f"📋 Notizen in: {folder_path}"})
                result = await _tool_list_notes_in_folder(folder_path, user_id, db)
                steps.append({"type": "tool_result", "content": f"{len(result)} Notizen gefunden"})
                tool_results.append({"tool": "list_notes", "folder_path": folder_path, "result": result})

            else:
                steps.append({"type": "error", "content": f"Unbekanntes Tool: {tool_name}"})
                tool_results.append({"tool": tool_name, "error": "Unbekanntes Tool"})

        # Feed results back into conversation
        conversation.append({"role": "model", "parts": [raw_response]})
        conversation.append({
            "role": "user",
            "parts": [f"Tool-Ergebnisse:\n```json\n{json.dumps(tool_results, ensure_ascii=False, default=str)}\n```\n\nFahre fort. Wenn du genug Informationen hast, erstelle das finale done-Objekt mit deinen Proposals."]
        })

    return {
        "steps": steps,
        "proposals": proposals,
        "summary": summary,
        "auto_accept": auto_accept,
    }


def _format_conversation(conversation: list[dict]) -> str:
    """Format conversation for single-prompt generation."""
    parts = []
    for msg in conversation:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        parts.append(f"[{role_label}]:\n{msg['parts'][0]}")
    return "\n\n".join(parts) + "\n\n[Assistant]:\n"


def _extract_json(text: str):
    """Extract JSON from LLM response — handles code fences and raw JSON."""
    text = text.strip()

    # Try to extract from code fences first
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try parsing as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try finding the first [ or { and parse from there
    for start_char, end_char in [('[', ']'), ('{', '}')]:
        start = text.find(start_char)
        if start == -1:
            continue
        # Find matching end
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None
