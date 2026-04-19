"""Infinite Teacher service — curriculum generation, interactive teaching chat, note generation."""

import google.generativeai as genai
from google.ai.generativelanguage_v1beta import types as glm_types
from app.services.ai_service import get_gemini_model
from app.config import get_settings
import json
import re
from datetime import datetime

GOOGLE_SEARCH_TOOL = glm_types.Tool(google_search=glm_types.Tool.GoogleSearch())

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


async def generate_curriculum(
    topic: str,
    parent_context: str | None = None,
    custom_focus: str | None = None,
) -> dict:
    """Generate a full curriculum / study plan for a topic.

    Returns: {title, description, units: [{unit_number, title, description, learning_objectives, level}]}
    """
    model = get_gemini_model()

    context_section = ""
    if parent_context:
        context_section = f"""
KONTEXT: Der Studierende hat bereits folgenden Kurs abgeschlossen:
{parent_context}

Baue auf diesem Wissen auf und vertiefe es. Wiederhole KEINE bereits behandelten Themen,
sondern gehe auf fortgeschrittene Aspekte ein.
"""
    if custom_focus:
        context_section += f"\nGEWÜNSCHTER SCHWERPUNKT: {custom_focus}\n"

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
- Wenn das Thema sich dynamisch weiterentwickelt (z.B. KI, Medizin, Technologie),
  beziehe aktuelle Forschung und den State of the Art (Stand {year}) mit ein.
  Bei zeitlosen oder historischen Themen ist das NICHT nötig.

Antworte NUR mit dem JSON, kein anderer Text:
{{
    "title": "Kurstitel — kurz und prägnant",
    "description": "Kurze Beschreibung des Kurses in 2-3 Sätzen",
    "units": [
        {{
            "unit_number": "1",
            "title": "Modulname",
            "description": "Was in diesem Modul behandelt wird",
            "learning_objectives": [],
            "level": 1
        }},
        {{
            "unit_number": "1.1",
            "title": "Lektionsname — das konkrete Thema",
            "description": "Was genau in dieser Lektion gelehrt wird",
            "learning_objectives": ["Ziel 1", "Ziel 2"],
            "level": 2
        }}
    ]
}}

WICHTIG:
- Erstelle einen UMFASSENDEN Lehrplan mit mindestens 5 Modulen und insgesamt 15-30 Lektionen
- Jede Lektion hat klare, messbare Lernziele
- Die Lektionsnamen sollen das THEMA beschreiben, nicht "Stunde 1" oder "Lektion 1"
- Module (level 1) sind übergeordnete Themenbereiche, Lektionen (level 2) sind die konkreten Unterrichtseinheiten"""

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    text = response.text.strip()

    result = _extract_json(text)
    if result:
        return {
            "title": result.get("title", topic),
            "description": result.get("description", ""),
            "units": result.get("units", []),
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
) -> str:
    """Send a message to the AI teacher and get a response.

    The teacher explains concepts conversationally, answers questions,
    and guides the student through the lesson.
    """
    model = get_gemini_model()

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

    prompt = f"""Du bist ein freundlicher, geduldiger und kompetenter Universitätsprofessor.
Wir befinden uns im Jahr {year}.
Du DUZT den Studenten IMMER ("du", "dein", "dir" — NIEMALS "Sie", "Ihr", "Ihnen").
Du unterrichtest gerade den Kurs "{course_title}".

AKTUELLE LEKTION: "{unit_title}"
{unit_description}

LERNZIELE dieser Lektion:
{objectives_str}
{prev_context}{next_hint}

BISHERIGER GESPRÄCHSVERLAUF:
{history_text}

NEUE NACHRICHT DES STUDENTEN:
{user_message}

