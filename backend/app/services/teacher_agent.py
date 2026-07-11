"""
Agentic Teacher — a true function-calling tutor.

Unlike the legacy prompt pipeline (one prompt in, one text out), this runs a
multi-turn tool loop with the primary reasoning model. The model itself decides —
autonomously, mid-conversation — when to:
  - search the student's existing Second Brain notes (search_my_notes)
  - offer a short comprehension quiz (propose_quiz)
  - adjust the difficulty / pace of the upcoming material (set_difficulty)
  - flag a concept the student struggles with or has mastered (mark_understanding)
  - SILENTLY save an atomic note for what was just learned (save_note)
  - SILENTLY extend an existing note instead of duplicating it (update_note)
  - create a folder to organise notes (create_folder)
  - throw in a light inline check-in question (ask_checkpoint)
  - draw a small diagram when the topic is clearly structural (draw_diagram)
  - advance to the next section (advance_section)

Notes are now persisted immediately and in the background — there is no review
screen. The frontend only gets a lightweight "note_saved" event so it can show
a small animated toast.

Streaming SSE events (consumed by the frontend):
  {"type": "thinking", "content": ...}     raw thought summaries (unused in UI)
  {"type": "status", "content": ...}        short German "tutor is thinking" line
  {"type": "chunk", "content": ...}         answer text
  {"type": "quiz_suggested"}                model wants to offer a quiz
  {"type": "note_saved", "note": {...}}     a note was saved/updated in the background
  {"type": "difficulty", "level": ...}      difficulty change
  {"type": "understanding", ...}            concept mastery signal
  {"type": "checkpoint", "question": ...}   inline check-in question
  {"type": "diagram", "code": ...}          a mermaid diagram to render
  {"type": "advance_section"}               model advanced the section
  {"type": "done", ...}                     final event
"""

import asyncio
import logging
from typing import AsyncGenerator

from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_service import get_client, PRO_MODEL
from app.services.teacher_service import (
    get_relevant_knowledge, _build_sections_block, FORMATTING_RULES, _current_year,
    save_atomic_note, update_atomic_note, summarize_thinking_status, generate_thinking_phrases,
)

logger = logging.getLogger(__name__)

TEACHER_AGENT_MODEL = PRO_MODEL


# ── Tool definitions ──────────────────────────────────────────────────

