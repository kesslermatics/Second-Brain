"""
Agentic Workspace Service — true multi-turn, function-calling agent using
gemini-3.1-pro-preview with thinking and streaming.

Architecture:
- Uses the new google-genai SDK with native function calling (no JSON simulation)
- Multi-turn chat: real conversation history with proper roles
- Thinking model: streams thought summaries + response chunks
- Autonomous tool loop: model decides when to call tools, we execute and feed back
"""

import json
import re
import asyncio
import logging
from typing import Optional, AsyncGenerator
from uuid import UUID

from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.config import get_settings
from app.models import Note, Folder, Tag, Image, note_tags
from app.services.ai_service import get_client, PRO_MODEL
from app.services.vector_service import hybrid_search

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Agent model ───────────────────────────────────────────────────────

AGENT_MODEL = PRO_MODEL  # gemini-3.1-pro-preview — thinking model

# ── System instruction (lean, no JSON format rules) ───────────────────

AGENT_SYSTEM_INSTRUCTION = """Du bist ein intelligenter, eloquenter Assistent für ein persönliches Second Brain / Notiz-System.
Du kannst mit dem Benutzer brainstormen, planen, Fragen stellen und Ideen entwickeln.
Du hast Zugriff auf alle Notizen und Bilder des Benutzers über Tools.

## Verhalten:

1. **Konversationell & intelligent**: Führe ein echtes Gespräch auf hohem Niveau. Stelle Rückfragen, brainstorme mit, schlage Strukturen vor, diskutiere Ideen tiefgründig. Sei eloquent, präzise und hilfreich.

2. **Notizen nur wenn sinnvoll**: Erstelle/bearbeite Notizen NUR wenn der Benutzer es explizit wünscht oder es klar Sinn macht. Beim ersten Kontakt zu einem Thema: brainstorme, frage, diskutiere — erstelle NICHT sofort Notizen.

3. **Bilder proaktiv speichern**: Wenn Bilder hochgeladen werden, speichere sie proaktiv als Notiz in einem passenden Ordner. Nutze ![Beschreibung](URL) zum Einbetten.

4. **Immer informiert**: Nutze die Suchtools proaktiv um relevante bestehende Notizen zu finden. Halte dich thematisch STRIKT an das was gefragt wird.

5. **Ordnerstruktur-Intelligenz**: Analysiere die bestehende Struktur genau. Erstelle sinnvolle Unterordner. Nutze bestehende Ordner wenn sie passen.

## Proposals (Notiz-Änderungen):

Wenn du Notizen erstellen/ändern/löschen willst, nutze die entsprechenden Tools:
- `create_note`: Neue Notiz erstellen
- `update_note`: Bestehende Notiz bearbeiten
- `delete_note`: Notiz löschen

Schreibe Notiz-Inhalte immer in gut formatiertem Markdown mit Headings, Listen, Callouts.

## Sprache:
Antworte IMMER in der Sprache des Benutzers (Standard: Deutsch)."""


# ── Tool definitions (native function declarations) ───────────────────

