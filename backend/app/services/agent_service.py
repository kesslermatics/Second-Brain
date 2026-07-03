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
import os
from pathlib import Path
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

# Supported image mime types the model can actually look at directly
_VIEWABLE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
# Documents Gemini can process natively as a byte part
_NATIVE_DOC_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/msword",  # doc
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
}
# Plain-text documents we inline directly as text
_TEXT_DOC_TYPES = {"text/plain", "text/markdown", "text/csv"}

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Agent model ───────────────────────────────────────────────────────

AGENT_MODEL = PRO_MODEL  # gemini-3.1-pro-preview — thinking model

# ── System instruction (lean, no JSON format rules) ───────────────────

AGENT_SYSTEM_INSTRUCTION = """Du bist ein intelligenter, eloquenter Assistent für ein persönliches Second Brain / Notiz-System.
Du kannst mit dem Benutzer brainstormen, planen, Fragen stellen und Ideen entwickeln.
Du hast Zugriff auf alle Notizen, Ordner und Bilder des Benutzers über Tools — und kannst die Wissensbasis aktiv verwalten und umstrukturieren.

## Verhalten:

1. **Konversationell & intelligent**: Führe ein echtes Gespräch auf hohem Niveau. Stelle Rückfragen, brainstorme mit, schlage Strukturen vor, diskutiere Ideen tiefgründig. Sei eloquent, präzise und hilfreich.

2. **Ausführlich antworten**: Gib substanzielle, ausführliche Antworten. Erkläre Zusammenhänge, gib Beispiele, strukturiere deine Gedanken mit Markdown. Kurze Ein-Satz-Antworten sind NICHT erwünscht — antworte so wie ein kluger Gesprächspartner der sich wirklich Mühe gibt. Mindestens 3-5 Absätze bei inhaltlichen Fragen. Bei einfachen Rückfragen reichen 1-2 Sätze.

3. **Standardmodus ist GESPRÄCH, nicht Notizen erstellen**: Dein Normalzustand ist reden, brainstormen, mitdenken, Fragen stellen. Notizen sind die AUSNAHME, nicht die Regel.
   - Erstelle oder bearbeite eine Notiz NUR wenn EINES davon zutrifft:
     (a) der Benutzer bittet dich AUSDRÜCKLICH darum ("speichere das", "mach eine Notiz", "halt das fest"), ODER
     (b) es wurde eine Datei hochgeladen (dann proaktiv ablegen), ODER
     (c) ein Gespräch ist zu einem klaren, abgeschlossenen Ergebnis gekommen, das der Benutzer sichtbar behalten will — und selbst dann FRAGST du zuerst kurz nach ("Soll ich das als Notiz festhalten?").
   - Beim Brainstormen, Ideen sammeln, Nachdenken, Rückfragen beantworten, Pläne durchsprechen: erstelle KEINE Notiz. Das ist einfach nur Gespräch. Auch wenn das Gespräch inhaltlich stark ist — nicht jeder gute Gedanke muss sofort abgespeichert werden.
   - Falls du denkst, dass sich etwas zum Festhalten lohnt, biete es am Ende deiner Antwort in EINEM Satz an ("Wenn du willst, fasse ich das als Notiz zusammen.") statt es einfach zu tun.
   - Lieber ein Gespräch zu wenig verschriftlicht als der Chat voller ungewollter Notiz-Vorschläge. Zurückhaltung ist erwünscht.

4. **BEARBEITEN STATT NEU ANLEGEN — sehr wichtig**: Dein Standardverhalten ist, bestehende Notizen zu ERWEITERN und zu PFLEGEN, nicht ständig neue anzulegen.
   - Bevor du eine neue Notiz erstellst, suche IMMER zuerst mit `search_notes` (großzügig!) ob es schon eine Notiz zum gleichen oder einem eng verwandten Thema gibt.
   - Wenn eine passende Notiz existiert: Lies sie mit `read_note`, dann nutze `update_note` um sie zu erweitern/verbessern. Du darfst die Notiz komplett neu schreiben — aber übernimm dabei ALLE bestehenden wertvollen Inhalte und ergänze das Neue sinnvoll integriert. Nichts Wichtiges darf verloren gehen.
   - Nutze deine bestehenden Notizen aktiv als Wissensquelle: Wenn du etwas erklärst oder planst, beziehe dich auf das was der Benutzer bereits notiert hat.
   - Erstelle nur dann eine NEUE Notiz, wenn es wirklich ein eigenständiges, neues Thema ist, das in keine bestehende Notiz passt.
   - WICHTIG: `update_note` ohne vorheriges `read_note` ist verboten — du würdest sonst bestehende Inhalte blind überschreiben. Lies immer zuerst.

5. **Wissensbasis aktiv verwalten**: Du kannst die Struktur des Second Brain aktiv organisieren — wie in einer IDE.
   - `create_folder`: neue Ordner anlegen
   - `rename_folder`: Ordner umbenennen
   - `move_note`: Notiz in einen anderen Ordner verschieben
   - `rename_note`: Notiz umbenennen (Titel ändern, ohne Inhalt anzufassen)
   - `delete_folder`: leere oder nicht mehr benötigte Ordner entfernen
   - Wenn der Benutzer bittet aufzuräumen oder umzustrukturieren, plane die Änderungen und schlage sie als konkrete Schritte vor.

6. **Dateien proaktiv ablegen**: Wenn Dateien (PDFs, Bilder, Dokumente) hochgeladen werden:
   - Erstelle eine Notiz im passenden Ordner
   - Bette die Datei ein: `![Beschreibung](URL)` für Bilder, `[📄 Dateiname](URL)` für PDFs/Dokumente
   - Verknüpfe die Datei über `attach_file_ids` damit sie im Ordner gespeichert wird
   - Füge eine Zusammenfassung/Beschreibung des Inhalts hinzu
   - Frage NICHT ob du es speichern sollst — tu es proaktiv

7. **Ordner kennen**: Nutze `list_folders` wenn du die aktuelle Ordnerstruktur brauchst (z.B. bevor du Notizen erstellst, verschiebst oder umstrukturierst). Die Struktur wird dir NICHT automatisch mitgegeben — hol sie dir bei Bedarf.

8a. **Bilder & Dokumente wirklich ansehen**: `search_images` und die gespeicherten Datei-Beschreibungen liefern dir nur eine Text-Zusammenfassung. Wenn diese für die Frage des Benutzers nicht ausreicht:
   - Bei Bildern: nutze `view_image` (mit image_id oder Dateiname), um das Originalbild WIRKLICH visuell zu sehen.
   - Bei Dokumenten (PDF, DOCX, XLSX, TXT, ...): nutze `view_document` (mit file_id oder Dateiname), um den TATSÄCHLICHEN Inhalt neu einzulesen — z.B. eine bestimmte Textstelle, Tabelle, Zahl oder ein Detail auf einer Seite.
   Rate nicht anhand der gespeicherten Zusammenfassung, wenn du die Originaldatei direkt prüfen kannst.

8. **Web-Recherche + Wissensbasis VEREINEN**: Du hast `search_notes` (dein Second Brain) und `web_search` (Internet).
   - Bei Wissensfragen: Suche ZUERST in den eigenen Notizen (`search_notes`), dann bei Bedarf im Web (`web_search`).
   - Verbinde beide Quellen in deiner Antwort und mache klar erkennbar, WAS WOHER kommt. Struktur zum Beispiel:
     - **Aus deinen Notizen:** was der Benutzer dazu bereits gespeichert hat (mit Verweis auf die Notiz-Titel)
     - **Neu aus dem Web:** was er noch nicht hatte, ergänzende/aktuelle Infos (mit Quellen)
     - **Fazit/Synthese:** wie beides zusammenpasst, was neu ist, was er ergänzen sollte
   - Wenn zu einem Thema noch nichts in den Notizen steht, sag das ehrlich und biete an, eine Notiz daraus zu erstellen.

## Antwortformat:
- Nutze Markdown: **Fettdruck** für Kernbegriffe, Aufzählungen, Überschriften (##) wo sinnvoll
- Strukturiere längere Antworten klar mit Absätzen
- Bei Brainstorming: Liste Ideen auf, diskutiere Pro/Contra, schlage nächste Schritte vor
- Bei Fragen zu Notizen: Fasse zusammen, verknüpfe, gib Kontext

## Proposals (Änderungen an der Wissensbasis):

Alle verändernden Aktionen (Notizen erstellen/ändern/löschen, Ordner anlegen/umbenennen/verschieben) werden dem Benutzer als VORSCHLÄGE vorgelegt — sie werden erst ausgeführt, wenn er sie annimmt. Sage NIE, dass du etwas bereits getan hast; sage, dass du es vorschlägst.

Schreibe Notiz-Inhalte immer in gut formatiertem Markdown mit Headings, Listen, Callouts.

## Sprache:
Antworte IMMER in der Sprache des Benutzers (Standard: Deutsch)."""


