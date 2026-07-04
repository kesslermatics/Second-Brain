"""Infinite Teacher service — curriculum generation, interactive teaching chat, note generation.

Knowledge-aware: the teacher inspects the user's existing Second Brain notes and
builds lessons, curricula and notes on top of what the student already has.
Uses native structured JSON output instead of regex extraction where possible.
"""

from app.services.ai_service import (
    generate_with_search, generate, generate_stream, generate_with_search_stream,
    generate_json, generate_with_search_sources, PRO_MODEL, FLASH_MODEL,
)
from app.config import get_settings
import json
import re
import logging
from datetime import datetime


# ── Knowledge-base awareness ──────────────────────────────────────────

async def get_relevant_knowledge(
    query: str,
    user_id: str,
    db,
    limit: int = 8,
) -> list[dict]:
    """Search the user's existing notes for a topic. Returns lightweight hits.

    Used to make the teacher build on what the student already has instead of
    starting every lesson from scratch. Fails soft — returns [] on any error.
    """
    if not user_id or db is None:
        return []
    try:
        from app.services.vector_service import hybrid_search
        results = await hybrid_search(query=query, user_id=str(user_id), db=db, limit=limit)
        return [
            {
                "note_id": r["note_id"],
                "title": r["title"],
                "folder_path": r.get("folder_path", ""),
                "preview": (r.get("content_preview") or "")[:400],
            }
            for r in results
        ]
    except Exception as e:
        logging.getLogger(__name__).warning(f"get_relevant_knowledge failed: {e}")
        return []


def _format_knowledge_block(hits: list[dict], label: str = "BEREITS VORHANDENES WISSEN DES STUDENTEN") -> str:
    """Render knowledge-base hits into a prompt block. Empty string when no hits."""
    if not hits:
        return ""
    lines = [f"\n{label} (aus seinem Second Brain — baue darauf auf, wiederhole es nicht stumpf):"]
    for h in hits:
        loc = f" [{h['folder_path']}]" if h.get("folder_path") else ""
        preview = (h.get("preview") or "").replace("\n", " ")
        if len(preview) > 220:
            preview = preview[:220] + "…"
        lines.append(f"- „{h['title']}\"{loc}: {preview}")
    lines.append(
        "Beziehe dieses Vorwissen aktiv ein: knüpfe daran an, verweise darauf, vertiefe es — "
        "aber wiederhole Bekanntes nicht ausführlich, sondern baue darauf auf."
    )
    return "\n".join(lines)


async def get_existing_note_titles(user_id: str, db, limit: int = 400) -> list[str]:
    """Return ALL note titles of the user (across courses) for cross-course dedup."""
    if not user_id or db is None:
        return []
    try:
        from sqlalchemy import select
        from app.models import Note
        from uuid import UUID
        result = await db.execute(
            select(Note.title).where(Note.user_id == UUID(str(user_id))).limit(limit)
        )
        return [row[0] for row in result.all()]
    except Exception as e:
        logging.getLogger(__name__).warning(f"get_existing_note_titles failed: {e}")
        return []

# Control messages that drive the lesson flow but are not real student input.
# They must be excluded from note generation, quiz/recap context, and "did the
# student write something" detection.
CONTROL_MESSAGES = ("[START]", "[NOTIZEN_ERSTELLT]", "[ABSCHNITT_WEITER]")

def _current_year() -> int:
    return datetime.now().year

def _extract_json(text: str) -> dict | None:
    """Robustly extract a JSON object from LLM response text.

    Handles markdown code fences, preamble text with braces,
    braces inside JSON string values, and truncated responses.
    """
    import logging
    logger = logging.getLogger(__name__)

    # 1. Strip markdown code fences
    cleaned = re.sub(r'```(?:json)?\s*', '', text).strip()

    # 2. Try direct parse
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # 3. Find the outermost JSON object using string-aware balanced braces
    def _find_json_object(s: str, start: int = 0) -> dict | None:
        """Find a balanced JSON object starting from position start, respecting strings."""
        i = s.find('{', start)
        if i == -1:
            return None

        depth = 0
        in_string = False
        escape_next = False

        for j in range(i, len(s)):
            c = s[j]
            if escape_next:
                escape_next = False
                continue
            if c == '\\' and in_string:
                escape_next = True
                continue
            if c == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    candidate = s[i:j + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # Try next opening brace
                        return _find_json_object(s, i + 1)
        return None

    result = _find_json_object(cleaned)
    if result:
        return result

    # 4. Try to repair truncated JSON (LLM output cut off)
    #    Find the start of the JSON, then try appending closing brackets
    first_brace = cleaned.find('{')
    if first_brace >= 0:
        fragment = cleaned[first_brace:]
        # Try progressively adding closing tokens
        for suffix in [
            '"}]}',      # truncated inside a string value in last note
            '"}]}',
            ']}'  ,      # truncated after last complete note
            '}'   ,      # truncated inside notes array
        ]:
            try:
                repaired = json.loads(fragment + suffix)
                if isinstance(repaired, dict):
                    logger.info("Repaired truncated JSON with suffix: %s", suffix)
                    return repaired
            except (json.JSONDecodeError, ValueError):
                continue

        # More aggressive: try to close all open braces/brackets
        open_braces = 0
        open_brackets = 0
        in_str = False
        esc = False
        for c in fragment:
            if esc:
                esc = False
                continue
            if c == '\\' and in_str:
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == '{':
                open_braces += 1
            elif c == '}':
                open_braces -= 1
            elif c == '[':
                open_brackets += 1
            elif c == ']':
                open_brackets -= 1

        if open_braces > 0 or open_brackets > 0:
            # We're in a truncated string value most likely — close it first
            closer = '"'
            closer += ']' * max(0, open_brackets)
            closer += '}' * max(0, open_braces)
            try:
                repaired = json.loads(fragment + closer)
                if isinstance(repaired, dict):
                    logger.info("Repaired truncated JSON by closing %d braces, %d brackets", open_braces, open_brackets)
                    return repaired
            except (json.JSONDecodeError, ValueError):
                pass

    logger.warning("Failed to extract JSON from LLM response: %s", text[:300])
    return None

import logging
_logger = logging.getLogger(__name__)

settings = get_settings()

# ── Shared formatting instructions for all teaching prompts ───────────
FORMATTING_RULES = """
Formatierungsregeln (SEHR WICHTIG — befolge jede einzelne):
- Strukturiere den Inhalt klar mit Markdown-Headings (##, ###)
- Verwende **Fettdruck** für Schlüsselbegriffe und wichtige Terme
- Verwende Aufzählungslisten für Hierarchien und Aufzählungen
- Verwende nummerierte Listen für Schritte und Abfolgen
- Verwende Callouts für wichtige Konzepte:
  > [!MERKSATZ]
  > Für Kernaussagen und Regeln

  > [!DEFINITION]
  > Für Begriffserklärungen

  > [!BEISPIEL]
  > Für konkrete Beispiele

  > [!WICHTIG]
  > Für besonders wichtige Hinweise

  > [!TIPP]
  > Für hilfreiche Tipps und Eselsbrücken

- MATHEMATISCHE FORMELN: Wenn das Thema mathematische Inhalte hat, verwende LaTeX-Notation:
  - Inline-Formeln: $E = mc^2$
  - Zentrierte Block-Formeln: $$\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}$$
  - Block-Formeln ($$...$$) sollen auf eigener Zeile stehen, zentriert
  - Verwende Mathe-Formeln NUR wenn sie zum Thema gehören — erzwinge keine Formeln bei nicht-mathematischen Themen
"""

ATOMIC_NOTE_RULES = """
Folge dem Prinzip der ATOMIC NOTES:
- Jede Notiz behandelt GENAU EIN Konzept, EINE Idee oder EINEN Begriff
- Der Titel ist das Thema/der Begriff selbst (NIEMALS "Kapitel X" oder "Stunde X")
- Die Notiz soll für sich allein verständlich sein
- Kurz und prägnant — lieber mehrere kleine Notizen als eine große
- Vermeide Verweise wie "wie in der vorherigen Stunde besprochen"
- Schreibe in sachlicher, neutraler, enzyklopädischer Form
"""


CURRICULUM_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "unit_number": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "learning_objectives": {"type": "array", "items": {"type": "string"}},
                    "level": {"type": "integer"},
                    "builds_on_existing": {"type": "boolean"},
                },
                "required": ["unit_number", "title", "level"],
            },
        },
    },
    "required": ["title", "description", "units"],
}