DEINE AUFGABE:
- Erkläre Konzepte einfach, klar und angenehm — wie ein guter Tutor
- Verwende Beispiele und Analogien, um abstrakte Konzepte greifbar zu machen
- Wenn der Student eine Frage stellt, beantworte sie ausführlich
- Wenn der Student sagt, er hat verstanden oder weiter möchte, fasse kurz zusammen und leite zum nächsten Aspekt über
- Wenn der Student nach einer Notiz fragt oder sagt, er will eine Notiz erstellen, signalisiere das mit dem speziellen Marker [NOTIZ_ANFRAGE: Thema der gewünschten Notiz]
- Wenn du den Eindruck hast, der Student versteht den Stoff, ermutige ihn und schlage vor, eine Notiz zu erstellen
- SPEZIAL-NACHRICHTEN:
  - "[START]": Der Student hat die Lektion gerade geöffnet. Begrüße ihn kurz und beginne mit der Einführung des Themas.
  - "[NOTIZEN_ERSTELLT]": Es wurden gerade Notizen zum aktuellen Thema erstellt und gespeichert. Frage den Studenten freundlich und kurz (2-3 Sätze), ob er noch Fragen zum aktuellen Thema hat oder ob er bereit ist, zur nächsten Lektion überzugehen.
- AKTUALITÄT: Wenn das Thema sich seit der klassischen Lehrmeinung weiterentwickelt hat
  oder es relevante neue Erkenntnisse gibt, bringe diese ein und kennzeichne sie z.B. mit
  "Aktueller Stand ({year}):...". Bei zeitlosen Themen (z.B. Philosophie, Geschichte,
  Grundlagentheorie) ist das NICHT nötig — erzwinge keine künstliche Aktualität.

{FORMATTING_RULES}

HINWEIS zu Mathe-Formeln: Wenn das Thema mathematische Inhalte hat, verwende die LaTeX-Notation ($...$ inline, $$...$$ als Block). Bei nicht-mathematischen Themen verwende KEINE Formeln.

Antworte auf Deutsch (oder in der Sprache, die der Student verwendet).
Sei warmherzig aber sachlich. Kein Smalltalk — fokussiere dich auf den Lehrinhalt.
WICHTIG: DUZE den Studenten IMMER. Verwende "du/dein/dir", NIEMALS "Sie/Ihr/Ihnen"."""

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    return response.text.strip()


async def generate_lesson_notes(
    course_title: str,
    unit_title: str,
    unit_number: str,
    unit_description: str,
    learning_objectives: list[str],
    chat_history: list[dict],
    existing_tags: list[str] | None = None,
) -> list[dict]:
    """Generate atomic notes for the current lesson based on what was discussed.

    Returns a list of notes: [{title, content, suggested_tags, suggested_folder}]
    """
    model = get_gemini_model()
    year = _current_year()

    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    objectives_str = "\n".join(f"  - {o}" for o in learning_objectives) if learning_objectives else ""

    # Compress chat history for context — use generous limit so notes cover everything
    chat_text = ""
    for msg in chat_history[-30:]:
        role_label = "Student" if msg["role"] == "user" else "Lehrer"
        if msg["role"] != "note_generated" and msg.get("content", "") not in ("[START]", "[NOTIZEN_ERSTELLT]"):
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

    prompt = f"""Du bist ein Second Brain Assistent. Wir befinden uns im Jahr {year}.
Basierend auf {'der Lektion' if thin_chat else 'dem folgenden Unterrichtsgespräch'} sollst du Notizen erstellen.

KURS: "{course_title}"
LEKTION {unit_number}: "{unit_title}"
{unit_description}

LERNZIELE:
{objectives_str}

{context_block}

STRUKTUR DER NOTIZEN:
1. ERSTE NOTIZ = ÜBERBLICKSNOTIZ: Eine zusammenfassende Notiz mit dem Titel "Lektion {unit_number}: {unit_title}".
   Diese fasst die gesamte Lektion kompakt zusammen: Kernaussagen, wichtige Konzepte, Zusammenhänge.
   Sie dient als Einstiegspunkt und gibt einen Überblick über die gesamte Lektion.
2. WEITERE NOTIZEN = ATOMIC NOTES: Für jedes wichtige Einzelkonzept eine eigene kurze Notiz.
   {ATOMIC_NOTE_RULES}

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen.

{FORMATTING_RULES}