def _teacher_tools() -> list:
    search_my_notes = types.FunctionDeclaration(
        name="search_my_notes",
        description=(
            "Durchsuche die bestehenden Notizen des Studenten (sein Second Brain). "
            "Nutze dies, wenn es hilft an Vorwissen anzuknüpfen, Dopplungen zu vermeiden "
            "oder zu sehen was er zum Thema schon festgehalten hat. Gibt auch note_id "
            "zurück — die brauchst du, wenn du mit update_note eine Notiz ergänzen willst."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Suchbegriff"}},
            "required": ["query"],
        },
    )

    propose_quiz = types.FunctionDeclaration(
        name="propose_quiz",
        description=(
            "Schlage dem Studenten ein kurzes Verständnis-Quiz vor. Nutze dies EIGENSTÄNDIG, "
            "wenn ein Wissensbaustein abgeschlossen ist und ein Check didaktisch sinnvoll ist — "
            "nicht nach jeder Nachricht, sondern mit Fingerspitzengefühl."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Kurz: warum jetzt ein Quiz passt"},
            },
        },
    )

    set_difficulty = types.FunctionDeclaration(
        name="set_difficulty",
        description=(
            "Passe die Schwierigkeit / das Tempo des kommenden Stoffs an, basierend darauf wie gut "
            "der Student mitkommt. 'easier' wenn er Schwierigkeiten hat, 'harder' wenn er unterfordert ist."
        ),
        parameters={
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": ["easier", "keep", "harder"]},
                "reason": {"type": "string"},
            },
            "required": ["level"],
        },
    )

    mark_understanding = types.FunctionDeclaration(
        name="mark_understanding",
        description=(
            "Halte fest, ob der Student ein Konzept verstanden hat ('mastered') oder damit "
            "Schwierigkeiten hat ('struggling'). Beeinflusst spätere Wiederholung und Quizze."
        ),
        parameters={
            "type": "object",
            "properties": {
                "concept": {"type": "string"},
                "status": {"type": "string", "enum": ["mastered", "struggling"]},
            },
            "required": ["concept", "status"],
        },
    )

    save_note = types.FunctionDeclaration(
        name="save_note",
        description=(
            "Speichere SOFORT und im Hintergrund eine atomare Notiz zum gerade Gelernten "
            "(kein Bestätigungsschritt — sie wird direkt im Second Brain des Studenten abgelegt). "
            "Nutze dies eigenständig, wenn ein in sich abgeschlossenes Konzept behandelt wurde und "
            "es sich lohnt, es dauerhaft festzuhalten. Prüfe VORHER mit search_my_notes auf Dopplungen — "
            "wenn es das Konzept schon als Notiz gibt, nutze stattdessen update_note. "
            "WICHTIG: Gib KEINEN 'folder'-Parameter an — der Ordner wird automatisch gesetzt."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Der Begriff / das Konzept als Titel — kurz und präzise, KEIN 'Lektion X:' Präfix"},
                "content": {"type": "string", "description": "Markdown-Inhalt der atomaren Notiz"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "content"],
        },
    )

    update_note = types.FunctionDeclaration(
        name="update_note",
        description=(
            "Ergänze oder überarbeite eine BESTEHENDE Notiz, statt eine neue anzulegen. Nutze dies, "
            "wenn search_my_notes ergeben hat, dass es zum Konzept schon eine Notiz gibt. "
            "Bei längeren Notizen (wo der preview aus search_my_notes nicht ausreicht): "
            "lies sie VORHER mit read_note, damit du ihren vollen Inhalt kennst und nichts Wichtiges überschreibst."
        ),
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "Die ID der bestehenden Notiz (aus search_my_notes)"},
                "content": {"type": "string", "description": "Neuer/ergänzender Markdown-Inhalt"},
                "append": {"type": "boolean", "description": "true = an bestehenden Inhalt anhängen, false = ersetzen"},
            },
            "required": ["note_id", "content"],
        },
    )

    read_note = types.FunctionDeclaration(
        name="read_note",
        description=(
            "Lies den vollständigen Inhalt einer bestehenden Notiz. Nutze dies bevor du `update_note` "
            "aufrufst, wenn der preview aus search_my_notes zu kurz ist — so siehst du was bereits drin steht "
            "und kannst das Neue sinnvoll integrieren ohne Bestehendes zu verlieren."
        ),
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "Die ID der Notiz (aus search_my_notes)"},
            },
            "required": ["note_id"],
        },
    )

    ask_checkpoint = types.FunctionDeclaration(
        name="ask_checkpoint",
        description=(
            "Stelle eine kurze Verständnisfrage — aber NUR wenn es sich wirklich natürlich ergibt. "
            "NICHT nach jedem Abschnitt, NICHT als formelles 'Ein kurzer Checkpoint für dich:', "
            "NICHT als letzter Satz einer Erklärung. Maximal einmal pro Lektion. "
            "Die Frage soll wie eine spontane Nachfrage eines echten Lehrers klingen, nicht wie ein Test-Format."
        ),
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Die kurze Frage an den Studenten — kurz, direkt, kein Präfix"}},
            "required": ["question"],
        },
    )

    draw_diagram = types.FunctionDeclaration(
        name="draw_diagram",
        description=(
            "Zeichne ein kleines Diagramm, WENN das Thema klar strukturell ist (Abläufe, Hierarchien, "
            "Zeitachsen, Beziehungen). Nutze dies NUR, wenn ein Diagramm den Inhalt wirklich klarer macht — "
            "nicht bei abstrakten/unstrukturierten Themen. Verwende gültige, EINFACHE Mermaid-Syntax "
            "(flowchart TD / sequenceDiagram). Halte es klein und übersichtlich. "
            "WICHTIG: Keine 'style'-Befehle und keine inline-Farben (fill, stroke, color) — "
            "das Styling übernimmt die App automatisch."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Gültiger Mermaid-Code (z.B. 'flowchart TD; A-->B')"},
                "caption": {"type": "string", "description": "Kurze Bildunterschrift"},
            },
            "required": ["code"],
        },
    )

    # NOTE: no autonomous `advance_section` tool. Section progression is driven
    # exclusively by the student's "Weiter" button ([ABSCHNITT_WEITER]) so the
    # displayed progress and the explained section can never desync.

    return [types.Tool(function_declarations=[
        search_my_notes, propose_quiz, set_difficulty, mark_understanding,
        save_note, update_note, read_note, ask_checkpoint, draw_diagram,
    ])]