# ── Tool definitions (native function declarations) ───────────────────

def _get_agent_tools() -> list:
    """Define the tools available to the agent as Python functions for automatic calling."""

    # We use manual FunctionDeclarations for more control over descriptions
    search_notes = types.FunctionDeclaration(
        name="search_notes",
        description="Semantische und Volltextsuche über alle Notizen und Bilder des Benutzers. Nutze dies proaktiv um relevanten Kontext zu finden. Gibt standardmäßig bis zu 30 Treffer zurück.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchanfrage (semantisch + Volltext)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximale Anzahl Treffer (Standard 30, max 60). Nutze einen hohen Wert wenn du einen umfassenden Überblick über ein Thema brauchst.",
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
        description="Suche hochgeladene Dateien (Bilder UND Dokumente wie PDFs) anhand ihrer KI-generierten Beschreibungen oder Dateinamen. Gibt Text-Beschreibungen + image_id/file_id zurück. Nutze danach view_image (Bilder) bzw. view_document (PDFs/Dokumente), wenn du die Originaldatei WIRKLICH ansehen/nachlesen musst.",
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

    view_image = types.FunctionDeclaration(
        name="view_image",
        description=(
            "Sieh dir ein Bild WIRKLICH visuell an (nicht nur die gespeicherte Text-Beschreibung). "
            "Nutze dies, wenn die vorhandene Beschreibung nicht ausreicht — z.B. für Details, Farben, "
            "exaktes Layout, kleine Textstellen, Diagramm-Feinheiten, oder wenn der Benutzer eine genaue "
            "Frage zum Bildinhalt stellt. Das Originalbild wird dir danach direkt gezeigt. "
            "Übergib die image_id (aus search_images) ODER den Dateinamen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "image_id": {
                    "type": "string",
                    "description": "UUID des Bildes (bevorzugt, aus search_images)",
                },
                "filename": {
                    "type": "string",
                    "description": "Alternativ: Dateiname des Bildes",
                },
            },
        },
    )

    view_document = types.FunctionDeclaration(
        name="view_document",
        description=(
            "Öffne ein hochgeladenes Dokument (PDF, DOCX, XLSX, TXT, MD, CSV) und lies seinen "
            "TATSÄCHLICHEN Inhalt neu ein — nicht nur die gespeicherte Zusammenfassung. "
            "Nutze dies, wenn der Benutzer eine neue oder detaillierte Frage zu einem Dokument stellt, "
            "die die vorhandene Kurz-Zusammenfassung nicht beantwortet (z.B. eine bestimmte Textstelle, "
            "Tabelle, Zahl oder ein Detail auf einer bestimmten Seite). Übergib die file_id ODER den Dateinamen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "UUID des Dokuments (bevorzugt, aus search_images/Upload-Kontext)",
                },
                "filename": {
                    "type": "string",
                    "description": "Alternativ: Dateiname des Dokuments",
                },
                "question": {
                    "type": "string",
                    "description": "Optional: worauf du im Dokument achten sollst (fokussiert das Nachlesen)",
                },
            },
        },
    )

    create_note = types.FunctionDeclaration(
        name="create_note",
        description="Erstelle eine neue Notiz im Second Brain. Nutze dies wenn der Benutzer explizit eine Notiz erstellen möchte oder bei Datei-Uploads. Wenn Dateien (PDFs, Bilder) hochgeladen wurden, verknüpfe sie über attach_file_ids und bette sie im Content ein mit ![Beschreibung](URL) oder [Dateiname](URL).",
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
                    "description": "Inhalt der Notiz in Markdown. Bette Dateien ein mit: ![Bild](URL) für Bilder oder [📄 Dateiname](URL) für PDFs/Dokumente.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags für die Notiz (optional)",
                },
                "attach_file_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IDs der hochgeladenen Dateien die mit dieser Notiz verknüpft werden sollen (aus dem Upload-Kontext)",
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

    rename_note = types.FunctionDeclaration(
        name="rename_note",
        description="Benenne eine Notiz um (ändert NUR den Titel, nicht den Inhalt). Nutze dies statt update_note wenn du nur den Titel ändern willst.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "UUID der Notiz",
                },
                "new_title": {
                    "type": "string",
                    "description": "Neuer Titel der Notiz",
                },
            },
            "required": ["note_id", "new_title"],
        },
    )

    move_note = types.FunctionDeclaration(
        name="move_note",
        description="Verschiebe eine Notiz in einen anderen Ordner. Der Zielordner wird bei Bedarf automatisch erstellt.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "UUID der zu verschiebenden Notiz",
                },
                "target_folder_path": {
                    "type": "string",
                    "description": "Zielordner-Pfad, z.B. 'Projekte/Umzug'",
                },
            },
            "required": ["note_id", "target_folder_path"],
        },
    )

    create_folder = types.FunctionDeclaration(
        name="create_folder",
        description="Erstelle einen neuen (auch verschachtelten) Ordner. Übergeordnete Ordner im Pfad werden bei Bedarf automatisch mit erstellt.",
        parameters={
            "type": "object",
            "properties": {
                "folder_path": {
                    "type": "string",
                    "description": "Vollständiger Pfad des neuen Ordners, z.B. 'Projekte/2026/Umzug'",
                },
            },
            "required": ["folder_path"],
        },
    )

    rename_folder = types.FunctionDeclaration(
        name="rename_folder",
        description="Benenne einen bestehenden Ordner um. Alle Pfade von Unterordnern und Notizen werden automatisch mit aktualisiert.",
        parameters={
            "type": "object",
            "properties": {
                "folder_path": {
                    "type": "string",
                    "description": "Aktueller Pfad des Ordners, z.B. 'Projekte/Alt'",
                },
                "new_name": {
                    "type": "string",
                    "description": "Neuer Name des Ordners (nur der Name, nicht der ganze Pfad)",
                },
            },
            "required": ["folder_path", "new_name"],
        },
    )

    delete_folder = types.FunctionDeclaration(
        name="delete_folder",
        description="Lösche einen Ordner. ACHTUNG: löscht auch alle enthaltenen Notizen und Unterordner. Nutze dies nur wenn der Benutzer es explizit wünscht oder der Ordner leer ist.",
        parameters={
            "type": "object",
            "properties": {
                "folder_path": {
                    "type": "string",
                    "description": "Pfad des zu löschenden Ordners",
                },
            },
            "required": ["folder_path"],
        },
    )

    get_recent_notes = types.FunctionDeclaration(
        name="get_recent_notes",
        description="Hole die zuletzt bearbeiteten Notizen (chronologisch). Nützlich für Fragen wie 'Was habe ich zuletzt notiert?'.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Anzahl der Notizen (Standard 15, max 50)",
                },
            },
        },
    )

    web_search = types.FunctionDeclaration(
        name="web_search",
        description="Durchsuche das Internet nach aktuellen Informationen. Nutze dies für Fakten-Recherche, aktuelle Nachrichten, Produktinfos, Anleitungen, oder wenn der Benutzer etwas wissen will das nicht in seinen Notizen steht. Die Quellen-URLs werden dem Benutzer automatisch angezeigt.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchanfrage auf Deutsch oder Englisch",
                },
            },
            "required": ["query"],
        },
    )

    return [
        types.Tool(function_declarations=[
            search_notes,
            read_note,
            list_folders,
            list_notes_in_folder,
            search_images,
            view_image,
            view_document,
            get_recent_notes,
            create_note,
            update_note,
            delete_note,
            rename_note,
            move_note,
            create_folder,
            rename_folder,
            delete_folder,
            web_search,
        ]),
    ]