async def generate_curriculum(
    topic: str,
    parent_context: str | None = None,
    custom_focus: str | None = None,
    focus_description: str | None = None,
    num_lessons: int | None = None,
    user_id: str | None = None,
    db=None,
) -> dict:
    """Generate a full curriculum / study plan for a topic.

    Knowledge-aware: inspects the student's existing notes and tailors the plan
    so it builds on what they already know instead of restarting from zero.

    Args:
        topic: The course topic.
        parent_context: Summary of a parent course when extending an existing one.
        custom_focus: Short focus term (used by advanced-focus deepening).
        focus_description: Free-text description of what the student wants to emphasise / deepen.
        num_lessons: Desired number of lessons (level-2 units). When None the AI decides.
        user_id / db: enable knowledge-base awareness.

    Returns: {title, description, units: [{unit_number, title, description, learning_objectives, level}]}
    """
    # Knowledge-base awareness: what does the student already have on this topic?
    knowledge_hits = await get_relevant_knowledge(topic, user_id, db, limit=10) if user_id else []
    knowledge_block = _format_knowledge_block(knowledge_hits)
    if knowledge_block:
        knowledge_block += (
            "\n\nWICHTIG für den Lehrplan: Markiere Lektionen, die vorhandenes Wissen vertiefen, "
            "mit \"builds_on_existing\": true. Setze früh im Kurs dort an, wo der Student noch Lücken hat, "
            "und behandle bereits Gemeistertes kompakter."
        )

    context_section = ""
    if parent_context:
        context_section = f"""
KONTEXT — DIES IST EINE VERTIEFUNG EINES BESTEHENDEN KURSES:
{parent_context}

Der Studierende möchte auf diesem Basiskurs aufbauen. Beachte dabei:
- Baue auf dem bereits vermittelten Wissen auf und vertiefe es gezielt.
- Wiederhole KEINE bereits behandelten Themen aus dem Basiskurs, sondern gehe auf
  fortgeschrittene, weiterführende oder spezialisierte Aspekte ein.
- Knüpfe inhaltlich sinnvoll an die Lehrinhalte des Basiskurses an (gleiche Terminologie,
  passendes Niveau), sodass sich die Vertiefung wie eine natürliche Fortsetzung anfühlt.
"""
    if custom_focus:
        context_section += f"\nGEWÜNSCHTER SCHWERPUNKT: {custom_focus}\n"
    if focus_description:
        context_section += f"""
BESCHREIBUNG & VERTIEFUNG DES STUDENTEN (worauf besonderer Wert gelegt werden soll):
{focus_description}

Richte den Lehrplan gezielt an diesen Wünschen aus und vertiefe die genannten Aspekte.
"""

    # Lesson-count instruction — either honour the requested number or let the AI decide.
    if num_lessons and num_lessons > 0:
        lessons_instruction = (
            f"- Erstelle GENAU {num_lessons} Lektionen (level 2), aufgeteilt in eine sinnvolle "
            f"Anzahl von Modulen (level 1)"
        )
    else:
        lessons_instruction = (
            "- Erstelle einen UMFASSENDEN Lehrplan mit mindestens 5 Modulen und insgesamt 15-30 Lektionen"
        )

    year = _current_year()

    prompt = f"""Du bist ein exzellenter Universitätsprofessor und Lehrplanentwickler.
Wir befinden uns im Jahr {year}.
Erstelle einen vollständigen, strukturierten Lehrplan für das Thema:

"{topic}"

{context_section}

Der Lehrplan soll:
- Chronologisch logisch aufgebaut sein (vom Grundlegenden zum Komplexen)
- In Module (level 1) und Lektionen (level 2) unterteilt sein
- Jede Lektion soll ein konkretes Thema behandeln, das in einer Unterrichtsstunde vermittelt werden kann
- Themen sollen natürlich ineinander übergehen und aufeinander aufbauen
- Lernziele pro Lektion definieren (was der Student danach können/wissen soll)
- Praxisrelevant und tiefgehend sein, wie ein guter Universitätskurs

WICHTIG:
{lessons_instruction}
- Jede Lektion hat klare, messbare Lernziele
- Die Lektionsnamen sollen das THEMA beschreiben, nicht "Stunde 1" oder "Lektion 1"
- Module (level 1) sind übergeordnete Themenbereiche, Lektionen (level 2) sind die konkreten Unterrichtseinheiten
- unit_number als String: Module "1", "2", ...; Lektionen "1.1", "1.2", ...
- Bei Lektionen die vorhandenes Wissen des Studenten vertiefen: "builds_on_existing": true"""

    # Add knowledge-base awareness to the prompt
    if knowledge_block:
        prompt += "\n" + knowledge_block

    # Grounded research first (up-to-date facts), then structure into strict JSON.
    research, _sources = await generate_with_search_sources(
        f"Recherchiere Kernthemen, typische Curriculum-Struktur und aktuelle Entwicklungen zu: {topic}. "
        f"Gib eine kompakte, faktenbasierte Stoffsammlung als Grundlage für einen Lehrplan.",
        model=PRO_MODEL,
    )
    if research:
        prompt += f"\n\nRECHERCHE-GRUNDLAGE (aktuell recherchiert):\n{research[:4000]}"

    result = await generate_json(prompt, CURRICULUM_SCHEMA, model=PRO_MODEL, temperature=0.6)
    if result and isinstance(result, dict) and result.get("units"):
        return {
            "title": result.get("title", topic),
            "description": result.get("description", ""),
            "units": result.get("units", []),
        }

    # Fallback: legacy free-text + regex extraction
    text = (await generate_with_search(prompt, model=PRO_MODEL)).strip()
    parsed = _extract_json(text)
    if parsed:
        return {
            "title": parsed.get("title", topic),
            "description": parsed.get("description", ""),
            "units": parsed.get("units", []),
        }

    return {"title": topic, "description": "", "units": []}