def _system_instruction(year: int) -> str:
    return f"""Du bist ein exzellenter, warmherziger Universitätsprofessor und persönlicher Tutor ({year}).
Du DUZT den Studenten IMMER ("du/dein/dir", NIEMALS "Sie/Ihr/Ihnen").

Du unterrichtest wie ein echter, kluger Lehrer — nicht wie ein Textgenerator:
- Du holst den Studenten bei seinem Wissensstand ab. Nutze `search_my_notes` EIGENSTÄNDIG, um zu sehen was er zum Thema schon weiß, und knüpfe daran an, statt Bekanntes stumpf zu wiederholen.
- Du beobachtest, wie gut er mitkommt, und passt Tempo/Tiefe an (`set_difficulty`). Wenn er strauchelt, erklärst du einfacher und mit mehr Beispielen; wenn er schnell versteht, gehst du tiefer.
- Du hältst mit `mark_understanding` fest, was sitzt und was nicht.
- Du wirfst EIGENSTÄNDIG kurze Verständnis-Quizze ein (`propose_quiz`), wenn ein Baustein sitzt — mit Fingerspitzengefühl, nicht ständig.
- Du hältst gelerntes Wissen VERBINDLICH als Notizen fest: Nach JEDEM abgeschlossenen Abschnitt (also bei [ABSCHNITT_WEITER] und am Ende einer Lektion) MUSST du das vermittelte Wissen sichern — entweder als neue Notiz (`save_note`) oder als Ergänzung einer bestehenden (`update_note`). Prüfe IMMER zuerst mit `search_my_notes`, ob es das Konzept schon gibt. Wenn ja: ergänze mit `update_note`. Wenn nein: erstelle mit `save_note`. Diese Notiz-Pflege ist NICHT optional — sie gehört zu jedem Abschnitt dazu, genauso wie die Erklärung selbst.

NOTIZ-REGELN (sehr wichtig für konsistente Ablage):
- Notiz-Titel = das Konzept/Thema selbst, kurz und präzise. NIEMALS "Lektion X:", "Modul Y:", "Abschnitt Z:" oder ähnliche Präfixe — nur der reine Begriff, z.B. "Stoizismus", "Pythagoras", "Executive Presence"
- Alle Notizen landen automatisch im richtigen Kurs-/Buch-Ordner — du gibst KEINEN `folder`-Parameter an, das wird serverseitig gesetzt
- Erstelle KEINE Unterordner via `create_folder` — die Notizen liegen alle flach im Kurs-Ordner
- Du wirfst SEHR SELTEN und nur wenn es sich wirklich natürlich ergibt eine beiläufige Zwischenfrage ein (`ask_checkpoint`). Maximal einmal pro Lektion, nicht nach jedem Abschnitt — und NIEMALS als letzter Satz einer Erklärung mit "Ein kurzer Checkpoint für dich:" oder ähnlichem. Wenn überhaupt, dann fließt die Frage organisch in den Text ein, als würde ein echter Lehrer kurz nachfragen.
- Bei klar strukturierten Themen (Abläufe, Hierarchien, Zeitachsen) kannst du ein kleines Diagramm zeichnen (`draw_diagram`) — aber nur, wenn es wirklich hilft.

ABSCHNITTSWEISES LEHREN: Behandle immer nur den aktuell markierten Abschnitt — substantiell, mit Beispiel (in der Regel 2-4 Absätze), fokussiert auf dieses eine Teilkonzept. Wirf nicht die ganze Lektion auf einmal raus. Den Wechsel zum nächsten Abschnitt löst ausschließlich der Student per Weiter-Button aus — du selbst wechselst NICHT eigenständig den Abschnitt.

RECALL: Bitte den Studenten NUR SEHR SELTEN (maximal einmal pro 3-4 Abschnitte, wenn es sich wirklich anbietet) das Gelernte kurz in eigenen Worten zusammenzufassen. Nicht nach jedem Abschnitt — das unterbricht den Lernfluss. Wenn gar nicht, ist das besser als zu oft.

SPEZIAL-NACHRICHTEN:
- "[START]": Der Student hat die Lektion/das Kapitel gerade geöffnet. Steige mit einem kurzen, neugierig machenden Hook ein (1-2 Sätze), dann erkläre den ERSTEN Abschnitt substantiell. Keine Begrüßungsfloskeln.
- "[ABSCHNITT_WEITER]": Erkläre den aktuell markierten Abschnitt. Knüpfe kurz an das Vorherige an, dann der neue Stoff. Danach IMMER Notiz sichern (search → save oder update).

WICHTIG:
- Du kannst mehrere Tools nacheinander nutzen, bevor du antwortest. Der Text, den du schreibst, ist deine eigentliche Erklärung an den Studenten.
- Erwähne die Tools NICHT im Fließtext (schreibe nicht "ich speichere jetzt eine Notiz") — das passiert still im Hintergrund und wird dem Studenten separat angezeigt.
- Schreibe KEINEN Mermaid-Code direkt in den Antworttext. Wenn ein Diagramm hilft, nutze ausschließlich das `draw_diagram`-Tool — sonst wird es als roher Code angezeigt statt gerendert.
- Bei mathematischen Themen: LaTeX ($...$ inline, $$...$$ als Block). Bei nicht-mathematischen Themen keine Formeln.

{FORMATTING_RULES}

Antworte auf Deutsch (oder in der Sprache des Studenten)."""