# ── Tool execution ────────────────────────────────────────────────────

async def _execute_tool(name: str, args: dict, user_id: str, db: AsyncSession) -> dict:
    """Execute a tool call and return the result as a dict."""
    try:
        if name == "search_notes":
            try:
                limit = int(args.get("limit") or 30)
            except (ValueError, TypeError):
                limit = 30
            limit = max(1, min(limit, 60))
            results = await hybrid_search(
                query=args.get("query", ""),
                user_id=user_id,
                db=db,
                limit=limit,
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

        elif name == "get_recent_notes":
            try:
                limit = int(args.get("limit") or 15)
            except (ValueError, TypeError):
                limit = 15
            limit = max(1, min(limit, 50))
            result = await db.execute(
                select(Note, Folder.path)
                .join(Folder, Note.folder_id == Folder.id)
                .where(Note.user_id == UUID(user_id))
                .order_by(Note.updated_at.desc())
                .limit(limit)
            )
            rows = result.all()
            return {
                "notes": [
                    {
                        "note_id": str(n.id),
                        "title": n.title,
                        "folder_path": path,
                        "preview": n.content[:300],
                        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
                    }
                    for n, path in rows
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
                        "file_id": str(img.id),
                        "filename": img.original_filename,
                        "content_type": img.content_type,
                        "is_document": img.content_type not in _VIEWABLE_IMAGE_TYPES,
                        "description": img.description[:500] if img.description else "",
                        "url": f"{backend_url}/uploads/{user_id}/{img.stored_filename}",
                    }
                    for img in images
                ]
            }

        elif name == "view_image":
            image_id = args.get("image_id", "")
            filename = args.get("filename", "")
            img = None
            # Resolve by id first, then by filename
            if image_id:
                try:
                    candidate = await db.get(Image, UUID(image_id))
                    if candidate and str(candidate.user_id) == user_id:
                        img = candidate
                except (ValueError, TypeError):
                    img = None
            if img is None and filename:
                res = await db.execute(
                    select(Image).where(
                        Image.user_id == UUID(user_id),
                        or_(
                            Image.original_filename == filename,
                            Image.stored_filename == filename,
                        ),
                    ).limit(1)
                )
                img = res.scalar_one_or_none()

            if img is None:
                return {"error": "Bild nicht gefunden"}

            if img.content_type not in _VIEWABLE_IMAGE_TYPES:
                return {
                    "error": f"Dieser Dateityp ({img.content_type}) kann nicht als Bild betrachtet werden.",
                    "description": img.description or "",
                }

            # Load the original bytes from disk
            try:
                file_path = Path(img.file_path)
                if not file_path.exists():
                    return {"error": "Bilddatei nicht mehr auf dem Datenträger vorhanden.",
                            "description": img.description or ""}
                image_bytes = file_path.read_bytes()
            except Exception as e:
                return {"error": f"Bild konnte nicht geladen werden: {str(e)[:120]}",
                        "description": img.description or ""}

            # Signal to the loop that a real image part must be attached.
            # (Bytes can't go into a JSON function_response, so the loop appends
            #  the image as a separate user-content part right after.)
            return {
                "status": "image_loaded",
                "filename": img.original_filename,
                "content_type": img.content_type,
                "_image_bytes": image_bytes,  # consumed by the loop, not sent as JSON
                "message": "Das Originalbild wird dir jetzt direkt gezeigt.",
            }

        elif name == "view_document":
            file_id = args.get("file_id", "")
            filename = args.get("filename", "")
            rec = None
            if file_id:
                try:
                    candidate = await db.get(Image, UUID(file_id))
                    if candidate and str(candidate.user_id) == user_id:
                        rec = candidate
                except (ValueError, TypeError):
                    rec = None
            if rec is None and filename:
                res = await db.execute(
                    select(Image).where(
                        Image.user_id == UUID(user_id),
                        or_(
                            Image.original_filename == filename,
                            Image.stored_filename == filename,
                        ),
                    ).limit(1)
                )
                rec = res.scalar_one_or_none()

            if rec is None:
                return {"error": "Dokument nicht gefunden"}

            ctype = rec.content_type
            if ctype not in _NATIVE_DOC_TYPES and ctype not in _TEXT_DOC_TYPES:
                return {
                    "error": f"Dieser Dateityp ({ctype}) kann nicht als Dokument gelesen werden.",
                    "description": rec.description or "",
                }

            try:
                file_path = Path(rec.file_path)
                if not file_path.exists():
                    return {"error": "Dokumentdatei nicht mehr auf dem Datenträger vorhanden.",
                            "description": rec.description or ""}
                doc_bytes = file_path.read_bytes()
            except Exception as e:
                return {"error": f"Dokument konnte nicht geladen werden: {str(e)[:120]}",
                        "description": rec.description or ""}

            # Plain-text docs: inline the text directly in the tool response
            if ctype in _TEXT_DOC_TYPES:
                try:
                    text_content = doc_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    text_content = doc_bytes.decode("latin-1", errors="replace")
                return {
                    "status": "document_text",
                    "filename": rec.original_filename,
                    "content": text_content[:50000],
                }

            # PDF / Office docs: attach as a real byte part so Gemini reads it natively
            return {
                "status": "document_loaded",
                "filename": rec.original_filename,
                "content_type": ctype,
                "_doc_bytes": doc_bytes,  # consumed by the loop, not sent as JSON
                "question": args.get("question", ""),
                "message": "Das Originaldokument wird dir jetzt direkt zum Nachlesen gezeigt.",
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
                    "attach_file_ids": args.get("attach_file_ids", []),
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

        elif name == "rename_note":
            # Resolve current title for a nicer proposal preview
            current_title = ""
            try:
                note = await db.get(Note, UUID(args.get("note_id", "")))
                if note and str(note.user_id) == user_id:
                    current_title = note.title
            except (ValueError, TypeError):
                pass
            return {
                "status": "proposal_created",
                "proposal": {
                    "type": "rename_note",
                    "note_id": args.get("note_id", ""),
                    "title": current_title,
                    "new_title": args.get("new_title", ""),
                },
            }

        elif name == "move_note":
            current_title = ""
            try:
                note = await db.get(Note, UUID(args.get("note_id", "")))
                if note and str(note.user_id) == user_id:
                    current_title = note.title
            except (ValueError, TypeError):
                pass
            return {
                "status": "proposal_created",
                "proposal": {
                    "type": "move_note",
                    "note_id": args.get("note_id", ""),
                    "title": current_title,
                    "target_folder_path": args.get("target_folder_path", ""),
                },
            }

        elif name == "create_folder":
            return {
                "status": "proposal_created",
                "proposal": {
                    "type": "create_folder",
                    "folder_path": args.get("folder_path", ""),
                },
            }

        elif name == "rename_folder":
            return {
                "status": "proposal_created",
                "proposal": {
                    "type": "rename_folder",
                    "folder_path": args.get("folder_path", ""),
                    "new_name": args.get("new_name", ""),
                },
            }

        elif name == "delete_folder":
            return {
                "status": "proposal_created",
                "proposal": {
                    "type": "delete_folder",
                    "folder_path": args.get("folder_path", ""),
                },
            }

        elif name == "web_search":
            # Execute a separate Gemini call with Google Search grounding
            query = args.get("query", "")
            try:
                search_client = get_client()
                search_response = await search_client.aio.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=f"Recherchiere: {query}\n\nGib eine präzise, faktenbasierte Zusammenfassung.",
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    ),
                )
                # Extract grounding sources — try multiple attribute paths
                sources = []
                if search_response.candidates:
                    candidate = search_response.candidates[0]
                    gm = getattr(candidate, 'grounding_metadata', None)

                    if gm:
                        # Try grounding_chunks (newer SDK)
                        chunks = getattr(gm, 'grounding_chunks', None)
                        if chunks:
                            for gc in chunks:
                                web = getattr(gc, 'web', None)
                                if web:
                                    title = getattr(web, 'title', '') or ''
                                    url = getattr(web, 'uri', '') or getattr(web, 'url', '') or ''
                                    if url:
                                        sources.append({"title": title, "url": url})

                        # Fallback: try grounding_supports → grounding_chunk_indices → retrieve from search_entry_point
                        if not sources:
                            supports = getattr(gm, 'grounding_supports', None)
                            if supports:
                                for sup in supports:
                                    segment = getattr(sup, 'segment', None) or getattr(sup, 'web', None)
                                    if segment:
                                        url = getattr(segment, 'uri', '') or getattr(segment, 'url', '') or ''
                                        title = getattr(segment, 'title', '') or ''
                                        if url:
                                            sources.append({"title": title, "url": url})

                        # Fallback: search_entry_point may have rendered HTML with links
                        if not sources:
                            sep = getattr(gm, 'search_entry_point', None)
                            if sep:
                                rendered = getattr(sep, 'rendered_content', '') or ''
                                # Extract URLs from rendered HTML
                                import re as _re
                                urls_found = _re.findall(r'href="(https?://[^"]+)"', rendered)
                                for url in urls_found[:5]:
                                    domain = url.split('/')[2] if '/' in url else url
                                    sources.append({"title": domain, "url": url})

                    # Deduplicate by URL
                    seen_urls = set()
                    unique_sources = []
                    for s in sources:
                        if s["url"] and s["url"] not in seen_urls:
                            seen_urls.add(s["url"])
                            unique_sources.append(s)
                    sources = unique_sources[:8]  # Max 8 sources

                logger.info(f"Web search '{query}': {len(sources)} sources found")
                return {
                    "answer": search_response.text or "",
                    "sources": sources,
                }
            except Exception as e:
                logger.error(f"Web search failed: {e}")
                return {"error": f"Web-Suche fehlgeschlagen: {str(e)[:150]}"}

        else:
            return {"error": f"Unbekanntes Tool: {name}"}

    except Exception as e:
        logger.error(f"Tool execution error ({name}): {e}")
        return {"error": str(e)}