async def chat_with_teacher(
    course_title: str,
    unit_title: str,
    unit_description: str,
    learning_objectives: list[str],
    chat_history: list[dict],
    user_message: str,
    previous_units_summary: str | None = None,
    next_unit_title: str | None = None,
    sections: list[dict] | None = None,
    current_section: int = 0,
) -> str:
    """Send a message to the AI teacher and get a response.

    The teacher explains concepts conversationally, answers questions,
    and guides the student through the lesson.
    """
    objectives_str = "\n".join(f"  - {o}" for o in learning_objectives) if learning_objectives else "  (keine spezifischen Lernziele definiert)"

    prev_context = ""
    if previous_units_summary:
        prev_context = f"""
BEREITS BEHANDELTE THEMEN (Kontext aus vorherigen Lektionen):
{previous_units_summary}
Du kannst auf dieses Vorwissen aufbauen, ohne es komplett zu wiederholen.
"""

    next_hint = ""
    if next_unit_title:
        next_hint = f"\nNÄCHSTES THEMA im Kurs: \"{next_unit_title}\" — du kannst gegen Ende der Lektion natürlich dorthin überleiten."

    # Build conversation for Gemini
    history_text = ""
    for msg in chat_history[-20:]:  # Keep last 20 messages for context
        role_label = "Student" if msg["role"] == "user" else "Lehrer"
        if msg["role"] == "note_generated":
            history_text += f"\n[System: Notiz wurde generiert: {msg.get('content', '')[:100]}]\n"
        else:
            history_text += f"\n{role_label}: {msg['content']}\n"

    year = _current_year()

    sections_block = _build_sections_block(sections, current_section)
    sections_section = f"\n{sections_block}\n" if sections_block else ""

    prompt = f"""Du bist ein freundlicher, geduldiger und kompetenter Universitätsprofessor.
Wir befinden uns im Jahr {year}.
Du DUZT den Studenten IMMER ("du", "dein", "dir" — NIEMALS "Sie", "Ihr", "Ihnen").
Du unterrichtest gerade den Kurs "{course_title}".

AKTUELLE LEKTION: "{unit_title}"
{unit_description}

LERNZIELE dieser Lektion:
{objectives_str}
{prev_context}{next_hint}
{sections_section}
BISHERIGER GESPRÄCHSVERLAUF:
{history_text}

NEUE NACHRICHT DES STUDENTEN:
{user_message}

DEINE AUFGABE:
- ABSCHNITTSWEISES LEHREN: Diese Lektion ist in Abschnitte unterteilt (siehe oben). Du behandelst IMMER NUR den aktuell markierten Abschnitt. Du springst NICHT vor und wirfst nicht die ganze Lektion auf einmal raus — das überfordert und wird nicht gelesen.
- BALANCE IN DEN ANTWORTEN: Erkläre den aktuellen Abschnitt substantiell genug, dass der Student wirklich etwas lernt (mit Beispiel), aber halte es fokussiert auf DIESES eine Teilkonzept. In der Regel 2-4 Absätze.
- Wenn der Student eine Frage zum aktuellen Abschnitt stellt, beantworte sie ausführlich, bevor es weitergeht.
- Erkläre Konzepte einfach, klar und angenehm — wie ein guter Tutor, mit Beispielen und Analogien.
- Wenn der Student nach einer Notiz fragt oder sagt, er will eine Notiz erstellen, signalisiere das mit dem speziellen Marker [NOTIZ_ANFRAGE: Thema der gewünschten Notiz]
- SPEZIAL-NACHRICHTEN:
  - "[START]": Der Student hat die Lektion gerade geöffnet. Beginne mit dem ERSTEN Abschnitt:
    * Verzichte auf Begrüßungsfloskeln wie "Hallo, schön dass du wieder da bist" — die Lektionsziele werden dem Studenten bereits separat angezeigt.
    * Steige mit einem kurzen, neugierig machenden Hook ein (1-2 Sätze: warum ist das Thema spannend/relevant?).
    * Erkläre dann den ERSTEN Abschnitt substantiell mit Beispiel (2-4 Absätze). NICHT die ganze Lektion.
    * Beende mit einer kurzen Verständnisfrage oder dem Hinweis, dass es danach mit dem nächsten Abschnitt weitergeht.
  - "[ABSCHNITT_WEITER]": Der Student möchte zum nächsten Abschnitt. Erkläre jetzt den oben als AKTUELL markierten Abschnitt — substantiell mit Beispiel, fokussiert auf dieses eine Teilkonzept. Knüpfe kurz an das Vorherige an (1 Satz), dann der neue Stoff.
  - "[NOTIZEN_ERSTELLT]": Es wurden gerade Notizen zum aktuellen Thema erstellt und gespeichert. Frage den Studenten freundlich und kurz (2-3 Sätze), ob er noch Fragen zum aktuellen Abschnitt hat oder ob er bereit ist, weiterzumachen.
{FORMATTING_RULES}

HINWEIS zu Mathe-Formeln: Wenn das Thema mathematische Inhalte hat, verwende die LaTeX-Notation ($...$ inline, $$...$$ als Block). Bei nicht-mathematischen Themen verwende KEINE Formeln.

Antworte auf Deutsch (oder in der Sprache, die der Student verwendet).
Sei warmherzig aber sachlich. Kein Smalltalk — fokussiere dich auf den Lehrinhalt.
WICHTIG: DUZE den Studenten IMMER. Verwende "du/dein/dir", NIEMALS "Sie/Ihr/Ihnen"."""

    return (await generate_with_search(prompt, model=PRO_MODEL)).strip()


# Guidance that turns the tutor into a proactive, adaptive teacher who decides
# on their own when a quick knowledge check makes sense.
ADAPTIVE_TEACHING_RULES = """
ADAPTIVES UNTERRICHTEN — verhalte dich wie ein echter, kluger Lehrer:
- Greife auf, was der Student schon kann (siehe Vorwissen) und hole ihn dort ab. Wiederhole Bekanntes nicht stumpf, sondern knüpfe daran an.
- Beobachte das Verständnis: Wenn der Student sichtlich Schwierigkeiten hat, erkläre einfacher, mit mehr Beispielen und langsamer. Wenn er schnell versteht, erhöhe das Tempo und die Tiefe.
- Wenn ein sinnvoller Wissensbaustein abgeschlossen ist (z.B. ein Abschnitt sitzt, oder mehrere Konzepte behandelt wurden), kannst du EIGENSTÄNDIG ein kurzes Verständnis-Quiz vorschlagen. Setze dazu GANZ AM ENDE deiner Nachricht in einer eigenen Zeile den Marker: [QUIZ_VORSCHLAG]
  - Nutze das mit Fingerspitzengefühl — nicht nach jeder Nachricht, sondern wenn es didaktisch Sinn ergibt (nach einem abgeschlossenen Thema, vor dem Übergang zum nächsten Abschnitt).
  - Erwähne den Marker NICHT im Fließtext; er wird technisch ausgewertet und dem Studenten als Button angeboten.
- Passe die Schwierigkeit des kommenden Stoffs an das bisher gezeigte Niveau an."""


async def chat_with_teacher_stream(
    course_title: str,
    unit_title: str,
    unit_description: str,
    learning_objectives: list[str],
    chat_history: list[dict],
    user_message: str,
    previous_units_summary: str | None = None,
    next_unit_title: str | None = None,
    sections: list[dict] | None = None,
    current_section: int = 0,
    knowledge_hits: list[dict] | None = None,
):
    """Streaming variant of chat_with_teacher. Yields SSE event dicts."""
    objectives_str = "\n".join(f"  - {o}" for o in learning_objectives) if learning_objectives else ""
    prev_context = f"\nBEREITS BEHANDELT:\n{previous_units_summary}\n" if previous_units_summary else ""
    next_hint = f'\nNÄCHSTES THEMA: "{next_unit_title}"' if next_unit_title else ""
    knowledge_block = _format_knowledge_block(knowledge_hits) if knowledge_hits else ""
    history_text = ""
    for msg in chat_history[-20:]:
        role_label = "Student" if msg["role"] == "user" else "Lehrer"
        if msg["role"] != "note_generated":
            history_text += f"\n{role_label}: {msg['content']}\n"
    year = _current_year()
    sections_block = _build_sections_block(sections, current_section)
    sections_section = f"\n{sections_block}\n" if sections_block else ""

    prompt = f"""Du bist ein freundlicher, kompetenter Universitätsprofessor ({year}). Du DUZT den Studenten IMMER.
Kurs: "{course_title}" | Lektion: "{unit_title}"
{unit_description}
Lernziele: {objectives_str}
{prev_context}{next_hint}{knowledge_block}{sections_section}
GESPRÄCHSVERLAUF:{history_text}

STUDENT: {user_message}

Erkläre den aktuellen Abschnitt substantiell mit Beispiel (2-4 Absätze). Fokussiere auf dieses Teilkonzept.
{ADAPTIVE_TEACHING_RULES}
{FORMATTING_RULES}
Antworte auf Deutsch. DUZE den Studenten."""

    async for event in generate_with_search_stream(prompt, model=PRO_MODEL):
        yield event