def _get_agent_tools() -> list:
    """Define the tools available to the agent as Python functions for automatic calling."""

    # We use manual FunctionDeclarations for more control over descriptions
    search_notes = types.FunctionDeclaration(
        name="search_notes",
        description="Semantische und Volltextsuche über alle Notizen und Bilder des Benutzers. Nutze dies proaktiv um relevanten Kontext zu finden.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchanfrage (semantisch + Volltext)",
                },
            },
            "required": ["query"],
        },
    )

    read_note = types.FunctionDeclaration(
        name="read_note",
        description="Lese den vollständigen Inhalt einer bestimmten Notiz anhand ihrer ID.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "UUID der Notiz",
                },
            },
            "required": ["note_id"],
        },
    )

    list_folders = types.FunctionDeclaration(
        name="list_folders",
        description="Liste alle Ordner des Benutzers auf. Nützlich um die Struktur zu verstehen bevor Notizen erstellt werden.",
        parameters={
            "type": "object",
            "properties": {},
        },
    )

    list_notes_in_folder = types.FunctionDeclaration(
        name="list_notes_in_folder",
        description="Liste alle Notizen in einem bestimmten Ordner (nach Pfad).",
        parameters={
            "type": "object",
            "properties": {
                "folder_path": {
                    "type": "string",
                    "description": "Pfad des Ordners, z.B. 'Projekte/Umzug'",
                },
            },
            "required": ["folder_path"],
        },
    )

    search_images = types.FunctionDeclaration(
        name="search_images",
        description="Suche Bilder anhand ihrer KI-generierten Beschreibungen oder Dateinamen.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchbegriff für Bilder",
                },
            },
            "required": ["query"],
        },
    )

    create_note = types.FunctionDeclaration(
        name="create_note",
        description="Erstelle eine neue Notiz im Second Brain. Nutze dies wenn der Benutzer explizit eine Notiz erstellen möchte oder bei Bild-Uploads.",
        parameters={
            "type": "object",
            "properties": {
                "folder_path": {
                    "type": "string",
                    "description": "Ordnerpfad für die Notiz, z.B. 'Projekte/Webdesign'",
                },
                "title": {
                    "type": "string",
                    "description": "Titel der Notiz",
                },
                "content": {
                    "type": "string",
                    "description": "Inhalt der Notiz in Markdown",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags für die Notiz (optional)",
                },
            },
            "required": ["folder_path", "title", "content"],
        },
    )

    update_note = types.FunctionDeclaration(
        name="update_note",
        description="Aktualisiere eine bestehende Notiz (Titel und/oder Inhalt).",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "UUID der zu aktualisierenden Notiz",
                },
                "new_title": {
                    "type": "string",
                    "description": "Neuer Titel (optional, leer lassen um nicht zu ändern)",
                },
                "new_content": {
                    "type": "string",
                    "description": "Neuer Inhalt in Markdown (optional)",
                },
            },
            "required": ["note_id"],
        },
    )

    delete_note = types.FunctionDeclaration(
        name="delete_note",
        description="Lösche eine Notiz aus dem Second Brain.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "UUID der zu löschenden Notiz",
                },
            },
            "required": ["note_id"],
        },
    )

    return [types.Tool(function_declarations=[
        search_notes,
        read_note,
        list_folders,
        list_notes_in_folder,
        search_images,
        create_note,
        update_note,
        delete_note,
    ])]


# ── Tool execution ────────────────────────────────────────────────────

async def _execute_tool(name: str, args: dict, user_id: str, db: AsyncSession) -> dict:
    """Execute a tool call and return the result as a dict."""
    try:
        if name == "search_notes":
            results = await hybrid_search(
                query=args.get("query", ""),
                user_id=user_id,
                db=db,
                limit=10,
            )
            return {
                "results": [
                    {
                        "note_id": r["note_id"],
                        "title": r["title"],
                        "folder_path": r["folder_path"],
                        "preview": r["content_preview"][:500],
                        "score": r["score"],
                    }
                    for r in results
                ]
            }

        elif name == "read_note":
            note_id = args.get("note_id", "")
            try:
                note = await db.get(Note, UUID(note_id))
            except (ValueError, TypeError):
                return {"error": "Ungültige Notiz-ID"}
            if not note or str(note.user_id) != user_id:
                return {"error": "Notiz nicht gefunden"}
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
            }

        elif name == "list_folders":
            result = await db.execute(
                select(Folder)
                .where(Folder.user_id == UUID(user_id))
                .order_by(Folder.path)
            )
            folders = result.scalars().all()
            return {"folders": [{"path": f.path, "name": f.name} for f in folders]}

        elif name == "list_notes_in_folder":
            folder_path = args.get("folder_path", "")
            folder_result = await db.execute(
                select(Folder).where(Folder.path == folder_path, Folder.user_id == UUID(user_id))
            )
            folder = folder_result.scalar_one_or_none()
            if not folder:
                return {"error": f"Ordner '{folder_path}' nicht gefunden"}
            notes_result = await db.execute(
                select(Note).where(Note.folder_id == folder.id).order_by(Note.updated_at.desc())
            )
            notes = notes_result.scalars().all()
            return {
                "notes": [
                    {"note_id": str(n.id), "title": n.title, "preview": n.content[:300]}
                    for n in notes
                ]
            }

        elif name == "search_images":
            query = args.get("query", "")
            result = await db.execute(
                select(Image)
                .where(
                    Image.user_id == UUID(user_id),
                    Image.description.isnot(None),
                    or_(
                        func.lower(Image.description).contains(query.lower()),
                        func.lower(Image.original_filename).contains(query.lower()),
                    ),
                )
                .order_by(Image.created_at.desc())
                .limit(10)
            )
            images = result.scalars().all()
            backend_url = settings.BACKEND_URL or "http://localhost:8000"
            return {
                "images": [
                    {
                        "image_id": str(img.id),
                        "filename": img.original_filename,
                        "description": img.description[:500] if img.description else "",
                        "url": f"{backend_url}/uploads/{user_id}/{img.stored_filename}",
                    }
                    for img in images
                ]
            }

        elif name == "create_note":
            # Return as a proposal — will be applied by the route handler
            return {
                "status": "proposal_created",
                "proposal": {
                    "type": "create",
                    "folder_path": args.get("folder_path", "Allgemein"),
                    "title": args.get("title", "Neue Notiz"),
                    "content": args.get("content", ""),
                    "tags": args.get("tags", []),
                },
            }

        elif name == "update_note":
            return {
                "status": "proposal_created",
                "proposal": {
                    "type": "update",
                    "note_id": args.get("note_id", ""),
                    "new_title": args.get("new_title"),
                    "new_content": args.get("new_content"),
                },
            }

        elif name == "delete_note":
            return {
                "status": "proposal_created",
                "proposal": {
                    "type": "delete",
                    "note_id": args.get("note_id", ""),
                },
            }

        else:
            return {"error": f"Unbekanntes Tool: {name}"}

    except Exception as e:
        logger.error(f"Tool execution error ({name}): {e}")
        return {"error": str(e)}