ACHTUNG AKTUALITÄT: Wenn im Gespräch aktuelle Forschungsergebnisse oder moderne Entwicklungen
besprochen wurden, schreibe diese MIT in die Notizen. Bei zeitlosen Themen (Philosophie,
Geschichte, Grundlagentheorie) ist keine künstliche Aktualitätsrecherche nötig.

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

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    text = response.text.strip()

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
    model = get_gemini_model()
    year = _current_year()

    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    # Compress recent chat for context
    chat_text = ""
    for msg in chat_history[-10:]:
        role_label = "Student" if msg["role"] == "user" else "Lehrer"
        if msg["role"] != "note_generated" and msg.get("content", "") not in ("[START]", "[NOTIZEN_ERSTELLT]"):
            chat_text += f"{role_label}: {msg['content'][:1500]}\n"

    prompt = f"""Du bist ein Second Brain Assistent. Wir befinden uns im Jahr {year}.
Erstelle eine ATOMIC NOTE zum folgenden Begriff:

BEGRIFF: "{term}"
KONTEXT: Kurs "{course_title}", Lektion "{unit_title}"

Aktueller Gesprächskontext:
{chat_text}

Wenn es für diesen Begriff relevante aktuelle Entwicklungen gibt (Stand {year}), erwähne sie.
Bei zeitlosen Konzepten ist keine künstliche Aktualitätsrecherche nötig.

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

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    text = response.text.strip()

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
    model = get_gemini_model()
    year = _current_year()

    prompt = f"""Du bist ein Studienberater und Lehrplanentwickler.
Wir befinden uns im Jahr {year}. Du DUZT den Studierenden.

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
- AKTUELLE TRENDS berücksichtigen: Recherchiere die neuesten Entwicklungen und Forschungsrichtungen
  in diesem Fachgebiet (Stand {year}) und schlage auch Schwerpunkte vor, die sich mit State-of-the-Art-Themen befassen

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

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    text = response.text.strip()

    result = _extract_json(text)
    if result:
        return result.get("suggestions", [])

    return []


async def ai_edit_lesson_content(current_content: str, instruction: str) -> str:
    """Edit a lesson note based on user instruction."""
    model = get_gemini_model()

    prompt = f"""Du bist ein Second Brain Assistent. Bearbeite die folgende Notiz basierend auf der Anweisung.

AKTUELLE NOTIZ:
{current_content}

ANWEISUNG: {instruction}

{FORMATTING_RULES}
{ATOMIC_NOTE_RULES}

Gib NUR den neuen, vollständigen Notiz-Inhalt zurück (Markdown). Kein JSON, keine Erklärung, nur der Inhalt."""

    response = model.generate_content(prompt)
    return response.text.strip()


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
) -> str:
    """Chat about a specific book chapter, explaining its content interactively."""
    model = get_gemini_model()
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

    prompt = f"""Du bist ein freundlicher, geduldiger und kompetenter Tutor, der einem Studenten beim Durcharbeiten eines Buches hilft.
Wir befinden uns im Jahr {year}.
Du DUZT den Studenten IMMER ("du", "dein", "dir" — NIEMALS "Sie", "Ihr", "Ihnen").

BUCH: "{book_title}" von {authors_str}
AKTUELLES KAPITEL: {chapter_number} — "{chapter_title}"
{prev_context}{next_hint}

BISHERIGER GESPRÄCHSVERLAUF:
{history_text}

NEUE NACHRICHT DES STUDENTEN:
{user_message}

DEINE AUFGABE:
- Recherchiere zuerst den TATSÄCHLICHEN Inhalt dieses Kapitels aus dem Buch und erkläre ihn dann
- Erkläre die Kernkonzepte des Kapitels klar und verständlich — wie ein guter Tutor
- Verwende Beispiele und Analogien, um abstrakte Konzepte greifbar zu machen
- Wenn der Student eine Frage stellt, beantworte sie ausführlich
- Wenn der Student sagt, er hat verstanden oder weiter möchte, fasse kurz zusammen
- Wenn der Student nach einer Notiz fragt oder sagt, er will eine Notiz erstellen, signalisiere das mit dem speziellen Marker [NOTIZ_ANFRAGE: Thema der gewünschten Notiz]
- Wenn du den Eindruck hast, der Student versteht den Stoff, ermutige ihn und schlage vor, Notizen zu erstellen
- SPEZIAL-NACHRICHTEN:
  - "[START]": Der Student hat das Kapitel gerade geöffnet. Begrüße ihn kurz und beginne mit einer Einführung
    in das Kapitelthema. Gib einen Überblick über die wichtigsten Konzepte, die in diesem Kapitel behandelt werden.
  - "[NOTIZEN_ERSTELLT]": Es wurden gerade Notizen erstellt und gespeichert. Frage den Studenten freundlich
    und kurz (2-3 Sätze), ob er noch Fragen zum aktuellen Kapitel hat oder ob er bereit ist, zum nächsten
    Kapitel überzugehen.
- AKTUALITÄT: Wenn das Buchthema sich seit Veröffentlichung relevant weiterentwickelt hat,
  bringe aktuelle Ergänzungen ein und kennzeichne sie z.B. mit "Aktueller Stand ({year}):...".
  Bei zeitlosen Themen (Philosophie, klassische Literatur, etc.) ist das NICHT nötig.

{FORMATTING_RULES}

HINWEIS zu Mathe-Formeln: Wenn das Kapitel mathematische Inhalte hat, verwende die LaTeX-Notation ($...$ inline, $$...$$ als Block). Bei nicht-mathematischen Themen verwende KEINE Formeln.

Antworte auf Deutsch (oder in der Sprache des Buches).
Sei warmherzig aber sachlich. Fokussiere dich auf den Inhalt des Kapitels.
WICHTIG: DUZE den Studenten IMMER. Verwende "du/dein/dir", NIEMALS "Sie/Ihr/Ihnen"."""

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    return response.text.strip()


