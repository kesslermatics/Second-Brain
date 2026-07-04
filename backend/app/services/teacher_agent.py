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

import logging
from typing import AsyncGenerator

from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_service import get_client, PRO_MODEL
from app.services.teacher_service import (
    get_relevant_knowledge, _build_sections_block, FORMATTING_RULES, _current_year,
    save_atomic_note, update_atomic_note, summarize_thinking_status,
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
            "wenn es das Konzept schon als Notiz gibt, nutze stattdessen update_note."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Der Begriff / das Konzept als Titel"},
                "content": {"type": "string", "description": "Markdown-Inhalt der atomaren Notiz"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "folder": {"type": "string", "description": "Optionaler Ordnerpfad, z.B. 'Kurse/Lineare Algebra'"},
            },
            "required": ["title", "content"],
        },
    )

    update_note = types.FunctionDeclaration(
        name="update_note",
        description=(
            "Ergänze oder überarbeite eine BESTEHENDE Notiz, statt eine neue anzulegen. Nutze dies, "
            "wenn search_my_notes ergeben hat, dass es zum Konzept schon eine Notiz gibt — so vermeidest "
            "du Dopplungen und baust das Wissen des Studenten sauber aus. Erfolgt sofort im Hintergrund."
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

    create_folder = types.FunctionDeclaration(
        name="create_folder",
        description=(
            "Lege einen Ordner (Pfad) im Second Brain an, um Notizen sauber zu organisieren. "
            "Ordner werden bei save_note ohnehin automatisch erstellt — nutze dies nur, wenn du "
            "explizit eine Struktur vorbereiten willst."
        ),
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Ordnerpfad, z.B. 'Kurse/Thema/Unterthema'"}},
            "required": ["path"],
        },
    )

    ask_checkpoint = types.FunctionDeclaration(
        name="ask_checkpoint",
        description=(
            "Wirf eine EINZELNE, beiläufige Verständnisfrage mitten in die Erklärung ein — leichter als "
            "ein Quiz, um den Studenten aktiv zu halten. Er kann antworten ODER einfach weitermachen. "
            "Nutze dies mit Fingerspitzengefühl, nicht in jeder Nachricht."
        ),
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string", "description": "Die kurze Frage an den Studenten"}},
            "required": ["question"],
        },
    )

    draw_diagram = types.FunctionDeclaration(
        name="draw_diagram",
        description=(
            "Zeichne ein kleines Diagramm, WENN das Thema klar strukturell ist (Abläufe, Hierarchien, "
            "Zeitachsen, Beziehungen). Nutze dies NUR, wenn ein Diagramm den Inhalt wirklich klarer macht — "
            "nicht bei abstrakten/unstrukturierten Themen. Verwende gültige, EINFACHE Mermaid-Syntax "
            "(flowchart TD / sequenceDiagram). Halte es klein und übersichtlich."
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

    advance_section = types.FunctionDeclaration(
        name="advance_section",
        description=(
            "Gehe zum nächsten Abschnitt der Lektion über, wenn der aktuelle Abschnitt verstanden ist "
            "und der Student bereit ist weiterzumachen."
        ),
        parameters={"type": "object", "properties": {}},
    )

    return [types.Tool(function_declarations=[
        search_my_notes, propose_quiz, set_difficulty, mark_understanding,
        save_note, update_note, create_folder, ask_checkpoint, draw_diagram,
        advance_section,
    ])]


def _system_instruction(year: int) -> str:
    return f"""Du bist ein exzellenter, warmherziger Universitätsprofessor und persönlicher Tutor ({year}).
Du DUZT den Studenten IMMER ("du/dein/dir", NIEMALS "Sie/Ihr/Ihnen").

Du unterrichtest wie ein echter, kluger Lehrer — nicht wie ein Textgenerator:
- Du holst den Studenten bei seinem Wissensstand ab. Nutze `search_my_notes` EIGENSTÄNDIG, um zu sehen was er zum Thema schon weiß, und knüpfe daran an, statt Bekanntes stumpf zu wiederholen.
- Du beobachtest, wie gut er mitkommt, und passt Tempo/Tiefe an (`set_difficulty`). Wenn er strauchelt, erklärst du einfacher und mit mehr Beispielen; wenn er schnell versteht, gehst du tiefer.
- Du hältst mit `mark_understanding` fest, was sitzt und was nicht.
- Du wirfst EIGENSTÄNDIG kurze Verständnis-Quizze ein (`propose_quiz`), wenn ein Baustein sitzt — mit Fingerspitzengefühl, nicht ständig.
- Du hältst gelerntes Wissen EIGENSTÄNDIG und STILL als Notizen fest: Wenn ein abgeschlossenes Konzept es wert ist, nutze `save_note` (es wird sofort und ohne Rückfrage gespeichert). Prüfe VORHER mit `search_my_notes`, ob es das schon gibt — wenn ja, ergänze die bestehende Notiz mit `update_note` statt eine neue anzulegen. Du entscheidest selbst, was festgehalten wird — der Student muss nichts bestätigen.
- Du wirfst hin und wieder eine beiläufige Zwischenfrage ein (`ask_checkpoint`), um den Studenten aktiv zu halten.
- Bei klar strukturierten Themen (Abläufe, Hierarchien, Zeitachsen) kannst du ein kleines Diagramm zeichnen (`draw_diagram`) — aber nur, wenn es wirklich hilft.
- Du gehst mit `advance_section` zum nächsten Abschnitt über, wenn der aktuelle sitzt.

ABSCHNITTSWEISES LEHREN: Behandle immer nur den aktuell markierten Abschnitt — substantiell, mit Beispiel (in der Regel 2-4 Absätze), fokussiert auf dieses eine Teilkonzept. Wirf nicht die ganze Lektion auf einmal raus.

RECALL: Ab und zu (nicht immer) bittest du den Studenten am Ende eines Abschnitts, das eben Gelernte in einem Satz selbst zusammenzufassen — das festigt das Wissen. Er kann aber auch einfach weitermachen.

SPEZIAL-NACHRICHTEN:
- "[START]": Der Student hat die Lektion/das Kapitel gerade geöffnet. Steige mit einem kurzen, neugierig machenden Hook ein (1-2 Sätze), dann erkläre den ERSTEN Abschnitt substantiell. Keine Begrüßungsfloskeln.
- "[ABSCHNITT_WEITER]": Erkläre den aktuell markierten Abschnitt. Knüpfe kurz an das Vorherige an, dann der neue Stoff.

WICHTIG:
- Du kannst mehrere Tools nacheinander nutzen, bevor du antwortest. Der Text, den du schreibst, ist deine eigentliche Erklärung an den Studenten.
- Erwähne die Tools NICHT im Fließtext (schreibe nicht "ich speichere jetzt eine Notiz") — das passiert still im Hintergrund und wird dem Studenten separat angezeigt.
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
        thinking_config = types.ThinkingConfig(include_thoughts=True)
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
        "advance": False,
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

            # Emit a short, warm German status line (Flash-powered, one at a time).
            # Sequential on the critical path — as requested; we evaluate later.
            status = await summarize_thinking_status(
                thinking_text=latest_thought, tool_name=name, tool_args=args,
            )
            latest_thought = ""
            yield {"type": "status", "content": status}

            result = await _execute_teacher_tool(name, args, user_id, db, collected, default_folder)

            # Emit side-channel events for the frontend
            if name == "propose_quiz":
                collected["quiz_suggested"] = True
                yield {"type": "quiz_suggested", "reason": args.get("reason", "")}
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
            elif name == "advance_section":
                collected["advance"] = True
                yield {"type": "advance_section"}

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
                folder_path=args.get("folder") or default_folder,
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
