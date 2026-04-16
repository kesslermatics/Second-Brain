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

    Handles markdown code fences, preamble text with braces, etc.
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

    # 3. Find first valid JSON object using balanced braces
    i = 0
    while i < len(cleaned):
        if cleaned[i] == '{':
            depth = 0
            for j in range(i, len(cleaned)):
                if cleaned[j] == '{':
                    depth += 1
                elif cleaned[j] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[i:j + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break  # This opening brace wasn't it, skip past it
            i = cleaned.find('{', i + 1)
            if i == -1:
                break
        else:
            i += 1

    logger.warning("Failed to extract JSON from LLM response: %s", text[:300])
    return None

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

- MATHEMATISCHE FORMELN: Verwende IMMER LaTeX-Notation:
  - Inline-Formeln: $E = mc^2$
  - Zentrierte Block-Formeln: $$\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}$$
  - JEDE mathematische Formel oder Gleichung MUSS in LaTeX geschrieben werden
  - Block-Formeln ($$...$$) sollen auf eigener Zeile stehen, zentriert
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
- AKTUELLE FORSCHUNG UND STATE OF THE ART einbeziehen: Recherchiere nach den neuesten
  Entwicklungen, Methoden und Erkenntnissen in diesem Fachgebiet (Stand {year}).
  Neben den Grundlagen sollen auch aktuelle Trends, moderne Ansätze und neue
  Forschungsergebnisse als Lektionen enthalten sein. Wenn das Thema sich schnell
  weiterentwickelt (z.B. KI, Medizin, Technologie), widme mindestens ein Modul
  explizit den aktuellen Entwicklungen und dem Stand der Forschung ({year}).

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
- AKTUALITÄT: Recherchiere aktiv nach dem aktuellen State of the Art, neuesten Forschungsergebnissen,
  modernen Best Practices und aktuellen Entwicklungen zu diesem Thema. Bringe diese proaktiv ein,
  wenn sie relevant sind. Kennzeichne aktuelle Erkenntnisse z.B. mit "Aktueller Stand ({year}):..."
  oder "Neuere Forschung zeigt...". Wenn klassisches Wissen inzwischen überholt ist, weise darauf hin.

{FORMATTING_RULES}

HINWEIS zu Mathe-Formeln: Wenn das Thema mathematische Inhalte hat, verwende IMMER die LaTeX-Notation ($...$ inline, $$...$$ als Block).

Antworte auf Deutsch (oder in der Sprache, die der Student verwendet).
Sei warmherzig aber sachlich. Kein Smalltalk — fokussiere dich auf den Lehrinhalt.
WICHTIG: DUZE den Studenten IMMER. Verwende "du/dein/dir", NIEMALS "Sie/Ihr/Ihnen"."""

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    return response.text.strip()


async def generate_lesson_notes(
    course_title: str,
    unit_title: str,
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

    prompt = f"""Du bist ein Second Brain Assistent. Wir befinden uns im Jahr {year}.
Basierend auf dem folgenden Unterrichtsgespräch sollst du ATOMIC NOTES erstellen.

KURS: "{course_title}"
LEKTION: "{unit_title}"
{unit_description}

LERNZIELE:
{objectives_str}

GESPRÄCHSVERLAUF:
{chat_text}

{ATOMIC_NOTE_RULES}

Bestehende Tags im System: {tags_str}
Bevorzuge bestehende Tags wenn sie passen.

{FORMATTING_RULES}

Erstelle so viele Notizen wie nötig, um ALLE wichtigen Konzepte der Lektion abzudecken.
Typischerweise 2-5 Notizen pro Lektion.

ACHTUNG AKTUALITÄT: Wenn im Gespräch aktuelle Forschungsergebnisse, moderne Methoden oder
State-of-the-Art-Entwicklungen besprochen wurden, schreibe diese MIT in die Notizen.
Recherchiere zusätzlich, ob es relevante aktuelle Erkenntnisse (Stand {year}) gibt, die in die Notizen gehören.

Antworte NUR mit dem JSON, kein anderer Text:
{{
    "notes": [
        {{
            "title": "Konzeptname als Titel",
            "content": "Markdown-formatierter Inhalt der Notiz",
            "suggested_tags": ["tag1", "tag2"],
            "suggested_folder": "Kurse/{course_title}"
        }}
    ]
}}"""

    response = model.generate_content(prompt, tools=[GOOGLE_SEARCH_TOOL])
    text = response.text.strip()

    result = _extract_json(text)
    if result:
        notes = result.get("notes", [])
        for note in notes:
            note.setdefault("suggested_folder", f"Kurse/{course_title}")
            note.setdefault("suggested_tags", [])
        return notes

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

WICHTIG: Recherchiere den aktuellen Stand der Forschung / State of the Art (Stand {year}) zu diesem Begriff.
Wenn es neuere Erkenntnisse oder Entwicklungen gibt, integriere sie in die Notiz.

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