async def generate_lesson_notes(
    course_title: str,
    unit_title: str,
    unit_number: str,
    unit_description: str,
    learning_objectives: list[str],
    chat_history: list[dict],
    existing_tags: list[str] | None = None,
    existing_note_titles: list[str] | None = None,
) -> list[dict]:
    """Generate atomic notes for the current lesson based on what was discussed.

    Returns a list of notes: [{title, content, suggested_tags, suggested_folder}]
    """
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    objectives_str = "\n".join(f"  - {o}" for o in learning_objectives) if learning_objectives else ""

    # Compress chat history for context — use generous limit so notes cover everything
    chat_text = ""
    for msg in chat_history[-30:]:
        role_label = "Student" if msg["role"] == "user" else "Lehrer"
        if msg["role"] != "note_generated" and msg.get("content", "") not in CONTROL_MESSAGES:
            chat_text += f"{role_label}: {msg['content'][:3000]}\n"

    # Determine if chat is too short for conversation-based notes
    thin_chat = len(chat_text.strip()) < 200

    if thin_chat:
        context_block = f"""HINWEIS: Das Gespräch ist noch sehr kurz. Generiere die Notizen basierend auf dem
Thema der Lektion selbst. Nutze dein Wissen und aktuelle Recherche, um hochwertige Notizen
zu den Kernkonzepten der Lektion zu erstellen.

BISHERIGER GESPRÄCHSVERLAUF (kurz):
{chat_text if chat_text.strip() else '(Noch kein inhaltliches Gespräch)'}"""
    else:
        context_block = f"""GESPRÄCHSVERLAUF:
{chat_text}"""

    # Build deduplication context
    dedup_block = ""
    if existing_note_titles:
        titles_list = "\n".join(f"- {t}" for t in existing_note_titles)
        dedup_block = f"""
BEREITS EXISTIERENDE NOTIZEN zu diesem Kurs (aus vorherigen Lektionen):
{titles_list}

WICHTIGE REGEL ZUR VERMEIDUNG VON DUPLIKATEN:
- Erstelle KEINE neuen Atomic Notes für Konzepte, die oben bereits als Notiz existieren.
- Wenn ein Konzept aus dieser Lektion bereits als Notiz existiert, erwähne es nur kurz in der Überblicksnotiz und verweise darauf, statt eine neue Notiz zu erstellen.
- Verwende ANDERE Beispiele als in vorherigen Lektionen — bringe frische, lektionsspezifische Beispiele.
- Erstelle nur Notizen für NEUE Konzepte, die in den bisherigen Notizen noch nicht behandelt wurden.
"""

    prompt = f"""Du bist ein Second Brain Assistent.
Basierend auf {'der Lektion' if thin_chat else 'dem folgenden Unterrichtsgespräch'} sollst du Notizen erstellen.

KURS: "{course_title}"
LEKTION {unit_number}: "{unit_title}"
{unit_description}

LERNZIELE:
{objectives_str}

{context_block}
{dedup_block}
STRUKTUR DER NOTIZEN:
1. ERSTE NOTIZ = ÜBERBLICKSNOTIZ: Eine zusammenfassende Notiz mit dem Titel "Lektion {unit_number}: {unit_title}".
   Diese fasst die gesamte Lektion kompakt zusammen: Kernaussagen, wichtige Konzepte, Zusammenhänge.
   Sie dient als Einstiegspunkt und gibt einen Überblick über die gesamte Lektion.
2. WEITERE NOTIZEN = ATOMIC NOTES: Für jedes wichtige Einzelkonzept eine eigene kurze Notiz.
   {ATOMIC_NOTE_RULES}

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen.

{FORMATTING_RULES}

Antworte NUR mit dem JSON, kein anderer Text:
{{
    "notes": [
        {{
            "title": "Lektion {unit_number}: {unit_title}",
            "content": "Überblick über die gesamte Lektion...",
            "suggested_tags": ["tag1", "tag2"],
            "suggested_folder": "Kurse/{course_title}"
        }},
        {{
            "title": "Konzeptname als Titel",
            "content": "Atomic Note Inhalt...",
            "suggested_tags": ["tag1"],
            "suggested_folder": "Kurse/{course_title}"
        }}
    ]
}}"""

    text = (await generate_with_search(prompt, model=PRO_MODEL)).strip()

    result = _extract_json(text)
    if result:
        notes = result.get("notes", [])
        # Fallback: if _extract_json found a single note object instead of the wrapper
        if not notes and "title" in result and "content" in result:
            notes = [result]
        for note in notes:
            note.setdefault("suggested_folder", f"Kurse/{course_title}")
            note.setdefault("suggested_tags", [])
        if notes:
            return notes
        _logger.warning("LLM returned empty notes array for lesson %s", unit_title)

    _logger.warning("Failed to generate lesson notes for %s — raw: %s", unit_title, text[:500])
    return []


async def generate_term_note(
    term: str,
    course_title: str,
    unit_title: str,
    chat_history: list[dict],
    existing_tags: list[str] | None = None,
) -> dict:
    """Generate a single atomic note for a specific term/concept.

    Returns: {title, content, suggested_tags, suggested_folder}
    """
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    # Compress recent chat for context
    chat_text = ""
    for msg in chat_history[-10:]:
        role_label = "Student" if msg["role"] == "user" else "Lehrer"
        if msg["role"] != "note_generated" and msg.get("content", "") not in CONTROL_MESSAGES:
            chat_text += f"{role_label}: {msg['content'][:1500]}\n"

    prompt = f"""Du bist ein Second Brain Assistent.
Erstelle eine ATOMIC NOTE zum folgenden Begriff:

BEGRIFF: "{term}"
KONTEXT: Kurs "{course_title}", Lektion "{unit_title}"

Aktueller Gesprächskontext:
{chat_text}

{ATOMIC_NOTE_RULES}
{FORMATTING_RULES}

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen.

Antworte NUR mit dem JSON, kein anderer Text:
{{
    "title": "{term}",
    "content": "Markdown-formatierter Inhalt der Notiz",
    "suggested_tags": ["tag1", "tag2"],
    "suggested_folder": "Kurse/{course_title}"
}}"""

    text = (await generate_with_search(prompt)).strip()

    result = _extract_json(text)
    if result:
        return {
            "title": result.get("title", term),
            "content": result.get("content", ""),
            "suggested_tags": result.get("suggested_tags", []),
            "suggested_folder": result.get("suggested_folder", f"Kurse/{course_title}"),
        }

    return {
        "title": term,
        "content": f"Fehler beim Generieren der Notiz für '{term}'.",
        "suggested_tags": [],
        "suggested_folder": f"Kurse/{course_title}",
    }


async def generate_advanced_focus(
    course_title: str,
    course_topic: str,
    completed_units_summary: str,
) -> list[dict]:
    """Generate follow-up / advanced specialization suggestions.

    Returns: [{title, description, topic}]
    """
    prompt = f"""Du bist ein Studienberater und Lehrplanentwickler.
Du DUZT den Studierenden.

Der Studierende hat folgenden Kurs abgeschlossen:
KURS: "{course_title}" (Thema: {course_topic})

BEHANDELTE INHALTE:
{completed_units_summary}

Schlage 3-5 VERTIEFENDE SCHWERPUNKTE vor, die der Studierende als nächstes studieren könnte.
Diese sollen:
- Auf dem erlernten Wissen aufbauen
- Fortgeschrittene oder spezialisierte Aspekte des Themas abdecken
- Wie Master-/Vertiefungsmodule sein
- Praktisch relevant und interessant sein

Antworte NUR mit dem JSON:
{{
    "suggestions": [
        {{
            "title": "Kurzer, prägnanter Titel des Schwerpunkts",
            "description": "2-3 Sätze, was in diesem Schwerpunkt behandelt wird",
            "topic": "Das Thema für die Curriculum-Generierung"
        }}
    ]
}}"""

    text = (await generate_with_search(prompt)).strip()

    result = _extract_json(text)
    if result:
        return result.get("suggestions", [])

    return []


async def ai_edit_lesson_content(current_content: str, instruction: str) -> str:
    """Edit a lesson note based on user instruction."""
    prompt = f"""Du bist ein Second Brain Assistent. Bearbeite die folgende Notiz basierend auf der Anweisung.

AKTUELLE NOTIZ:
{current_content}

ANWEISUNG: {instruction}

{FORMATTING_RULES}
{ATOMIC_NOTE_RULES}

Gib NUR den neuen, vollständigen Notiz-Inhalt zurück (Markdown). Kein JSON, keine Erklärung, nur der Inhalt."""

    return (await generate(prompt)).strip()


# ── Lesson sections (break a lesson into walk-through steps) ──────────