# ── Build multi-turn contents from chat history ───────────────────────

# History truncation limits — keep recent turns verbatim, summarize the rest.
MAX_HISTORY_MESSAGES = 20        # how many recent messages to keep in full
MAX_MSG_CHARS = 6000             # cap on a single message's length


def _build_contents(chat_history: list[dict], image_context: list[dict] | None = None) -> list[types.Content]:
    """Convert DB chat history into proper multi-turn contents for the API.

    Long histories are truncated: only the most recent MAX_HISTORY_MESSAGES are
    kept verbatim. Older messages are condensed into a single summary turn so the
    context window stays manageable over very long sessions.
    """
    history = chat_history or []

    # Clean + normalize all messages first
    cleaned: list[dict] = []
    for msg in history:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = re.sub(r'<!-- AGENT_META[\s\S]*?AGENT_META -->', '', msg.get("content", "")).strip()
        if not text:
            continue
        # Cap individual message length to avoid a single huge note dominating context
        if len(text) > MAX_MSG_CHARS:
            text = text[:MAX_MSG_CHARS] + "\n… (gekürzt)"
        cleaned.append({"role": role, "text": text})

    contents: list[types.Content] = []

    # If the history is long, condense everything except the last N messages
    if len(cleaned) > MAX_HISTORY_MESSAGES:
        older = cleaned[:-MAX_HISTORY_MESSAGES]
        recent = cleaned[-MAX_HISTORY_MESSAGES:]

        summary_lines = []
        for m in older:
            label = "Benutzer" if m["role"] == "user" else "Assistent"
            snippet = m["text"].replace("\n", " ")
            if len(snippet) > 200:
                snippet = snippet[:200] + "…"
            summary_lines.append(f"- {label}: {snippet}")
        summary_text = (
            "[Zusammenfassung des bisherigen Gesprächsverlaufs (ältere Nachrichten, gekürzt)]\n"
            + "\n".join(summary_lines)
        )
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=summary_text)],
        ))
        # Acknowledge so the summary sits in a valid user→model turn structure
        contents.append(types.Content(
            role="model",
            parts=[types.Part.from_text(text="Verstanden, ich habe den bisherigen Kontext.")],
        ))
    else:
        recent = cleaned

    for m in recent:
        contents.append(types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part.from_text(text=m["text"])],
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

    # Build multi-turn conversation (with truncation of long histories)
    contents = _build_contents(chat_history or [], image_context)

    # Augment the current user message with context
    user_message_parts = []

    # Add file context if present (images, PDFs, documents)
    if image_context:
        file_text = "\n\n---\n**Hochgeladene Dateien:**\n"
        for f in image_context:
            file_type = f.get("type", "document")
            icon = "📷" if file_type == "image" else "📄"
            file_text += f"\n{icon} **{f['filename']}** (file_id: `{f.get('file_id', '')}`)\n"
            file_text += f"URL: {f['url']}\n"
            file_text += f"Analyse: {f['description']}\n"
        file_text += "\nLege diese Dateien proaktiv in einem passenden Ordner ab."
        file_text += "\nNutze `attach_file_ids` mit den file_ids um die Dateien mit der Notiz zu verknüpfen."
        file_text += "\nBette sie im Content ein: `![Beschreibung](URL)` für Bilder, `[📄 Dateiname](URL)` für PDFs.\n"
        user_message_parts.append(instruction + file_text)
    else:
        user_message_parts.append(instruction)

    # NOTE: The folder structure is no longer appended to every message.
    # The agent fetches it on demand via the `list_folders` tool, which keeps
    # the context lean over long sessions.

    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message_parts[0])],
    ))

    # Agent config — enable thought summaries so the UI can surface the reasoning
    try:
        thinking_config = types.ThinkingConfig(include_thoughts=True)
    except Exception:
        thinking_config = None

    config = types.GenerateContentConfig(
        system_instruction=AGENT_SYSTEM_INSTRUCTION,
        tools=_get_agent_tools(),
        temperature=0.8,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        **({"thinking_config": thinking_config} if thinking_config else {}),
    )

    proposals = []
    steps = []
    max_tool_rounds = 15  # allow deeper multi-step reasoning for complex tasks

    for round_num in range(max_tool_rounds + 1):
        # For tool rounds (not the last), use non-streaming to avoid thought_signature issues
        # For the final response (no function calls), stream it
        full_text_parts = []
        function_calls = []

        if round_num > 0:
            # After first round, we know we're in tool-calling mode
            # Use non-streaming to get complete response with all signatures intact
            response = await client.aio.models.generate_content(
                model=AGENT_MODEL,
                contents=contents,
                config=config,
            )

            # Extract function calls and text from complete response
            if response.candidates and response.candidates[0].content:
                candidate_content = response.candidates[0].content
                # Add complete model response to history (preserves signatures)
                contents.append(candidate_content)

                for part in candidate_content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        function_calls.append(part.function_call)
                    elif hasattr(part, 'text') and part.text:
                        if hasattr(part, 'thought') and part.thought:
                            yield {"type": "thinking", "content": part.text}
                        else:
                            full_text_parts.append(part.text)

            # Stream text that was generated
            full_text = "".join(full_text_parts)
            if full_text:
                yield {"type": "chunk", "content": full_text}

        else:
            # First round: stream the response for immediate UX feedback
            all_response_parts = []

            async for chunk in await client.aio.models.generate_content_stream(
                model=AGENT_MODEL,
                contents=contents,
                config=config,
            ):
                # Collect all parts for replay + separate thoughts from answer text
                emitted_via_parts = False
                if chunk.candidates:
                    for candidate in chunk.candidates:
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                all_response_parts.append(part)
                                # Thought summary parts → stream as "thinking"
                                if getattr(part, 'thought', False) and getattr(part, 'text', None):
                                    emitted_via_parts = True
                                    yield {"type": "thinking", "content": part.text}
                                elif getattr(part, 'text', None) and not getattr(part, 'function_call', None):
                                    emitted_via_parts = True
                                    full_text_parts.append(part.text)
                                    yield {"type": "chunk", "content": part.text}

                # Capture function calls
                fc_list = chunk.function_calls
                if fc_list:
                    function_calls.extend(fc_list)
                elif not emitted_via_parts:
                    # Fallback for chunks whose parts weren't iterable above
                    try:
                        text = chunk.text
                        if text:
                            full_text_parts.append(text)
                            yield {"type": "chunk", "content": text}
                    except Exception:
                        pass

            # Add model response to contents (with all signatures)
            if all_response_parts:
                contents.append(types.Content(role="model", parts=all_response_parts))

        # If no function calls, we're done — response already streamed
        if not function_calls:
            break

        # If we've exhausted rounds, break
        if round_num >= max_tool_rounds:
            break

        # For round 0, model response already added to contents above
        # For round > 0, model response already added via candidate_content

        # Execute each function call and build function responses
        function_response_parts = []
        pending_images_to_show = []  # real image bytes to show the model after the tool turn
        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            # Build human-friendly step description
            step_labels = {
                "search_notes": "Suche",
                "read_note": "Lese Notiz",
                "list_folders": "Ordner laden",
                "list_notes_in_folder": "Notizen laden",
                "search_images": "Bilder suchen",
                "view_image": "Bild ansehen",
                "view_document": "Dokument lesen",
                "get_recent_notes": "Neueste Notizen",
                "create_note": "Erstelle Notiz",
                "update_note": "Bearbeite Notiz",
                "delete_note": "Lösche Notiz",
                "rename_note": "Benenne Notiz um",
                "move_note": "Verschiebe Notiz",
                "create_folder": "Erstelle Ordner",
                "rename_folder": "Benenne Ordner um",
                "delete_folder": "Lösche Ordner",
                "web_search": "Web-Recherche",
            }
            label = step_labels.get(tool_name, tool_name)
            detail = ""
            if tool_args.get("query"):
                detail = f' „{tool_args["query"]}"'
            elif tool_args.get("new_name"):
                detail = f' → „{tool_args["new_name"]}"'
            elif tool_args.get("target_folder_path"):
                detail = f' → {tool_args["target_folder_path"]}'
            elif tool_args.get("title"):
                detail = f' „{tool_args["title"]}"'
            elif tool_args.get("folder_path"):
                detail = f' in {tool_args["folder_path"]}'
            step_desc = f"{label}{detail}"

            yield {"type": "tool_call", "content": step_desc}
            steps.append({"type": "tool_call", "content": step_desc})

            # Execute
            result = await _execute_tool(tool_name, tool_args, user_id, db)

            # Check if this generated a proposal
            if result.get("status") == "proposal_created":
                proposal = result["proposal"]
                proposals.append(proposal)
                yield {"type": "proposal", "proposal": proposal}
                # IMPORTANT: Tell the model clearly that this is NOT yet applied
                result = {
                    "status": "pending_approval",
                    "message": f"HINWEIS: Die Änderung ({proposal['type']}) wurde NICHT ausgeführt. Sie wurde als Vorschlag dem Benutzer zur Bestätigung vorgelegt. Sage dem Benutzer, dass du einen Vorschlag erstellt hast den er annehmen oder ablehnen kann. Sage NICHT dass du die Notiz bereits erstellt/geändert/gelöscht hast.",
                }

            # ── view_image / view_document: pull out raw bytes to attach as a real part ──
            pending_image = None
            if result.get("status") == "image_loaded" and result.get("_image_bytes"):
                pending_image = {
                    "bytes": result.pop("_image_bytes"),
                    "mime": result.get("content_type", "image/png"),
                    "filename": result.get("filename", "Bild"),
                    "kind": "image",
                }
            elif result.get("status") == "document_loaded" and result.get("_doc_bytes"):
                pending_image = {
                    "bytes": result.pop("_doc_bytes"),
                    "mime": result.get("content_type", "application/pdf"),
                    "filename": result.get("filename", "Dokument"),
                    "kind": "document",
                }
            else:
                # Ensure no stray bytes ever end up in the JSON response
                result.pop("_image_bytes", None)
                result.pop("_doc_bytes", None)

            # Summarize result for streaming UI
            result_summary = _summarize_tool_result(tool_name, result)
            yield {"type": "tool_result", "content": result_summary}
            steps.append({"type": "tool_result", "content": result_summary})

            # Emit sources from web_search
            if tool_name == "web_search" and result.get("sources"):
                yield {"type": "sources", "sources": result["sources"]}

            # Build function response part
            function_response_parts.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=result,
                )
            )

            # If an image was loaded, remember it to append after the tool turn
            if pending_image:
                pending_images_to_show.append(pending_image)

        # Add function responses to contents
        contents.append(types.Content(role="tool", parts=function_response_parts))

        # Attach any actual images/documents the model asked to view, as real
        # user-content parts so the multimodal model can genuinely SEE/READ them.
        if pending_images_to_show:
            media_parts = []
            for pi in pending_images_to_show:
                if pi.get("kind") == "document":
                    label = f"[Originaldokument: {pi['filename']} — lies es dir jetzt genau durch]"
                else:
                    label = f"[Originalbild: {pi['filename']} — sieh es dir jetzt genau an]"
                media_parts.append(types.Part.from_text(text=label))
                try:
                    media_parts.append(types.Part.from_bytes(data=pi["bytes"], mime_type=pi["mime"]))
                except Exception as e:
                    logger.warning(f"Could not attach media bytes ({pi.get('kind')}): {e}")
            if media_parts:
                contents.append(types.Content(role="user", parts=media_parts))
            pending_images_to_show = []

        # Continue the loop — model will generate a follow-up response

    yield {"type": "done", "proposals": proposals, "steps": steps}