# ── Build multi-turn contents from chat history ───────────────────────

def _build_contents(chat_history: list[dict], image_context: list[dict] | None = None) -> list[types.Content]:
    """Convert DB chat history into proper multi-turn contents for the API."""
    contents = []

    for msg in chat_history:
        role = msg["role"]
        content_text = msg["content"]

        # Strip hidden agent metadata from stored assistant messages
        content_text = re.sub(r'<!-- AGENT_META[\s\S]*?AGENT_META -->', '', content_text).strip()

        if role == "user":
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=content_text)],
            ))
        elif role == "assistant":
            contents.append(types.Content(
                role="model",
                parts=[types.Part.from_text(text=content_text)],
            ))

    return contents


# ── Streaming agent run ───────────────────────────────────────────────

async def run_agent_stream(
    instruction: str,
    user_id: str,
    db: AsyncSession,
    chat_history: list[dict] = None,
    auto_accept: bool = False,
    image_context: list[dict] | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Run the agent with streaming. Yields SSE-compatible events:
    - {"type": "thinking", "content": "..."} — thought summaries
    - {"type": "chunk", "content": "..."} — response text chunks
    - {"type": "tool_call", "content": "..."} — tool being called
    - {"type": "tool_result", "content": "..."} — tool result summary
    - {"type": "proposal", "proposal": {...}} — note change proposal
    - {"type": "done", "proposals": [...]} — final event
    """
    client = get_client()

    # Build the folder context as part of the user message
    folders_result = await db.execute(
        select(Folder).where(Folder.user_id == UUID(user_id)).order_by(Folder.path)
    )
    folders = folders_result.scalars().all()
    folder_tree = "\n".join(f"  📁 {f.path}" for f in folders) or "(keine Ordner)"

    # Build multi-turn conversation
    contents = _build_contents(chat_history or [], image_context)

    # Augment the current user message with context
    user_message_parts = []

    # Add image context if present
    if image_context:
        img_text = "\n\n---\n**Hochgeladene Bilder:**\n"
        for img in image_context:
            img_text += f"\n📷 **{img['filename']}** (URL: {img['url']})\n"
            img_text += f"KI-Beschreibung: {img['description']}\n"
        img_text += "\nSpeichere diese Bilder proaktiv als Notiz in einem passenden Ordner.\n"
        user_message_parts.append(instruction + img_text)
    else:
        user_message_parts.append(instruction)

    # Add folder context as system-level info in the user turn
    context_suffix = f"\n\n[Aktuelle Ordnerstruktur:\n{folder_tree}]"
    user_message_parts[0] += context_suffix

    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message_parts[0])],
    ))

    # Agent config
    config = types.GenerateContentConfig(
        system_instruction=AGENT_SYSTEM_INSTRUCTION,
        tools=_get_agent_tools(),
        temperature=0.8,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    proposals = []
    steps = []
    max_tool_rounds = 5  # prevent infinite loops

    for round_num in range(max_tool_rounds + 1):
        # Stream the response — collect ALL parts for thought signature preservation
        full_text_parts = []
        function_calls = []
        all_response_parts = []  # Preserve complete parts including thought signatures

        async for chunk in await client.aio.models.generate_content_stream(
            model=AGENT_MODEL,
            contents=contents,
            config=config,
        ):
            # Collect all parts from candidates for faithful multi-turn replay
            if chunk.candidates:
                for candidate in chunk.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            all_response_parts.append(part)

            # Use the chunk-level accessors for streaming UI
            fc_list = chunk.function_calls
            if fc_list:
                function_calls.extend(fc_list)
            else:
                # Only try to get text when there are no function calls in this chunk
                try:
                    text = chunk.text
                    if text:
                        full_text_parts.append(text)
                        yield {"type": "chunk", "content": text}
                except Exception:
                    pass

        # If no function calls, we're done
        if not function_calls:
            break

        # If we've exhausted rounds, break
        if round_num >= max_tool_rounds:
            break

        # Add the model's COMPLETE response to contents (preserves thought signatures)
        if all_response_parts:
            contents.append(types.Content(role="model", parts=all_response_parts))
        else:
            # Fallback: manually build parts if streaming didn't yield them properly
            model_parts = []
            full_response_text = "".join(full_text_parts)
            if full_response_text:
                model_parts.append(types.Part.from_text(text=full_response_text))
            for fc in function_calls:
                model_parts.append(types.Part(function_call=fc))
            contents.append(types.Content(role="model", parts=model_parts))

        # Execute each function call and build function responses
        function_response_parts = []
        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            step_desc = f"🔧 {tool_name}"
            if tool_args.get("query"):
                step_desc += f': "{tool_args["query"]}"'
            elif tool_args.get("folder_path"):
                step_desc += f': "{tool_args["folder_path"]}"'
            elif tool_args.get("note_id"):
                step_desc += f': {tool_args["note_id"][:8]}...'
            elif tool_args.get("title"):
                step_desc += f': "{tool_args["title"]}"'

            yield {"type": "tool_call", "content": step_desc}
            steps.append({"type": "tool_call", "content": step_desc})

            # Execute
            result = await _execute_tool(tool_name, tool_args, user_id, db)

            # Check if this generated a proposal
            if result.get("status") == "proposal_created":
                proposal = result["proposal"]
                proposals.append(proposal)
                yield {"type": "proposal", "proposal": proposal}
                # Tell the model the proposal was created
                result = {"status": "success", "message": f"Proposal erstellt: {proposal['type']} — wird dem Benutzer zur Bestätigung angezeigt."}

            # Summarize result for streaming UI
            result_summary = _summarize_tool_result(tool_name, result)
            yield {"type": "tool_result", "content": result_summary}
            steps.append({"type": "tool_result", "content": result_summary})

            # Build function response part
            function_response_parts.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=result,
                )
            )

        # Add function responses to contents
        contents.append(types.Content(role="tool", parts=function_response_parts))

        # Continue the loop — model will generate a follow-up response

    yield {"type": "done", "proposals": proposals, "steps": steps}


def _summarize_tool_result(tool_name: str, result: dict) -> str:
    """Create a short human-readable summary of a tool result."""
    if "error" in result:
        return f"❌ Fehler: {result['error']}"

    if tool_name == "search_notes":
        count = len(result.get("results", []))
        return f"📋 {count} Ergebnisse gefunden"
    elif tool_name == "read_note":
        title = result.get("title", "?")
        return f'📖 Gelesen: "{title}"'
    elif tool_name == "list_folders":
        count = len(result.get("folders", []))
        return f"📁 {count} Ordner"
    elif tool_name == "list_notes_in_folder":
        count = len(result.get("notes", []))
        return f"📋 {count} Notizen"
    elif tool_name == "search_images":
        count = len(result.get("images", []))
        return f"🖼️ {count} Bilder gefunden"
    elif tool_name in ("create_note", "update_note", "delete_note"):
        return f"✅ {result.get('message', 'Proposal erstellt')}"
    else:
        return "✅ Erledigt"


# ── Non-streaming fallback (for backwards compat) ─────────────────────

async def run_agent(
    instruction: str,
    user_id: str,
    db: AsyncSession,
    chat_history: list[dict] = None,
    auto_accept: bool = False,
    image_context: list[dict] = None,
) -> dict:
    """
    Non-streaming agent run. Collects all stream events and returns the final result.
    Used as fallback when streaming isn't available.
    """
    response_parts = []
    proposals = []
    steps = []

    async for event in run_agent_stream(
        instruction=instruction,
        user_id=user_id,
        db=db,
        chat_history=chat_history,
        auto_accept=auto_accept,
        image_context=image_context,
    ):
        event_type = event.get("type")
        if event_type == "chunk":
            response_parts.append(event["content"])
        elif event_type == "proposal":
            proposals.append(event["proposal"])
        elif event_type in ("tool_call", "tool_result"):
            steps.append({"type": event_type, "content": event["content"]})
        elif event_type == "done":
            proposals = event.get("proposals", proposals)
            steps = event.get("steps", steps)

    return {
        "response": "".join(response_parts),
        "steps": steps,
        "proposals": proposals,
        "auto_accept": auto_accept,
    }