async def generate_lesson_sections(
    title: str,
    description: str,
    learning_objectives: list[str],
    kind: str = "lesson",
    book_title: str | None = None,
    book_authors: list[str] | None = None,
) -> list[dict]:
    """Break a single lesson / book chapter into a handful of teachable sections.

    Each section is one focused step the tutor walks the student through, one at a
    time, so a lesson becomes a guided sequence instead of one wall of text.

    Returns a list: [{"title": str, "focus": str}]
    """
    objectives_str = "\n".join(f"  - {o}" for o in learning_objectives) if learning_objectives else "  (keine spezifischen Lernziele)"

    if kind == "book":
        authors_str = ", ".join(book_authors) if book_authors else "unbekannter Autor"
        subject_block = (
            f'BUCH: "{book_title}" von {authors_str}\n'
            f'KAPITEL: "{title}"'
        )
        subject_word = "des Kapitels"
        research_hint = (
            "Recherchiere bei Bedarf den tatsächlichen Inhalt dieses Kapitels und teile ihn "
            "in eine sinnvolle Reihenfolge von Lernabschnitten ein.\n"
        )
    else:
        subject_block = f'LEKTION: "{title}"\n{description}'
        subject_word = "der Lektion"
        research_hint = ""

    prompt = f"""Du bist ein erfahrener Didaktiker. Teile die folgende Lerneinheit in eine
sinnvolle Abfolge kleiner, fokussierter ABSCHNITTE ein, die ein Tutor nacheinander mit dem
Studenten durchgeht. Jeder Abschnitt behandelt EIN Teilkonzept {subject_word}.

{subject_block}

LERNZIELE:
{objectives_str}

{research_hint}REGELN:
- Erstelle 3 bis 6 Abschnitte (je nach Umfang des Themas) — nicht mehr, nicht weniger
- Die Abschnitte bauen logisch aufeinander auf (vom Grundlegenden zum Komplexeren)
- Jeder Abschnitt ist ein abgeschlossener Lernschritt, den man in 1-3 Tutor-Nachrichten erklären kann
- Der letzte Abschnitt soll das Gelernte abrunden / zusammenführen
- Der "title" ist kurz und konkret (das Teilkonzept selbst, NICHT "Abschnitt 1")
- Der "focus" beschreibt in 1-2 Sätzen, was in diesem Abschnitt genau vermittelt wird

Antworte NUR mit dem JSON, kein anderer Text:
{{
    "sections": [
        {{"title": "Konkretes Teilkonzept", "focus": "Was in diesem Abschnitt vermittelt wird"}}
    ]
}}"""

    text = (await generate_with_search(prompt)).strip()

    result = _extract_json(text)
    if result:
        sections = result.get("sections", [])
        clean: list[dict] = []
        for s in sections:
            t = (s.get("title") or "").strip()
            if not t:
                continue
            clean.append({"title": t, "focus": (s.get("focus") or "").strip()})
        if clean:
            return clean

    _logger.warning("Failed to generate sections for %s — raw: %s", title, text[:300])
    # Fallback: a single section covering the whole lesson
    return [{"title": title, "focus": description or ""}]


def _build_sections_block(
    sections: list[dict] | None,
    current_section: int,
) -> str:
    """Build the prompt block describing the lesson's section plan and where we are."""
    if not sections:
        return ""
    lines = ["AUFBAU DIESER EINHEIT (Abschnitte, die nacheinander durchgegangen werden):"]
    for i, s in enumerate(sections):
        marker = "→ AKTUELL" if i == current_section else ("✓ erledigt" if i < current_section else "")
        title = s.get("title", f"Abschnitt {i + 1}")
        lines.append(f"  {i + 1}. {title} {marker}".rstrip())
    current = sections[current_section] if 0 <= current_section < len(sections) else None
    is_last = current_section >= len(sections) - 1
    if current:
        lines.append("")
        lines.append(f'DU BEHANDELST JETZT ABSCHNITT {current_section + 1}/{len(sections)}: "{current.get("title", "")}"')
        if current.get("focus"):
            lines.append(f'Fokus dieses Abschnitts: {current["focus"]}')
        lines.append(
            "Erkläre AUSSCHLIESSLICH diesen Abschnitt — substantiell, mit Beispiel, so dass der "
            "Student ihn versteht. Gehe NICHT zu späteren Abschnitten über; die kommen später dran."
        )
        if is_last:
            lines.append("Dies ist der LETZTE Abschnitt — runde die Einheit am Ende sauber ab.")
        else:
            lines.append(
                'Wenn du diesen Abschnitt erklärt hast, beende mit einer kurzen Verständnisfrage '
                'oder einem Hinweis, dass es mit dem nächsten Abschnitt weitergeht.'
            )
    return "\n".join(lines)


# ── Quiz & Recap (gamified lesson rhythm) ─────────────────────────────

def _build_quiz_context(chat_history: list[dict] | None, limit: int = 30) -> str:
    """Compress chat history into a context string for quiz/recap generation."""
    if not chat_history:
        return ""
    chat_text = ""
    for msg in chat_history[-limit:]:
        if msg["role"] in ("user", "assistant"):
            role_label = "Student" if msg["role"] == "user" else "Lehrer"
            content = msg.get("content", "")
            if content in CONTROL_MESSAGES:
                continue
            chat_text += f"{role_label}: {content[:2000]}\n"
    return chat_text


async def generate_quiz(
    title: str,
    description: str,
    learning_objectives: list[str],
    chat_history: list[dict] | None = None,
    kind: str = "lesson",
    book_title: str | None = None,
    num_questions: int = 3,
) -> list[dict]:
    """Generate a short multiple-choice quiz to check understanding.

    Works for both lessons and book chapters. Returns a list of questions:
    [{question, options: [str, ...], correct_index: int, explanation}]
    """
    subject = "des Buchkapitels" if kind == "book" else "der Lektion"
    objectives_str = "\n".join(f"  - {o}" for o in learning_objectives) if learning_objectives else ""

    chat_text = _build_quiz_context(chat_history)
    if chat_text.strip():
        context_block = f"BISHER BESPROCHENER INHALT:\n{chat_text}"
    else:
        context_block = (
            f"HINWEIS: Es gibt noch kaum Gesprächsverlauf. Erstelle die Fragen anhand des Themas "
            f"{subject} selbst und nutze dein Wissen."
        )

    book_line = f'BUCH: "{book_title}"\n' if book_title else ""

    prompt = f"""Du bist ein motivierender Tutor und erstellst ein kurzes, spielerisches Quiz,
um das Verständnis {subject} zu überprüfen. Du DUZT den Studenten.

{book_line}THEMA: "{title}"
{description}

LERNZIELE:
{objectives_str}

{context_block}

AUFGABE: Erstelle GENAU {num_questions} Multiple-Choice-Fragen, die das Verständnis der
Kernkonzepte prüfen. Regeln:
- Jede Frage hat genau 4 Antwortmöglichkeiten, von denen GENAU EINE richtig ist
- Die Fragen sollen das Verständnis prüfen, nicht stures Auswendiglernen — gerne kleine Anwendungsszenarien
- Variiere die Position der richtigen Antwort (nicht immer dieselbe)
- Formuliere klar und nicht zu lang
- Gib zu jeder Frage eine kurze, freundliche Erklärung, warum die richtige Antwort korrekt ist
- Schreibe auf Deutsch (oder in der Sprache des bisherigen Gesprächs)

Antworte NUR mit dem JSON, kein anderer Text:
{{
    "questions": [
        {{
            "question": "Fragetext?",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct_index": 0,
            "explanation": "Kurze Erklärung, warum die Antwort richtig ist."
        }}
    ]
}}"""

    text = (await generate(prompt)).strip()

    result = _extract_json(text)
    if result:
        questions = result.get("questions", [])
        # Sanitise: ensure correct_index is valid and options exist
        clean: list[dict] = []
        for q in questions:
            opts = q.get("options") or []
            if not isinstance(opts, list) or len(opts) < 2:
                continue
            try:
                idx = int(q.get("correct_index", 0))
            except (ValueError, TypeError):
                idx = 0
            if idx < 0 or idx >= len(opts):
                idx = 0
            clean.append({
                "question": q.get("question", ""),
                "options": opts,
                "correct_index": idx,
                "explanation": q.get("explanation", ""),
            })
        if clean:
            return clean

    _logger.warning("Failed to generate quiz for %s — raw: %s", title, text[:300])
    return []