def _summarize_tool_result(tool_name: str, result: dict) -> str:
    """Create a short human-readable summary of a tool result for the streaming UI."""
    if "error" in result:
        return f"❌ {result['error'][:80]}"

    if tool_name == "search_notes":
        count = len(result.get("results", []))
        return f"{count} Ergebnisse gefunden"
    elif tool_name == "read_note":
        title = result.get("title", "?")
        return f'"{title}" gelesen'
    elif tool_name == "list_folders":
        count = len(result.get("folders", []))
        return f"{count} Ordner geladen"
    elif tool_name == "list_notes_in_folder":
        count = len(result.get("notes", []))
        return f"{count} Notizen geladen"
    elif tool_name == "search_images":
        count = len(result.get("images", []))
        return f"{count} Bilder gefunden"
    elif tool_name == "view_image":
        if result.get("status") == "image_loaded":
            return f'Bild „{result.get("filename", "?")}" angesehen'
        return "Bild konnte nicht geladen werden"
    elif tool_name == "view_document":
        if result.get("status") in ("document_loaded", "document_text"):
            return f'Dokument „{result.get("filename", "?")}" gelesen'
        return "Dokument konnte nicht geladen werden"
    elif tool_name == "get_recent_notes":
        count = len(result.get("notes", []))
        return f"{count} Notizen geladen"
    elif tool_name == "create_note":
        return "Vorschlag erstellt"
    elif tool_name == "update_note":
        return "Änderung vorgeschlagen"
    elif tool_name == "delete_note":
        return "Löschung vorgeschlagen"
    elif tool_name == "rename_note":
        return "Umbenennung vorgeschlagen"
    elif tool_name == "move_note":
        return "Verschiebung vorgeschlagen"
    elif tool_name == "create_folder":
        return "Ordner-Erstellung vorgeschlagen"
    elif tool_name == "rename_folder":
        return "Ordner-Umbenennung vorgeschlagen"
    elif tool_name == "delete_folder":
        return "Ordner-Löschung vorgeschlagen"
    elif tool_name == "web_search":
        count = len(result.get("sources", []))
        return f"Web-Recherche: {count} Quellen"
    else:
        return "Erledigt"


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