async def generate_book_chapter_notes(
    book_title: str,
    book_authors: list[str],
    chapter_number: str,
    chapter_title: str,
    chat_history: list[dict],
    existing_tags: list[str] | None = None,
) -> list[dict]:
    """Generate atomic notes for a book chapter based on the interactive discussion."""
    model = get_gemini_model()
    year = _current_year()
    authors_str = ", ".join(book_authors) if book_authors else "unbekannter Autor"
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    chat_text = ""
    for msg in chat_history[-30:]:
        role_label = "Student" if msg["role"] == "user" else "Tutor"
        if msg["role"] != "note_generated" and msg.get("content", "") not in ("[START]", "[NOTIZEN_ERSTELLT]"):
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

    prompt = f"""Du bist ein Second Brain Assistent. Wir befinden uns im Jahr {year}.
Basierend auf {'dem Buchkapitel' if thin_chat else 'dem folgenden Gespräch über ein Buchkapitel'} sollst du Notizen erstellen.

BUCH: "{book_title}" von {authors_str}
KAPITEL: {chapter_number} — "{chapter_title}"

{context_block}

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

ACHTUNG: Wenn im Gespräch aktuelle Ergänzungen zum Buchinhalt besprochen wurden, integriere diese in die Notizen.

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

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    text = response.text.strip()

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
    model = get_gemini_model()
    year = _current_year()
    authors_str = ", ".join(book_authors) if book_authors else "unbekannter Autor"
    tags_str = ", ".join(existing_tags) if existing_tags else "(keine)"

    chat_text = ""
    for msg in chat_history[-10:]:
        role_label = "Student" if msg["role"] == "user" else "Tutor"
        if msg["role"] != "note_generated" and msg.get("content", "") not in ("[START]", "[NOTIZEN_ERSTELLT]"):
            chat_text += f"{role_label}: {msg['content'][:1500]}\n"

    prompt = f"""Du bist ein Second Brain Assistent. Wir befinden uns im Jahr {year}.
Erstelle eine ATOMIC NOTE zum folgenden Begriff:

BEGRIFF: "{term}"
KONTEXT: Buch "{book_title}" von {authors_str}, Kapitel "{chapter_title}"

Aktueller Gesprächskontext:
{chat_text}

Wenn es für diesen Begriff relevante aktuelle Entwicklungen gibt (Stand {year}), erwähne sie.
Bei zeitlosen Konzepten ist keine künstliche Aktualitätsrecherche nötig.

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

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    text = response.text.strip()

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