async def generate_recap(
    title: str,
    description: str,
    learning_objectives: list[str],
    chat_history: list[dict] | None = None,
    kind: str = "lesson",
    book_title: str | None = None,
    next_title: str | None = None,
) -> dict:
    """Generate a short celebratory recap shown when a lesson/chapter is completed.

    Returns: {summary_points: [str, ...], next_preview: str}
    """
    subject = "des Buchkapitels" if kind == "book" else "der Lektion"
    objectives_str = "\n".join(f"  - {o}" for o in learning_objectives) if learning_objectives else ""

    chat_text = _build_quiz_context(chat_history)
    if chat_text.strip():
        context_block = f"GESPRÄCHSVERLAUF:\n{chat_text}"
    else:
        context_block = (
            f"HINWEIS: Es gibt kaum Gesprächsverlauf. Fasse die Kernpunkte {subject} "
            f"anhand des Themas selbst zusammen."
        )

    book_line = f'BUCH: "{book_title}"\n' if book_title else ""
    next_block = ""
    if next_title:
        next_unit_word = "Das nächste Kapitel" if kind == "book" else "Die nächste Lektion"
        next_block = f'\n{next_unit_word}: "{next_title}" — gib einen kurzen, neugierig machenden Ausblick darauf.'
    else:
        next_block = "\nDies war die letzte Einheit — es gibt keinen Ausblick auf eine nächste Einheit."

    prompt = f"""Du bist ein motivierender Tutor. Der Student hat gerade {subject} "{title}" abgeschlossen.
Erstelle einen kurzen, motivierenden Rückblick. Du DUZT den Studenten.

{book_line}THEMA: "{title}"
{description}

LERNZIELE:
{objectives_str}

{context_block}
{next_block}

AUFGABE: Fasse zusammen, was der Student gerade gelernt hat — kurz, knackig, motivierend.
Antworte NUR mit dem JSON, kein anderer Text:
{{
    "summary_points": [
        "Kurzer Stichpunkt zu einem Kernkonzept, das gelernt wurde",
        "Weiterer Kernpunkt",
        "Noch ein Kernpunkt"
    ],
    "next_preview": "Ein bis zwei Sätze Ausblick auf das nächste Thema (leer lassen wenn es keins gibt)."
}}

Regeln:
- 2 bis 4 Stichpunkte, jeder ein kurzer, vollständiger Satz
- Beziehe dich konkret auf die Inhalte, nicht generisch
- Schreibe auf Deutsch (oder in der Sprache des Gesprächs)"""

    text = (await generate(prompt)).strip()

    result = _extract_json(text)
    if result:
        return {
            "summary_points": result.get("summary_points", []),
            "next_preview": result.get("next_preview", ""),
        }

    _logger.warning("Failed to generate recap for %s — raw: %s", title, text[:300])
    return {"summary_points": [], "next_preview": ""}


# ── Book Chapter Interactive Teaching ─────────────────────────────────

async def chat_about_book_chapter(
    book_title: str,
    book_authors: list[str],
    chapter_number: str,
    chapter_title: str,
    chat_history: list[dict],
    user_message: str,
    previous_chapters_summary: str | None = None,
    next_chapter_title: str | None = None,
    sections: list[dict] | None = None,
    current_section: int = 0,
) -> str:
    """Chat about a specific book chapter, explaining its content interactively."""
    year = _current_year()
    authors_str = ", ".join(book_authors) if book_authors else "unbekannter Autor"

    prev_context = ""
    if previous_chapters_summary:
        prev_context = f"""
BEREITS BEHANDELTE KAPITEL (Kontext):
{previous_chapters_summary}
Du kannst auf dieses Vorwissen aufbauen, ohne es komplett zu wiederholen.
"""

    next_hint = ""
    if next_chapter_title:
        next_hint = f'\nNÄCHSTES KAPITEL im Buch: "{next_chapter_title}" — du kannst gegen Ende natürlich dorthin überleiten.'

    history_text = ""
    for msg in chat_history[-20:]:
        role_label = "Student" if msg["role"] == "user" else "Tutor"
        if msg["role"] == "note_generated":
            history_text += f"\n[System: Notiz wurde generiert: {msg.get('content', '')[:100]}]\n"
        else:
            history_text += f"\n{role_label}: {msg['content']}\n"

    sections_block = _build_sections_block(sections, current_section)
    sections_section = f"\n{sections_block}\n" if sections_block else ""

    prompt = f"""Du bist ein freundlicher, geduldiger und kompetenter Tutor, der einem Studenten beim Durcharbeiten eines Buches hilft.
Wir befinden uns im Jahr {year}.
Du DUZT den Studenten IMMER ("du", "dein", "dir" — NIEMALS "Sie", "Ihr", "Ihnen").

BUCH: "{book_title}" von {authors_str}
AKTUELLES KAPITEL: {chapter_number} — "{chapter_title}"
{prev_context}{next_hint}
{sections_section}
BISHERIGER GESPRÄCHSVERLAUF:
{history_text}

NEUE NACHRICHT DES STUDENTEN:
{user_message}

DEINE AUFGABE:
- Recherchiere zuerst den TATSÄCHLICHEN Inhalt dieses Kapitels aus dem Buch und erkläre ihn dann
- ABSCHNITTSWEISES LEHREN: Dieses Kapitel ist in Abschnitte unterteilt (siehe oben). Du behandelst IMMER NUR den aktuell markierten Abschnitt. Du springst NICHT vor und wirfst nicht das ganze Kapitel auf einmal raus — das überfordert und wird nicht gelesen.
- BALANCE IN DEN ANTWORTEN: Erkläre den aktuellen Abschnitt substantiell genug, dass der Student wirklich etwas lernt (mit Beispiel), aber halte es fokussiert auf DIESES eine Teilkonzept. In der Regel 2-4 Absätze.
- Wenn der Student eine Frage zum aktuellen Abschnitt stellt, beantworte sie ausführlich, bevor es weitergeht.
- Verwende Beispiele und Analogien, um abstrakte Konzepte greifbar zu machen
- Wenn der Student nach einer Notiz fragt oder sagt, er will eine Notiz erstellen, signalisiere das mit dem speziellen Marker [NOTIZ_ANFRAGE: Thema der gewünschten Notiz]
- SPEZIAL-NACHRICHTEN:
  - "[START]": Der Student hat das Kapitel gerade geöffnet. Beginne mit dem ERSTEN Abschnitt:
    * Verzichte auf Begrüßungsfloskeln wie "Hallo, schön dass du wieder da bist".
    * Steige mit einem kurzen, neugierig machenden Hook ein (1-2 Sätze: worum geht es in diesem Kapitel und warum lohnt es sich?).
    * Erkläre dann den ERSTEN Abschnitt substantiell mit Beispiel (2-4 Absätze). NICHT das ganze Kapitel.
    * Beende mit einer kurzen Verständnisfrage oder dem Hinweis, dass es danach mit dem nächsten Abschnitt weitergeht.
  - "[ABSCHNITT_WEITER]": Der Student möchte zum nächsten Abschnitt. Erkläre jetzt den oben als AKTUELL markierten Abschnitt — substantiell mit Beispiel, fokussiert auf dieses eine Teilkonzept. Knüpfe kurz an das Vorherige an (1 Satz), dann der neue Stoff.
  - "[NOTIZEN_ERSTELLT]": Es wurden gerade Notizen erstellt und gespeichert. Frage den Studenten freundlich
    und kurz (2-3 Sätze), ob er noch Fragen zum aktuellen Abschnitt hat oder ob er bereit ist, weiterzumachen.
{FORMATTING_RULES}

HINWEIS zu Mathe-Formeln: Wenn das Kapitel mathematische Inhalte hat, verwende die LaTeX-Notation ($...$ inline, $$...$$ als Block). Bei nicht-mathematischen Themen verwende KEINE Formeln.

Antworte auf Deutsch (oder in der Sprache des Buches).
Sei warmherzig aber sachlich. Fokussiere dich auf den Inhalt des Kapitels.
WICHTIG: DUZE den Studenten IMMER. Verwende "du/dein/dir", NIEMALS "Sie/Ihr/Ihnen"."""

    return (await generate_with_search(prompt, model=PRO_MODEL)).strip()


async def chat_about_book_chapter_stream(
    book_title: str,
    book_authors: list[str],
    chapter_number: str,
    chapter_title: str,
    chat_history: list[dict],
    user_message: str,
    previous_chapters_summary: str | None = None,
    next_chapter_title: str | None = None,
    sections: list[dict] | None = None,
    current_section: int = 0,
    knowledge_hits: list[dict] | None = None,
):
    """Streaming variant of chat_about_book_chapter. Yields SSE event dicts."""
    year = _current_year()
    authors_str = ", ".join(book_authors) if book_authors else "unbekannter Autor"
    prev_context = f"\nBEREITS BEHANDELT:\n{previous_chapters_summary}\n" if previous_chapters_summary else ""
    next_hint = f'\nNÄCHSTES KAPITEL: "{next_chapter_title}"' if next_chapter_title else ""
    knowledge_block = _format_knowledge_block(knowledge_hits) if knowledge_hits else ""
    history_text = ""
    for msg in chat_history[-20:]:
        role_label = "Student" if msg["role"] == "user" else "Tutor"
        if msg["role"] != "note_generated":
            history_text += f"\n{role_label}: {msg['content']}\n"
    sections_block = _build_sections_block(sections, current_section)
    sections_section = f"\n{sections_block}\n" if sections_block else ""

    prompt = f"""Du bist ein kompetenter Tutor ({year}), der einem Studenten beim Durcharbeiten eines Buches hilft. Du DUZT den Studenten IMMER.
BUCH: "{book_title}" von {authors_str}
KAPITEL {chapter_number}: "{chapter_title}"
{prev_context}{next_hint}{knowledge_block}{sections_section}
GESPRÄCHSVERLAUF:{history_text}

STUDENT: {user_message}

Recherchiere den tatsächlichen Inhalt dieses Kapitels. Erkläre den aktuellen Abschnitt substantiell mit Beispiel (2-4 Absätze).
{ADAPTIVE_TEACHING_RULES}
{FORMATTING_RULES}
Antworte auf Deutsch. DUZE den Studenten IMMER."""

    async for event in generate_with_search_stream(prompt, model=PRO_MODEL):
        yield event