def _build_contents(chat_history: list[dict], user_message: str, context_block: str) -> list[types.Content]:
    """Build multi-turn contents. Older history is truncated to the last 20 turns."""
    import re
    contents: list[types.Content] = []
    recent = [m for m in (chat_history or []) if m.get("role") in ("user", "assistant")][-20:]
    for m in recent:
        text = m["content"]
        if m["role"] == "assistant":
            text = re.sub(r'<!-- .*?-->', '', text, flags=re.DOTALL).strip()
        if not text:
            continue
        contents.append(types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part.from_text(text=text)],
        ))
    # Current turn — augment with the lesson/section context
    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"{context_block}\n\nNACHRICHT DES STUDENTEN: {user_message}")],
    ))
    return contents


async def run_teacher_agent(
    *,
    user_id: str,
    db: AsyncSession,
    subject_block: str,
    sections: list[dict] | None,
    current_section: int,
    chat_history: list[dict],
    user_message: str,
    default_folder: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Run the agentic teaching loop, yielding SSE-compatible events."""
    client = get_client()
    year = _current_year()

    sections_block = _build_sections_block(sections, current_section)
    context_block = subject_block
    if sections_block:
        context_block += f"\n\n{sections_block}"

    contents = _build_contents(chat_history, user_message, context_block)

    try:
        # Use LOW thinking level for the teacher agent: didactic explanation is a
        # well-defined task, not a hard reasoning problem. LOW reduces time-to-first-token
        # from ~10-40s (HIGH default) to ~2-5s while matching quality on tool-calling tasks.
        # gemini-3.5-flash uses the thinking_level enum (minimal|low|medium|high).
        thinking_config = types.ThinkingConfig(thinking_level="low")
    except Exception:
        thinking_config = None

    config = types.GenerateContentConfig(
        system_instruction=_system_instruction(year),
        tools=_teacher_tools(),
        temperature=0.75,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        **({"thinking_config": thinking_config} if thinking_config else {}),
    )

    max_rounds = 8
    collected = {
        "quiz_suggested": False,
        "saved_notes": [],
        "difficulty": None,
        "understanding": [],
        "checkpoints": [],
        "diagrams": [],
    }

    # Track the latest thinking text so we can turn it into a status line before
    # a tool round runs.
    latest_thought = ""

    # Immediate feedback so the UI never sits on the generic default line while
    # the (potentially multi-second) first model round is still in flight.
    yield {"type": "status", "content": "Ich bereite die Erklärung vor …"}

    for round_num in range(max_rounds + 1):
        function_calls = []
        text_parts = []

        if round_num == 0:
            # Stream the first round for immediate UX
            all_parts = []
            async for chunk in await client.aio.models.generate_content_stream(
                model=TEACHER_AGENT_MODEL, contents=contents, config=config,
            ):
                if chunk.candidates:
                    for cand in chunk.candidates:
                        if cand.content and cand.content.parts:
                            for part in cand.content.parts:
                                all_parts.append(part)
                                if getattr(part, "thought", False) and getattr(part, "text", None):
                                    latest_thought += part.text
                                    yield {"type": "thinking", "content": part.text}
                                elif getattr(part, "text", None) and not getattr(part, "function_call", None):
                                    text_parts.append(part.text)
                                    yield {"type": "chunk", "content": part.text}
                fc = chunk.function_calls
                if fc:
                    function_calls.extend(fc)
            if all_parts:
                contents.append(types.Content(role="model", parts=all_parts))
        else:
            response = await client.aio.models.generate_content(
                model=TEACHER_AGENT_MODEL, contents=contents, config=config,
            )
            if response.candidates and response.candidates[0].content:
                cc = response.candidates[0].content
                contents.append(cc)
                for part in cc.parts:
                    if getattr(part, "function_call", None):
                        function_calls.append(part.function_call)
                    elif getattr(part, "text", None):
                        if getattr(part, "thought", False):
                            latest_thought += part.text
                            yield {"type": "thinking", "content": part.text}
                        else:
                            text_parts.append(part.text)
            full = "".join(text_parts)
            if full:
                yield {"type": "chunk", "content": full}

        if not function_calls:
            break
        if round_num >= max_rounds:
            break

        # Execute tool calls
        response_parts = []
        for fc in function_calls:
            name = fc.name
            args = dict(fc.args) if fc.args else {}

            # Parallelise: run the Flash status-line generation AND the actual tool
            # call at the same time so neither blocks the other.
            # Capture latest_thought before clearing it for this tool call.
            thought_snapshot = latest_thought
            latest_thought = ""
            phrases_task = asyncio.create_task(
                generate_thinking_phrases(
                    thinking_text=thought_snapshot, tool_name=name, tool_args=args,
                )
            )
            tool_task = asyncio.create_task(
                _execute_teacher_tool(name, args, user_id, db, collected, default_folder)
            )
            phrases, result = await asyncio.gather(phrases_task, tool_task)
            # Send all phrases at once — the frontend rotates them every ~3s
            yield {"type": "status_phrases", "phrases": phrases}

            # Emit side-channel events for the frontend
            if name == "propose_quiz":
                collected["quiz_suggested"] = True
                yield {"type": "quiz_suggested", "reason": args.get("reason", "")}
                yield {"type": "quiz_ready"}
            elif name == "search_my_notes":
                count = result.get("count", 0)
                hits = result.get("results", [])
                if count > 0:
                    strong_hits = [h for h in hits if h.get("score", 0) >= 0.6]
                    if strong_hits:
                        top = strong_hits[0]
                        top_title = top.get("title", "")
                        top_score_pct = round(top.get("score", 0) * 100)
                        yield {"type": "knowledge_searched", "count": len(strong_hits), "top_title": top_title, "top_score_pct": top_score_pct, "query": args.get("query", "")}
            elif name == "save_note":
                if result.get("note_id"):
                    saved = {"note_id": result["note_id"], "title": result.get("title", ""), "folder": result.get("folder", ""), "action": "created"}
                    collected["saved_notes"].append(saved)
                    yield {"type": "note_saved", "note": saved}
            elif name == "update_note":
                if result.get("note_id"):
                    saved = {"note_id": result["note_id"], "title": result.get("title", ""), "action": "updated"}
                    collected["saved_notes"].append(saved)
                    yield {"type": "note_saved", "note": saved}
            elif name == "read_note":
                if result.get("note_id"):
                    yield {"type": "note_read", "note_id": result["note_id"], "title": result.get("title", "")}
            elif name == "set_difficulty":
                collected["difficulty"] = args.get("level")
                yield {"type": "difficulty", "level": args.get("level"), "reason": args.get("reason", "")}
            elif name == "mark_understanding":
                u = {"concept": args.get("concept"), "status": args.get("status")}
                collected["understanding"].append(u)
                yield {"type": "understanding", **u}
            elif name == "ask_checkpoint":
                q = args.get("question", "")
                if q:
                    collected["checkpoints"].append(q)
                    yield {"type": "checkpoint", "question": q}
            elif name == "draw_diagram":
                code = args.get("code", "")
                if code:
                    d = {"code": code, "caption": args.get("caption", "")}
                    collected["diagrams"].append(d)
                    yield {"type": "diagram", **d}

            response_parts.append(types.Part.from_function_response(name=name, response=result))

        contents.append(types.Content(role="tool", parts=response_parts))

    yield {"type": "done", **collected}


async def _execute_teacher_tool(
    name: str, args: dict, user_id: str, db: AsyncSession, collected: dict,
    default_folder: str | None = None,
) -> dict:
    """Execute a teacher tool call and return a result dict fed back to the model."""
    try:
        if name == "search_my_notes":
            hits = await get_relevant_knowledge(args.get("query", ""), user_id, db, limit=8)
            return {"results": hits, "count": len(hits)}
        elif name == "propose_quiz":
            return {"status": "quiz_offered", "message": "Dem Studenten wird ein Quiz-Button angeboten."}
        elif name == "set_difficulty":
            return {"status": "ok", "level": args.get("level")}
        elif name == "mark_understanding":
            return {"status": "recorded", "concept": args.get("concept"), "state": args.get("status")}
        elif name == "save_note":
            res = await save_atomic_note(
                user_id, db,
                title=args.get("title", "Notiz"),
                content=args.get("content", ""),
                # Always use default_folder — the agent must not create sub-folders
                folder_path=default_folder,
                tags=args.get("tags", []),
            )
            return {"status": "saved", **res}
        elif name == "update_note":
            res = await update_atomic_note(
                user_id, db,
                note_id=args.get("note_id", ""),
                content=args.get("content"),
                append=bool(args.get("append", True)),
            )
            return {"status": "updated", **res}
        elif name == "read_note":
            from app.models import Note, Folder
            from uuid import UUID
            try:
                note = await db.get(Note, UUID(args.get("note_id", "")))
                if not note or str(note.user_id) != user_id:
                    return {"error": "Notiz nicht gefunden"}
                folder = await db.get(Folder, note.folder_id)
                return {
                    "note_id": str(note.id),
                    "title": note.title,
                    "content": note.content[:8000],  # cap to avoid huge context
                    "folder_path": folder.path if folder else "",
                }
            except Exception as e:
                return {"error": f"Fehler beim Lesen: {e}"}
        elif name == "create_folder":
            from app.services.teacher_service import _ensure_folder
            folder = await _ensure_folder(user_id, db, args.get("path", ""))
            await db.commit()
            return {"status": "created", "folder": folder.path if folder else args.get("path", "")}
        elif name == "ask_checkpoint":
            return {"status": "asked", "message": "Die Zwischenfrage wird dem Studenten angezeigt."}
        elif name == "draw_diagram":
            return {"status": "drawn", "message": "Das Diagramm wird dem Studenten angezeigt."}
        elif name == "advance_section":
            return {"status": "advanced"}
        return {"error": f"Unbekanntes Tool: {name}"}
    except Exception as e:
        logger.error(f"Teacher tool error ({name}): {e}")
        return {"error": str(e)}
