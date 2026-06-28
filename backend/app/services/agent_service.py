"""
Agentic Workspace Service — conversational AI agent that can read, search,
brainstorm and plan with the user, and only writes/creates notes when appropriate.

The agent operates conversationally:
1. Receives user message + context (folder structure, chat history)
2. Can use tools to search/read notes for context
3. Responds conversationally — brainstorming, asking questions, planning
4. Only generates proposals (create/update/delete) when the user explicitly asks
   or when it makes clear sense from the conversation

This is NOT a one-shot tool caller — it's a conversational partner that happens
to have access to the user's notes.
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
    return genai.GenerativeModel("gemini-3-flash-preview")


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
        {"note_id": str(n.id), "title": n.title, "preview": n.content[:300]}
        for n in notes
    ]


# ── Agent Loop ────────────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """Du bist ein intelligenter Assistent für ein Second Brain / Notiz-System.
Du kannst mit dem Benutzer brainstormen, planen, Fragen stellen und Ideen entwickeln.
Du hast Zugriff auf alle Notizen des Benutzers und kannst diese durchsuchen und lesen.

## Dein Verhalten:

1. **Konversationell**: Du führst ein Gespräch. Stelle Rückfragen wenn nötig, brainstorme mit,
   schlage Strukturen vor, diskutiere Ideen.
   
2. **Notizen nur wenn sinnvoll**: Erstelle/bearbeite Notizen NUR wenn:
   - Der Benutzer es explizit wünscht ("erstelle eine Notiz", "schreib das auf", "mach daraus eine Notiz")
   - Es aus dem Gesprächskontext klar ergibt, dass eine Notiz erstellt werden soll
   - Du genug Informationen hast um eine sinnvolle Notiz zu erstellen
   
3. **Immer informiert**: Nutze die Suchfunktion proaktiv um relevante bestehende Notizen
   zu finden und in deine Antworten einzubeziehen.

## Antwortformat:

Deine Antwort MUSS immer gültiges JSON sein:

```json
{
  "response": "Deine Nachricht an den Benutzer (Markdown erlaubt)",
  "tool_calls": [...],
  "proposals": [...]
}
```

### Felder:
- `response` (PFLICHT): Deine Nachricht an den Benutzer. Kann Markdown enthalten.
  Hier brainstormst du, stellst Fragen, diskutierst, etc.
  
- `tool_calls` (optional): Tools die du VORHER ausführen willst um Kontext zu bekommen:
  - `{"tool": "search", "query": "..."}`
  - `{"tool": "read_note", "note_id": "..."}`
  - `{"tool": "list_folders"}`
  - `{"tool": "list_notes", "folder_path": "..."}`
  
- `proposals` (optional, NUR wenn der Benutzer es will oder es klar Sinn macht):
  - `{"type": "create", "folder_path": "...", "title": "...", "content": "...", "tags": [...], "reason": "..."}`
  - `{"type": "update", "note_id": "...", "new_title": "...", "new_content": "...", "reason": "..."}`
  - `{"type": "delete", "note_id": "...", "reason": "..."}`

### Wichtig:
- Proposals nur generieren wenn du genug Info hast UND der Benutzer es möchte
- Beim ersten Kontakt zu einem Thema: IMMER erstmal fragen/brainstormen, NICHT sofort Notizen erstellen
- Verweise auf bestehende Notizen wenn du welche findest ("Ich habe dazu schon eine Notiz gefunden...")
- Schreibe den Content in Proposals immer in gut formatiertem Markdown
- Antworte IMMER auf Deutsch (oder in der Sprache des Benutzers)
"""


async def run_agent(
    instruction: str,
    user_id: str,
    db: AsyncSession,
    chat_history: list[dict] = None,
    auto_accept: bool = False,
) -> dict:
    """
    Run the agent. Returns:
    - response: the agent's conversational message
    - steps: list of {type, content} — tool calls executed
    - proposals: list of proposed changes (may be empty)
    """
    model = _get_model()

    # Gather folder context
    folders = await _tool_list_folders(user_id, db)
    folder_tree_str = "\n".join(f"  📁 {f['path']}" for f in folders) or "(keine Ordner)"

    # Build conversation context
    history_str = ""
    if chat_history:
        for msg in chat_history[-10:]:  # last 10 messages for context
            role = "Benutzer" if msg["role"] == "user" else "Assistent"
            history_str += f"\n{role}: {msg['content']}\n"

    context = f"""{AGENT_SYSTEM_PROMPT}