async def generate_book_chapter_notes(
    book_title: str,
    book_authors: list[str],
    chapter_number: str,
    chapter_title: str,
    chat_history: list[dict],
    existing_tags: list[str] | None = None,
    existing_note_titles: list[str] | None = None,
) -> list[dict]:
    """Generate atomic notes for a book chapter based on the interactive discussion."""
    authors_str = ", ".join(book_authors) if book_authors else "unbekannter Autor"
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    chat_text = ""
    for msg in chat_history[-30:]:
        role_label = "Student" if msg["role"] == "user" else "Tutor"
        if msg["role"] != "note_generated" and msg.get("content", "") not in CONTROL_MESSAGES:
            chat_text += f"{role_label}: {msg['content'][:3000]}\n"

    # Determine if chat is too short for conversation-based notes
    thin_chat = len(chat_text.strip()) < 200

    if thin_chat:
        context_block = f"""HINWEIS: Das Gespräch ist noch sehr kurz. Generiere die Notizen basierend auf dem
Kapitelinhalt selbst. Nutze dein Wissen und aktuelle Recherche über das Buch und dieses Kapitel,
um hochwertige Notizen zu den Kernkonzepten zu erstellen.

BISHERIGER GESPRÄCHSVERLAUF (kurz):
{chat_text if chat_text.strip() else '(Noch kein inhaltliches Gespräch)'}"""
    else:
        context_block = f"""GESPRÄCHSVERLAUF:
{chat_text}"""

    # Build deduplication context
    dedup_block = ""
    if existing_note_titles:
        titles_list = "\n".join(f"- {t}" for t in existing_note_titles)
        dedup_block = f"""
BEREITS EXISTIERENDE NOTIZEN zu diesem Buch (aus vorherigen Kapiteln):
{titles_list}

WICHTIGE REGEL ZUR VERMEIDUNG VON DUPLIKATEN:
- Erstelle KEINE neuen Atomic Notes für Konzepte, die oben bereits als Notiz existieren.
- Wenn ein Konzept aus diesem Kapitel bereits als Notiz existiert, erwähne es nur kurz in der Überblicksnotiz und verweise darauf, statt eine neue Notiz zu erstellen.
- Verwende ANDERE Beispiele als in vorherigen Kapiteln — bringe frische, kapitelspezifische Beispiele.
- Erstelle nur Notizen für NEUE Konzepte, die in den bisherigen Notizen noch nicht behandelt wurden.
"""

    prompt = f"""Du bist ein Second Brain Assistent.
Basierend auf {'dem Buchkapitel' if thin_chat else 'dem folgenden Gespräch über ein Buchkapitel'} sollst du Notizen erstellen.

BUCH: "{book_title}" von {authors_str}
KAPITEL: {chapter_number} — "{chapter_title}"

{context_block}
{dedup_block}
STRUKTUR DER NOTIZEN:
1. ERSTE NOTIZ = ÜBERBLICKSNOTIZ: Eine zusammenfassende Notiz mit dem Titel "Kapitel {chapter_number}: {chapter_title}".
   Diese fasst das gesamte Kapitel kompakt zusammen: Kernaussagen, Hauptargumente, zentrale Begriffe.
   Sie dient als Einstiegspunkt und gibt einen Überblick über das gesamte Kapitel.
   Beginne mit einer kurzen Einordnung (Buch + Autor).
2. WEITERE NOTIZEN = ATOMIC NOTES: Für jedes wichtige Einzelkonzept eine eigene kurze Notiz.
   {ATOMIC_NOTE_RULES}
   Beginne jede Notiz mit einer kurzen Einordnung: Aus welchem Buch und Kapitel das Konzept stammt.

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen.

{FORMATTING_RULES}

Antworte NUR mit dem JSON, kein anderer Text:
{{
    "notes": [
        {{
            "title": "Kapitel {chapter_number}: {chapter_title}",
            "content": "Überblick über das gesamte Kapitel...",
            "suggested_tags": ["tag1", "tag2"],
            "suggested_folder": "Bücher/{book_title}"
        }},
        {{
            "title": "Konzeptname als Titel",
            "content": "Atomic Note Inhalt...",
            "suggested_tags": ["tag1"],
            "suggested_folder": "Bücher/{book_title}"
        }}
    ]
}}"""

    text = (await generate_with_search(prompt, model=PRO_MODEL)).strip()

    result = _extract_json(text)
    if result:
        notes = result.get("notes", [])
        # Fallback: if _extract_json found a single note object instead of the wrapper
        if not notes and "title" in result and "content" in result:
            notes = [result]
        for note in notes:
            note.setdefault("suggested_folder", f"Bücher/{book_title}")
            note.setdefault("suggested_tags", [])
        if notes:
            return notes
        _logger.warning("LLM returned empty notes array for chapter %s %s", chapter_number, chapter_title)

    _logger.warning("Failed to generate book chapter notes for %s %s — raw: %s", chapter_number, chapter_title, text[:500])
    return []


async def generate_book_term_note(
    term: str,
    book_title: str,
    book_authors: list[str],
    chapter_title: str,
    chat_history: list[dict],
    existing_tags: list[str] | None = None,
) -> dict:
    """Generate a single atomic note for a term from a book chapter context."""
    authors_str = ", ".join(book_authors) if book_authors else "unbekannter Autor"
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    chat_text = ""
    for msg in chat_history[-10:]:
        role_label = "Student" if msg["role"] == "user" else "Tutor"
        if msg["role"] != "note_generated" and msg.get("content", "") not in CONTROL_MESSAGES:
            chat_text += f"{role_label}: {msg['content'][:1500]}\n"

    prompt = f"""Du bist ein Second Brain Assistent.
Erstelle eine ATOMIC NOTE zum folgenden Begriff:

BEGRIFF: "{term}"
KONTEXT: Buch "{book_title}" von {authors_str}, Kapitel "{chapter_title}"

Aktueller Gesprächskontext:
{chat_text}

{ATOMIC_NOTE_RULES}
{FORMATTING_RULES}

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen.

Antworte NUR mit dem JSON, kein anderer Text:
{{
    "title": "{term}",
    "content": "Markdown-formatierter Inhalt der Notiz",
    "suggested_tags": ["tag1", "tag2"],
    "suggested_folder": "Bücher/{book_title}"
}}"""

    text = (await generate_with_search(prompt, model=PRO_MODEL)).strip()

    result = _extract_json(text)
    if result:
        return {
            "title": result.get("title", term),
            "content": result.get("content", ""),
            "suggested_tags": result.get("suggested_tags", []),
            "suggested_folder": result.get("suggested_folder", f"Bücher/{book_title}"),
        }

    return {
        "title": term,
        "content": f"Fehler beim Generieren der Notiz für '{term}'.",
        "suggested_tags": [],
        "suggested_folder": f"Bücher/{book_title}",
    }


# ── Note persistence helpers (used by the agentic teacher to save silently) ──
# The agentic tutor saves notes on its own, in the background, without a review
# screen. These helpers own folder creation, tag resolution, note creation /
# update and vector-embedding upsert. They open their writes on whatever session
# is passed in (the caller decides transaction scope).

_TEACHER_TAG_COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']


