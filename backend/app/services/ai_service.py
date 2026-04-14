import google.generativeai as genai
from app.config import get_settings
import json
import re

settings = get_settings()
genai.configure(api_key=settings.GEMINI_API_KEY)


def get_gemini_model():
    return genai.GenerativeModel("gemini-3-flash-preview")


async def process_note_input(user_input: str, folder_structure: list[dict]) -> dict:
    """Process user input and suggest where to save it as a note."""
    model = get_gemini_model()

    folder_tree_str = json.dumps(folder_structure, indent=2, default=str)

    prompt = f"""Du bist ein Second Brain Assistent. Der Benutzer gibt dir Notizen oder Informationen, 
und du sollst diese strukturiert aufbereiten und vorschlagen, wo sie in der vorhandenen Ordnerstruktur 
gespeichert werden sollen.

Aktuelle Ordnerstruktur:
{folder_tree_str}

Benutzereingabe:
{user_input}

Bitte antworte im folgenden JSON-Format (NUR das JSON, kein anderer Text):
{{
    "suggested_folder": "pfad/zum/ordner",
    "suggested_title": "Titel der Notiz",
    "formatted_content": "Der formatierte Inhalt der Notiz in Markdown"
}}

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
- Die Notiz soll visuell ansprechend und leicht scanbar sein"""

    response = model.generate_content(prompt)
    text = response.text.strip()

    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        text = json_match.group()

    try:
        result = json.loads(text)
        return {
            "suggested_folder": result.get("suggested_folder", ""),
            "suggested_title": result.get("suggested_title", ""),
            "formatted_content": result.get("formatted_content", ""),
        }
    except json.JSONDecodeError:
        return {
            "suggested_folder": "",
            "suggested_title": "Neue Notiz",
            "formatted_content": user_input,
        }


async def answer_with_rag(question: str, context_notes: list[dict], chat_history: list[dict] = None) -> str:
    """Answer a question using RAG context."""
    model = get_gemini_model()

    context_str = ""
    for note in context_notes:
        context_str += f"\n--- Notiz: {note['title']} (Pfad: {note['folder_path']}) ---\n"
        context_str += f"{note['content_preview']}\n"

    history_str = ""
    if chat_history:
        for msg in chat_history[-10:]:
            role = "Benutzer" if msg["role"] == "user" else "Assistent"
            history_str += f"{role}: {msg['content']}\n"

    prompt = f"""Du bist ein intelligenter Second Brain Assistent. Beantworte die Frage des Benutzers 
basierend auf den folgenden Notizen aus seinem Second Brain. Wenn die Notizen nicht ausreichen, 
um die Frage vollständig zu beantworten, sage das ehrlich und gib trotzdem dein Bestes.

Relevante Notizen aus dem Second Brain:
{context_str}

{f'Bisheriger Chatverlauf:{chr(10)}{history_str}' if history_str else ''}

Aktuelle Frage: {question}

Bitte antworte:
- Strukturiert und klar
- Mit Bezug auf die Quellen wenn möglich
- In der Sprache der Frage
- Nutze Markdown für Formatierung"""

    response = model.generate_content(prompt)
    return response.text


async def edit_note_with_ai(current_content: str, instruction: str) -> str:
    """Edit a note based on AI instruction."""
    model = get_gemini_model()

    prompt = f"""Du bist ein Notiz-Editor. Bearbeite die folgende Notiz gemäß der Anweisung des Benutzers.
Gib NUR den bearbeiteten Inhalt zurück, keinen anderen Text.

Aktuelle Notiz:
{current_content}

Anweisung: {instruction}

Bearbeitete Notiz:"""

    response = model.generate_content(prompt)
    return response.text.strip()