## Aktuelle Ordnerstruktur des Benutzers:
{folder_tree_str}

## Bisheriger Gesprächsverlauf:
{history_str if history_str else "(Neues Gespräch)"}

## Aktuelle Nachricht des Benutzers:
{instruction}

Antworte als JSON. Wenn du zuerst Notizen durchsuchen willst, setze tool_calls.
Wenn du direkt antworten kannst (z.B. bei Rückfragen oder Brainstorming), setze nur response."""

    steps = []
    proposals = []
    response_text = ""

    # Phase 1: Initial generation (may include tool_calls)
    raw = await _generate(model, context)
    parsed = _extract_json(raw)

    if parsed is None:
        # Fallback: treat entire response as conversational text
        response_text = raw.strip()
        return {
            "response": response_text,
            "steps": steps,
            "proposals": [],
            "auto_accept": auto_accept,
        }

    # Execute tool calls if requested
    tool_calls = parsed.get("tool_calls", [])
    if tool_calls:
        tool_results = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            tool_name = call.get("tool", "")

            if tool_name == "search":
                query = call.get("query", "")
                steps.append({"type": "tool_call", "content": f"🔍 Suche: \"{query}\""})
                results = await _tool_search(query, user_id, db)
                steps.append({"type": "tool_result", "content": f"{len(results)} Ergebnisse gefunden"})
                tool_results.append({"tool": "search", "query": query, "results": results})

            elif tool_name == "read_note":
                note_id = call.get("note_id", "")
                steps.append({"type": "tool_call", "content": f"📖 Lese Notiz: {note_id[:8]}..."})
                result = await _tool_read_note(note_id, user_id, db)
                if result:
                    steps.append({"type": "tool_result", "content": f"Gelesen: \"{result['title']}\""})
                else:
                    steps.append({"type": "tool_result", "content": "Notiz nicht gefunden"})
                tool_results.append({"tool": "read_note", "result": result})

            elif tool_name == "list_folders":
                steps.append({"type": "tool_call", "content": "📁 Liste Ordner"})
                result = await _tool_list_folders(user_id, db)
                steps.append({"type": "tool_result", "content": f"{len(result)} Ordner"})
                tool_results.append({"tool": "list_folders", "result": result})

            elif tool_name == "list_notes":
                fp = call.get("folder_path", "")
                steps.append({"type": "tool_call", "content": f"📋 Notizen in: {fp}"})
                result = await _tool_list_notes_in_folder(fp, user_id, db)
                steps.append({"type": "tool_result", "content": f"{len(result)} Notizen"})
                tool_results.append({"tool": "list_notes", "result": result})

        # Phase 2: Generate final response with tool results
        followup = f"""Die Tool-Ergebnisse:
```json
{json.dumps(tool_results, ensure_ascii=False, default=str)[:4000]}
```

Basierend auf diesen Informationen, antworte dem Benutzer jetzt.
Denk dran: Brainstorme, stelle Fragen, oder erstelle Proposals nur wenn es Sinn macht.
Antworte als JSON mit mindestens dem "response" Feld."""

        raw2 = await _generate(model, context + f"\n\n[Deine erste Antwort mit tool_calls]: {raw}\n\n[Tool-Ergebnisse]:\n{followup}")
        parsed2 = _extract_json(raw2)

        if parsed2:
            response_text = parsed2.get("response", "")
            proposals = parsed2.get("proposals", [])
        else:
            response_text = raw2.strip()
    else:
        response_text = parsed.get("response", "")
        proposals = parsed.get("proposals", [])

    return {
        "response": response_text,
        "steps": steps,
        "proposals": proposals,
        "auto_accept": auto_accept,
    }


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

    # Try finding the first { and parse from there
    start = text.find('{')
    if start == -1:
        return None

    # Find matching end brace
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    break
    return None