async def _ensure_folder(user_id, db, path: str | None):
    """Create all folders in a path if missing; return the leaf folder."""
    from uuid import UUID
    from sqlalchemy import select
    from app.models import Folder

    if not path:
        path = "Allgemein"
    uid = user_id if not isinstance(user_id, str) else UUID(str(user_id))

    result = await db.execute(select(Folder).where(Folder.path == path, Folder.user_id == uid))
    folder = result.scalar_one_or_none()
    if folder:
        return folder

    parts = [p for p in path.split("/") if p]
    current_path = ""
    parent_id = None
    folder = None
    for part in parts:
        current_path = f"{current_path}/{part}" if current_path else part
        result = await db.execute(select(Folder).where(Folder.path == current_path, Folder.user_id == uid))
        existing = result.scalar_one_or_none()
        if existing:
            parent_id = existing.id
            folder = existing
            continue
        new_folder = Folder(name=part, path=current_path, parent_id=parent_id, user_id=uid)
        db.add(new_folder)
        await db.flush()
        await db.refresh(new_folder)
        parent_id = new_folder.id
        folder = new_folder
    return folder


async def _resolve_tag_objects(user_id, db, names: list[str] | None):
    """Resolve tag names to Tag rows, creating new ones as needed."""
    import random
    from uuid import UUID
    from sqlalchemy import select
    from app.models import Tag

    uid = user_id if not isinstance(user_id, str) else UUID(str(user_id))
    tag_result = await db.execute(select(Tag).where(Tag.user_id == uid))
    all_tags = list(tag_result.scalars().all())

    resolved = []
    for tag_name in names or []:
        tl = (tag_name or "").strip().lower()
        if not tl:
            continue
        found = next((t for t in all_tags if t.name_lower == tl), None)
        if not found:
            found = Tag(
                name=tag_name.strip(), name_lower=tl,
                color=random.choice(_TEACHER_TAG_COLORS), user_id=uid,
            )
            db.add(found)
            await db.flush()
            await db.refresh(found)
            all_tags.append(found)
        resolved.append(found)
    return resolved


async def save_atomic_note(
    user_id, db, title: str, content: str,
    folder_path: str | None = None, tags: list[str] | None = None,
) -> dict:
    """Create and persist a single note, ensuring its folder + tags exist.

    Commits on the given session and upserts the vector embedding (best-effort).
    Returns {note_id, title, folder}.
    """
    from uuid import UUID
    from app.models import Note

    uid = user_id if not isinstance(user_id, str) else UUID(str(user_id))
    folder = await _ensure_folder(uid, db, folder_path or "Allgemein")
    tag_objs = await _resolve_tag_objects(uid, db, tags)

    note = Note(
        title=(title or "Notiz").strip()[:500],
        content=content or "",
        note_type="text",
        folder_id=folder.id,
        user_id=uid,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)
    for t in tag_objs:
        note.tags.append(t)
    await db.commit()

    try:
        from app.services.vector_service import upsert_note_embedding
        upsert_note_embedding(str(note.id), str(uid), note.title, note.content, folder.path)
    except Exception:
        pass

    return {"note_id": str(note.id), "title": note.title, "folder": folder.path}


async def update_atomic_note(
    user_id, db, note_id: str,
    content: str | None = None, append: bool = False, title: str | None = None,
) -> dict:
    """Update an existing note's content/title. Returns {note_id, title} or {error}."""
    from uuid import UUID
    from app.models import Note, Folder

    uid = user_id if not isinstance(user_id, str) else UUID(str(user_id))
    try:
        note = await db.get(Note, UUID(str(note_id)))
    except Exception:
        note = None
    if not note or note.user_id != uid:
        return {"error": "Notiz nicht gefunden"}

    if title:
        note.title = title.strip()[:500]
    if content is not None:
        if append:
            note.content = (note.content or "").rstrip() + "\n\n" + content
        else:
            note.content = content
    await db.commit()
    await db.refresh(note)

    try:
        folder = await db.get(Folder, note.folder_id)
        from app.services.vector_service import upsert_note_embedding
        upsert_note_embedding(str(note.id), str(uid), note.title, note.content, folder.path if folder else "")
    except Exception:
        pass

    return {"note_id": str(note.id), "title": note.title, "updated": True}


# ── Curriculum editing via chat ───────────────────────────────────────

async def edit_curriculum(current_curriculum: dict, instruction: str) -> dict:
    """Revise an existing curriculum based on a free-text instruction.

    Takes the current {title, description, units:[...]} and the user's instruction
    (e.g. "tausche Lektion 3 und 5", "mehr Fokus auf Beweise", "kürzer") and returns
    a fully revised curriculum in the same shape. Falls back to the input on failure.
    """
    year = _current_year()
    current_json = json.dumps(current_curriculum, ensure_ascii=False, indent=2)

    prompt = f"""Du bist ein Lehrplanentwickler ({year}). Der Student möchte einen bestehenden
Lehrplan anpassen. Hier ist der AKTUELLE Lehrplan als JSON:

{current_json}

ANWEISUNG DES STUDENTEN:
{instruction}

Überarbeite den Lehrplan gemäß der Anweisung. Regeln:
- Behalte die bewährte Struktur bei (Module = level 1, Lektionen = level 2)
- unit_number als String: Module "1", "2", …; Lektionen "1.1", "1.2", …
- Ändere NUR das, worum der Student bittet — den Rest lässt du inhaltlich stabil
- Jede Lektion hat klare Lernziele (learning_objectives)
- Gib den KOMPLETTEN überarbeiteten Lehrplan zurück, nicht nur die Änderung

Antworte ausschließlich im JSON-Format des Lehrplans."""

    result = await generate_json(prompt, CURRICULUM_SCHEMA, model=PRO_MODEL, temperature=0.5)
    if result and isinstance(result, dict) and result.get("units"):
        return {
            "title": result.get("title", current_curriculum.get("title", "")),
            "description": result.get("description", current_curriculum.get("description", "")),
            "units": result.get("units", []),
        }
    return current_curriculum


# ── "Thinking" status line (Flash-powered, German, short) ─────────────

async def summarize_thinking_status(
    thinking_text: str | None = None,
    tool_name: str | None = None,
    tool_args: dict | None = None,
) -> str:
    """Turn the agent's raw (English, verbose) reasoning / tool step into a short,
    warm German status line, as if the tutor were briefly thinking out loud.

    Uses the cheap FLASH_MODEL. Kept intentionally tiny (a half sentence). On any
    failure it falls back to a deterministic phrase so the UI is never empty.
    """
    # Deterministic fallback per tool — always available, never blocks.
    fallback_by_tool = {
        "search_my_notes": "Ich schaue, was du dazu schon weißt …",
        "propose_quiz": "Ich überlege mir eine kleine Verständnisfrage …",
        "set_difficulty": "Ich passe das Tempo an dich an …",
        "mark_understanding": "Ich merke mir, wie es bei dir sitzt …",
        "save_note": "Ich halte das für dich als Notiz fest …",
        "update_note": "Ich ergänze eine bestehende Notiz …",
        "create_folder": "Ich sortiere das sauber ein …",
        "ask_checkpoint": "Ich formuliere eine kurze Zwischenfrage …",
        "draw_diagram": "Ich skizziere das für dich …",
        "advance_section": "Weiter zum nächsten Abschnitt …",
    }
    fallback = fallback_by_tool.get(tool_name or "", "Ich denke kurz nach …")

    src = (thinking_text or "").strip()
    if not src and not tool_name:
        return fallback

    context = ""
    if tool_name:
        context += f"\nAktuelle Aktion des Tutors: {tool_name}"
        if tool_args:
            try:
                context += f" ({json.dumps(tool_args, ensure_ascii=False)[:200]})"
            except Exception:
                pass
    if src:
        context += f"\nInterner Gedankengang (evtl. englisch):\n{src[:800]}"

    prompt = f"""Formuliere eine EINZIGE, sehr kurze deutsche Statuszeile (max 6 Wörter),
die zeigt, was ein Tutor gerade tut oder denkt — warmherzig, in der ICH-Form, mit einem
abschließenden „ …". Keine Anführungszeichen, kein Punkt am Ende, nur die Zeile.
{context}

Beispiele für den Stil:
- „Ich suche ein gutes Beispiel …"
- „Ich knüpfe an dein Vorwissen an …"
- „Ich fasse das Wichtigste zusammen …"

Statuszeile:"""

    try:
        line = (await generate(prompt, model=FLASH_MODEL, temperature=0.4)).strip()
        line = line.strip('"\'').strip()
        # Guard against the model returning a paragraph.
        if not line or len(line) > 80:
            return fallback
        return line
    except Exception:
        return fallback
