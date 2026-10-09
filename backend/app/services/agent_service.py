"""
Agentic Workspace Service — true multi-turn, function-calling agent using
the primary reasoning model (PRO_MODEL) with thinking and streaming.

Architecture:
- Uses OpenAI's Responses API with native function calling
- Multi-turn chat: real conversation history with proper roles
- The UI uses status phrases and response chunks; provider reasoning remains private
- Autonomous tool loop: model decides when to call tools, we execute and feed back
"""

import json
import re
import time
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, AsyncGenerator
from uuid import UUID

from app.services.openai_compat import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.config import get_settings
from app.models import Note, Folder, Tag, Image, note_tags
from app.services.ai_service import get_client, PRO_MODEL, FLASH_MODEL
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

AGENT_MODEL = PRO_MODEL  # primary reasoning model (thinking + grounding)

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
     (c) ein Gespräch ist zu einem klaren, abgeschlossenen Ergebnis gekommen, das der Benutzer sichtbar behalten will.
   - Beim Brainstormen, Ideen sammeln, Nachdenken, Rückfragen beantworten, Pläne durchsprechen: erstelle KEINE Notiz. Das ist einfach nur Gespräch. Auch wenn das Gespräch inhaltlich stark ist — nicht jeder gute Gedanke muss sofort abgespeichert werden.
   - Wenn du erkennst, dass etwas wirklich ins Second Brain gehört: Tue es einfach direkt — OHNE nachzufragen und OHNE es anzukündigen. Kein "Soll ich?", kein "Ich schlage vor", kein "Ich habe einen Entwurf erstellt". Handeln, fertig.
   - Lieber ein Gespräch zu wenig verschriftlicht als der Chat voller Rückfragen.

4. **BEARBEITEN STATT NEU ANLEGEN — sehr wichtig**: Dein Standardverhalten ist, bestehende Notizen zu ERWEITERN und zu PFLEGEN, nicht ständig neue anzulegen.
   - Bevor du eine neue Notiz erstellst, suche IMMER zuerst mit `search_notes` ob es schon eine Notiz zum gleichen oder einem eng verwandten Thema gibt. EINE breite Suche reicht in der Regel — kombiniere verwandte Begriffe statt mehrerer Einzelsuchen.
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
   - `web_search` ist TEUER (löst einen eigenen Recherche-Durchlauf aus) — nutze es nur bei echten Wissens-/Aktualitätsfragen, nicht routinemäßig bei jeder Anfrage.

9. **Sparsam mit Tool-Aufrufen**: Du hast ein begrenztes Kontingent an Tool-Runden pro Antwort. Plane deine Suchen effizient:
   - Fasse verwandte Suchbegriffe in EINER `search_notes`-Anfrage zusammen, statt sie nacheinander einzeln abzusetzen.
   - Wiederhole eine Suche NICHT mit nur leicht abgewandelten Begriffen ("Sponsor", dann "Sponsoring", dann "Sponsor Modell") — das ist Verschwendung. Wenn die erste Suche nichts Passendes fand, probiere einen grundlegend anderen Blickwinkel, nicht dieselbe Formulierung.
   - Wenn du nach 2-3 Suchen genug Kontext hast, antworte — du musst nicht jeden Stein umdrehen.

## QUELLEN ZITIEREN — wichtig:

Jedes Tool-Ergebnis, das eine Quelle liefert (Notizen aus `search_notes`/`read_note`/`get_recent_notes`/`list_notes_in_folder`, Web-Treffer aus `web_search`, Dateien aus `search_images`), enthält ein Feld `cite` mit einer Zahl.

Wenn du eine Information aus einer solchen Quelle verwendest, setze direkt hinter die betreffende Passage den Marker `[[cite:N]]` — mit genau der Zahl aus dem `cite`-Feld.

Regeln:
- Setze den Marker ans ENDE des Satzes oder Absatzes, der die Information enthält — nach dem Punkt.
- Mehrere Quellen für eine Passage: `[[cite:2]][[cite:5]]` direkt hintereinander.
- Zitiere nur, wenn die Information wirklich aus dieser Quelle kommt. Eigene Schlussfolgerungen, Vorschläge und allgemeines Wissen brauchen KEINEN Marker.
- Erfinde NIEMALS Zahlen. Nutze ausschließlich `cite`-Werte, die du tatsächlich in einem Tool-Ergebnis gesehen hast.
- Schreibe die Marker als reinen Text, nicht in Code-Blöcken, nicht in Backticks.
- Erwähne die Marker nicht im Fließtext („wie in Quelle 3 beschrieben") — sie werden dem Benutzer automatisch als klickbare Quellenangabe angezeigt.

Beispiel:
„Dein Autokredit läuft noch bis März 2027 mit 312 € monatlich. [[cite:1]] Laut aktuellen Marktdaten liegen vergleichbare Zinssätze derzeit bei etwa 4,2 %. [[cite:4]] Eine Umschuldung könnte sich also lohnen — das würde ich an deiner Stelle prüfen."

## Antwortformat:
- Nutze Markdown: **Fettdruck** für Kernbegriffe, Aufzählungen, Überschriften (##) wo sinnvoll
- Strukturiere längere Antworten klar mit Absätzen
- Bei Brainstorming: Liste Ideen auf, diskutiere Pro/Contra, schlage nächste Schritte vor
- Bei Fragen zu Notizen: Fasse zusammen, verknüpfe, gib Kontext

## Verhalten beim Speichern:

Alle verändernden Aktionen (Notizen erstellen/ändern/löschen, Ordner anlegen/umbenennen/verschieben) werden **sofort und ohne Rückfrage ausgeführt**. Kündige sie NICHT im Chat an, frage NICHT nach Bestätigung. Tu es einfach. Der Benutzer sieht die Änderung im UI direkt.

Schreibe Notiz-Inhalte immer in gut formatiertem Markdown mit Headings, Listen, Callouts.

10. **Forge Fitness & Ernährungs-Daten**: Du hast Zugriff auf die Forge-App des Benutzers mit drei Tools:
   - `get_fitness_overview` — Profil, Gewichtsverlauf, Trainingsplan, Coaching-Briefings. Nutze dies bei Fragen zu Zielen, Fortschritt oder allgemeinem Fitnessstatus.
   - `get_workout_data` — Workouts der letzten Tage/Wochen, letztes Training, oder die History einer bestimmten Übung (z.B. Bench Press). Nutze dies bei Fragen zu Training, Volumen, PRs, Trainingshäufigkeit.
   - `get_health_data` — Ernährung (Kalorien, Makros, Mahlzeiten), Schritte, Schlaf. Nutze dies bei Fragen zu Kalorien, Protein, Defizit/Überschuss, Aktivität oder Schlaf.
   - Kombiniere Forge-Daten aktiv mit deinen Notizen: Wenn der Benutzer über Training oder Ernährung spricht, schaue sowohl in seinen Notizen als auch in Forge.
   - Forge-Daten sind Live-Daten aus der App — keine historischen Snapshots in den Notizen nötig.

11. **Vesti Garderobe**: Du hast Zugriff auf die Vesti-App des Benutzers mit zwei Tools:
   - `get_wardrobe` — Lädt Kleidungsstücke, Uhren, Düfte und/oder Accessoires mit allen Details. Nutze dies für Fragen zu konkreten Stücken, Outfit-Planung oder Bestandsübersichten. Wähle gezielt nur die relevanten Kategorien (z.B. nur `include_clothing=true` wenn es ums Outfit geht).
   - `get_wardrobe_analytics` — Fertige Auswertungen: Stilverteilung, Investitionswerte, Service-Fälligkeiten, Lücken und Empfehlungen. Nutze dies für strategische Fragen: 'Was fehlt in meiner Garderobe?', 'Was dominiert meinen Stil?', 'Wie viel sind meine Uhren wert?', 'Welche Düfte gehen bald zur Neige?'.
   - Bei Outfit-Fragen: Lade die relevanten Kategorien und schlage konkrete Kombinationen vor basierend auf Stil, Anlass und Saison.
   - Vesti-Daten sind Live-Daten — immer aktuell, nicht in Notizen zwischenspeichern.

12. **Glowup Routinen & Gewohnheiten**: Du hast Zugriff auf die Glowup-App des Benutzers mit drei Tools:
   - `list_routines` — Kompakte Übersicht aller Routinen (Name, ID, Typ, Frequenz). Nutze dies als ersten Schritt wenn der Benutzer nach seinen Gewohnheiten oder Routinen fragt, oder bevor du mit den anderen Tools tiefer einsteigst.
   - `get_routine_summary` — Schedule-bewusste Performance-Zusammenfassung einer Routine: Streaks, Erfolgsquote, Fehlschläge. Nutze dies für: 'Wie gut halte ich X durch?', 'Wie ist mein Streak?', 'Zeig mir meine Performance'.
   - `get_routine_entries` — Rohe Tageseinträge einer Routine mit Status, Wert, Notiz, Mood und Energy. Nutze dies wenn konkrete Einzel-Daten gefragt sind: 'Was habe ich diese Woche eingetragen?', 'An welchen Tagen habe ich gefehlt?'.
   - Workflow: Starte meist mit `list_routines` um die IDs zu kennen, dann hole Details mit Summary oder Entries.
   - Verbinde Glowup-Daten mit Notizen: Wenn der Benutzer über Gewohnheiten, Selbstentwicklung oder Tagesstruktur spricht, prüfe sowohl seine Notizen als auch Glowup.
   - Glowup-Daten sind Live-Daten — immer aktuell, nicht in Notizen zwischenspeichern.

## Sprache:
Antworte IMMER in der Sprache des Benutzers (Standard: Deutsch)."""


# ── Tool definitions (native function declarations) ───────────────────

def _get_agent_tools() -> list:
    """Define the tools available to the agent as Python functions for automatic calling."""

    # We use manual FunctionDeclarations for more control over descriptions
    search_notes = types.FunctionDeclaration(
        name="search_notes",
        description=(
            "Semantische und Volltextsuche über alle Notizen und Bilder des Benutzers. "
            "Gibt standardmäßig bis zu 5 Treffer zurück. WICHTIG: Formuliere EINE breite, "
            "kombinierte Suchanfrage statt mehrerer eng verwandter Einzelsuchen (z.B. 'Sponsoring "
            "Kündigung Vertrag' statt drei separater Suchen für jeden Begriff). Wiederhole eine "
            "Suche NICHT mit nur leicht abgewandelten Begriffen, wenn die erste schon Treffer lieferte."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Breite Suchanfrage — kombiniere verwandte Begriffe in einem Aufruf",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximale Anzahl Treffer (Standard 5, max 10).",
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

    # ── Forge Fitness & Nutrition Tools ──────────────────────────────

    get_fitness_overview = types.FunctionDeclaration(
        name="get_fitness_overview",
        description=(
            "Ruft ein vollständiges Fitness-Profil aus der Forge-App ab: Nutzerprofil (Name, Größe, Sprache), "
            "aktuellen Trainingsplan, Gewichtsverlauf und Coaching-Briefings/Workout-Reviews. "
            "Nutze dies wenn der Benutzer nach seinem Trainingsstatus, Fortschritt, Gewicht, Zielen oder "
            "Coaching-Feedback fragt. days_weight steuert wie viele Tage Gewichtshistorie geladen werden."
        ),
        parameters={
            "type": "object",
            "properties": {
                "include_training_plan": {
                    "type": "boolean",
                    "description": "Trainingsplan einbeziehen (Standard: true)",
                },
                "days_weight": {
                    "type": "integer",
                    "description": "Wie viele Tage Gewichtshistorie (7–365, Standard: 90)",
                },
                "coaching_memory_limit": {
                    "type": "integer",
                    "description": "Anzahl Coaching-Briefings/Reviews (1–10, Standard: 3)",
                },
            },
        },
    )

    get_workout_data = types.FunctionDeclaration(
        name="get_workout_data",
        description=(
            "Ruft Workout-Daten aus der Forge-App ab. Kann das letzte Workout, eine Liste von Workouts "
            "der letzten N Tage, oder die komplette Historie einer bestimmten Übung liefern. "
            "Nutze dies für Fragen zu Trainings, Übungsfortschritt, Volumen, PRs oder Trainingshäufigkeit."
        ),
        parameters={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["latest", "history", "exercise_history"],
                    "description": (
                        "'latest' = letztes einzelnes Workout, "
                        "'history' = mehrere Workouts (steuerbar über limit/days), "
                        "'exercise_history' = alle Sätze einer bestimmten Übung"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Anzahl Workouts/Sessions (1–30, Standard: 10). Gilt für 'history' und 'exercise_history'.",
                },
                "days": {
                    "type": "integer",
                    "description": "Nur Workouts der letzten N Tage (1–365, Standard: 30). Gilt für 'history'.",
                },
                "exercise_name": {
                    "type": "string",
                    "description": "Exakter Übungsname (z.B. 'Bench Press'). Pflichtfeld für mode='exercise_history'.",
                },
            },
            "required": ["mode"],
        },
    )

    get_health_data = types.FunctionDeclaration(
        name="get_health_data",
        description=(
            "Ruft Gesundheits- und Ernährungsdaten aus der Forge-App ab: Kalorien, Makros, Mahlzeiten, "
            "Schritte, Schlaf. Kann einen einzelnen Tag oder einen Datumsbereich abfragen. "
            "Nutze dies für Fragen zu Ernährung, Kaloriendefizit/-überschuss, Makros, Schlaf oder Aktivität."
        ),
        parameters={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["day", "range", "steps", "sleep"],
                    "description": (
                        "'day' = Ernährung eines einzelnen Tages inkl. Ziele und Mahlzeiten, "
                        "'range' = Ernährungsübersicht mehrerer Tage (Makros + Kalorien), "
                        "'steps' = Schritte und Aktivitäts-kcal eines Tages, "
                        "'sleep' = Schlafdaten einer Nacht"
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Datum als YYYY-MM-DD. Standard: heute. Gilt für 'day', 'steps', 'sleep'.",
                },
                "days": {
                    "type": "integer",
                    "description": "Anzahl Tage für 'range' (1–14, Standard: 7).",
                },
                "include_food_items": {
                    "type": "boolean",
                    "description": "Bei mode='day': einzelne Lebensmittel pro Mahlzeit einbeziehen (Standard: false).",
                },
            },
            "required": ["mode"],
        },
    )

    # ── Vesti Wardrobe Tools ──────────────────────────────────────────

    get_wardrobe = types.FunctionDeclaration(
        name="get_wardrobe",
        description=(
            "Ruft die Garderobe des Benutzers aus der Vesti-App ab. Liefert Kleidungsstücke, Uhren, "
            "Düfte und/oder Accessoires mit allen Details (Marke, Material, Farbe, Stil, Anlass, Saison usw.). "
            "Alle Filter sind optional — ohne Filter kommt die komplette Kategorie zurück. "
            "String-Filter sind case-insensitive Substring-Matches (brand='rol' trifft 'Rolex'). "
            "Nutze dies für: 'Was habe ich für Hemden?', 'Welche Düfte passen zum Winter?', "
            "'Zeig mir meine Lieblingsuhren', 'Was kann ich zum Vorstellungsgespräch anziehen?'. "
            "Wähle gezielt die relevanten Kategorien — nicht alle gleichzeitig laden wenn nicht nötig."
        ),
        parameters={
            "type": "object",
            "properties": {
                # ── Clothing ───────────────────────────────────────────
                "include_clothing": {
                    "type": "boolean",
                    "description": "Kleidungsstücke laden (Hemden, Hosen, Jacken, Schuhe …)",
                },
                "clothing_category": {
                    "type": "string",
                    "description": "Kategorie-Filter für Kleidung, z.B. 'Oberteile', 'Hosen', 'Schuhe'",
                },
                "clothing_color": {
                    "type": "string",
                    "description": "Farb-Filter, z.B. 'Blau', 'Weiß'",
                },
                "clothing_style": {
                    "type": "string",
                    "description": "Stil-Filter, z.B. 'Business', 'Casual', 'Sportlich'",
                },
                "clothing_occasion": {
                    "type": "string",
                    "description": "Anlass-Filter, z.B. 'Formell', 'Alltag', 'Sport'",
                },
                "clothing_season": {
                    "type": "string",
                    "description": "Saison-Filter, z.B. 'Sommer', 'Winter', 'Ganzjährig'",
                },
                "clothing_brand": {
                    "type": "string",
                    "description": "Marken-Filter (Substring), z.B. 'Ralph'",
                },
                "clothing_favorite": {
                    "type": "boolean",
                    "description": "Nur Favoriten laden",
                },
                # ── Watches ────────────────────────────────────────────
                "include_watches": {
                    "type": "boolean",
                    "description": "Uhren laden",
                },
                "watches_brand": {
                    "type": "string",
                    "description": "Marken-Filter, z.B. 'Rolex', 'Omega'",
                },
                "watches_style": {
                    "type": "string",
                    "description": "Stil-Filter, z.B. 'Sport', 'Dress', 'Casual'",
                },
                "watches_occasion": {
                    "type": "string",
                    "description": "Anlass-Filter, z.B. 'Alltag', 'Formell'",
                },
                "watches_favorite": {
                    "type": "boolean",
                    "description": "Nur Favoriten laden",
                },
                # ── Fragrances ─────────────────────────────────────────
                "include_fragrances": {
                    "type": "boolean",
                    "description": "Düfte laden",
                },
                "fragrances_brand": {
                    "type": "string",
                    "description": "Marken-Filter, z.B. 'Dior', 'Chanel'",
                },
                "fragrances_family": {
                    "type": "string",
                    "description": "Duftfamilien-Filter (trifft family UND secondary_family), z.B. 'Holzig', 'Frisch'",
                },
                "fragrances_season": {
                    "type": "string",
                    "description": "Saison-Filter gegen seasons-Array, z.B. 'Winter', 'Sommer'",
                },
                "fragrances_occasion": {
                    "type": "string",
                    "description": "Anlass-Filter gegen occasions-Array, z.B. 'Alltag', 'Abend'",
                },
                "fragrances_concentration": {
                    "type": "string",
                    "description": "Konzentrations-Filter, z.B. 'EDP', 'EDT', 'Parfum'",
                },
                "fragrances_favorite": {
                    "type": "boolean",
                    "description": "Nur Favoriten laden",
                },
                # ── Accessories ────────────────────────────────────────
                "include_accessories": {
                    "type": "boolean",
                    "description": "Accessoires laden (Brillen, Gürtel, Taschen, Schmuck …)",
                },
                "accessories_type": {
                    "type": "string",
                    "description": "Typ-Filter, z.B. 'Sonnenbrille', 'Ring', 'Gürtel'",
                },
                "accessories_brand": {
                    "type": "string",
                    "description": "Marken-Filter, z.B. 'Ray-Ban', 'Cartier'",
                },
                "accessories_style": {
                    "type": "string",
                    "description": "Stil-Filter, z.B. 'Casual', 'Elegant'",
                },
                "accessories_occasion": {
                    "type": "string",
                    "description": "Anlass-Filter gegen occasions-Array, z.B. 'Alltag', 'Urlaub'",
                },
                "accessories_favorite": {
                    "type": "boolean",
                    "description": "Nur Favoriten laden",
                },
            },
        },
    )

    get_wardrobe_analytics = types.FunctionDeclaration(
        name="get_wardrobe_analytics",
        description=(
            "Ruft fertig aufbereitete Statistiken und Analysen der Vesti-Garderobe ab. "
            "Enthält Verteilungen (Stile, Marken, Materialien), Investitionswerte, Service-Fälligkeiten, "
            "Lücken-Analyse und Empfehlungen. "
            "Nutze dies bei übergeordneten Fragen: 'Was fehlt in meiner Garderobe?', "
            "'Wie viel sind meine Uhren wert?', 'Welche Düfte gehen bald zur Neige?', "
            "'Was dominiert meinen Stil?'. Lade nur die Kategorien die relevant sind."
        ),
        parameters={
            "type": "object",
            "properties": {
                "include_watches": {
                    "type": "boolean",
                    "description": "Uhr-Statistiken laden (Wert, Service, Stilverteilung)",
                },
                "include_fragrances": {
                    "type": "boolean",
                    "description": "Duft-Statistiken laden (Lagerbestand, Ablauf, Noten-Vielfalt)",
                },
                "include_accessories": {
                    "type": "boolean",
                    "description": "Accessoire-Statistiken laden",
                },
            },
        },
    )

    # ── Glowup Routine-Tracker Tools ─────────────────────────────────

    list_routines = types.FunctionDeclaration(
        name="list_routines",
        description=(
            "Listet alle Routinen des Benutzers aus der Glowup-App auf (kompakt, ohne Eintragshistorie). "
            "Nutze dies um einen Überblick zu bekommen: 'Welche Routinen habe ich?', "
            "'Zeig mir meine aktiven Gewohnheiten', 'Was tracke ich gerade?'. "
            "Liefert Name, ID, Typ, Frequenz und Status jeder Routine — "
            "anschließend kannst du mit get_routine_summary oder get_routine_entries tiefer einsteigen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "include_archived": {
                    "type": "boolean",
                    "description": "Archivierte Routinen einschließen (Standard: false)",
                },
                "name_query": {
                    "type": "string",
                    "description": "Namensteil zum Filtern, z.B. 'Sport' oder 'Morgen'",
                },
            },
        },
    )

    get_routine_summary = types.FunctionDeclaration(
        name="get_routine_summary",
        description=(
            "Schedule-bewusste Performance-Zusammenfassung einer einzelnen Routine: "
            "Streaks, Erfolgsquote, Fehlschläge und Trend — basierend auf dem Zeitfenster. "
            "Nutze dies bei Fragen zu Fortschritt oder Konsistenz einer bestimmten Routine: "
            "'Wie gut halte ich meine Morgenroutine durch?', 'Wie ist mein Streak bei X?', "
            "'Zeig mir meine Performance der letzten 30 Tage'. "
            "Hole dir zuerst die routine_id via list_routines wenn du sie noch nicht kennst."
        ),
        parameters={
            "type": "object",
            "properties": {
                "routine_id": {
                    "type": "string",
                    "description": "UUID der Routine (aus list_routines)",
                },
                "days": {
                    "type": "integer",
                    "enum": [7, 30, 90],
                    "description": "Analysefenster in Tagen — nur 7, 30 oder 90 erlaubt",
                },
            },
            "required": ["routine_id", "days"],
        },
    )

    get_routine_entries = types.FunctionDeclaration(
        name="get_routine_entries",
        description=(
            "Ruft die rohen Tageseinträge einer Routine ab: Status (done/skipped/missed), "
            "Wert, Notiz, Mood und Energy pro Tag. "
            "Nutze dies wenn du konkrete Einzeldaten brauchst: 'Was habe ich diese Woche eingetragen?', "
            "'Zeig mir meine Notizen zur Routine', 'An welchen Tagen habe ich gefehlt?'. "
            "Maximaler Zeitraum: 90 Tage. Hole dir zuerst die routine_id via list_routines."
        ),
        parameters={
            "type": "object",
            "properties": {
                "routine_id": {
                    "type": "string",
                    "description": "UUID der Routine (aus list_routines)",
                },
                "from": {
                    "type": "string",
                    "description": "Startdatum inklusiv (YYYY-MM-DD)",
                },
                "to": {
                    "type": "string",
                    "description": "Enddatum inklusiv (YYYY-MM-DD) — max. 90 Tage Abstand zu 'from'",
                },
            },
            "required": ["routine_id", "from", "to"],
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
            get_fitness_overview,
            get_workout_data,
            get_health_data,
            get_wardrobe,
            get_wardrobe_analytics,
            list_routines,
            get_routine_summary,
            get_routine_entries,
        ]),
    ]


# ── Tool execution ────────────────────────────────────────────────────

async def _execute_tool(name: str, args: dict, user_id: str, db: AsyncSession) -> dict:
    """Execute a tool call and return the result as a dict."""
    try:
        if name == "search_notes":
            try:
                limit = int(args.get("limit") or 5)
            except (ValueError, TypeError):
                limit = 5
            limit = max(1, min(limit, 10))
            results = await hybrid_search(
                query=args.get("query", ""),
                user_id=user_id,
                db=db,
                limit=limit,
            )
            # Filter out low-relevance results — passing noise to the LLM leads to
            # hallucinated connections and bloated context.
            MIN_SCORE = 0.35  # lower bar than teacher (workspace queries are broader)
            filtered = [r for r in results if r.get("score", 0) >= MIN_SCORE]
            # Always include at least the top 3 results even if below threshold,
            # so the model has something to work with on sparse knowledge bases.
            if len(filtered) < 3 and results:
                filtered = results[:3]
            return {
                "results": [
                    {
                        "note_id": r["note_id"],
                        "title": r["title"],
                        "folder_path": r["folder_path"],
                        "preview": r["content_preview"][:500],
                        "relevance": f"{round(r['score'] * 100)}%",
                    }
                    for r in filtered
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
            # Execute directly — no proposal flow
            from app.routes.agent_routes import _apply_create as _do_create, _apply_update as _do_update, _apply_delete as _do_delete, _apply_rename_note as _do_rename, _apply_move_note as _do_move, _apply_create_folder as _do_create_folder, _apply_rename_folder as _do_rename_folder, _apply_delete_folder as _do_delete_folder
            from app.services.vector_service import upsert_note_embedding, delete_note_embedding
            p = {
                "type": "create",
                "folder_path": args.get("folder_path", "Allgemein"),
                "title": args.get("title", "Neue Notiz"),
                "content": args.get("content", ""),
                "tags": args.get("tags", []),
                "attach_file_ids": args.get("attach_file_ids", []),
            }
            result = await _do_create(p, UUID(user_id), db)
            # Upsert embedding directly — no background_tasks available here
            try:
                await asyncio.to_thread(
                    upsert_note_embedding,
                    result["note_id"], user_id,
                    result.get("title", ""), args.get("content", ""),
                    result.get("folder_path", ""),
                )
            except Exception as emb_err:
                logger.warning(f"Embedding upsert failed for created note {result.get('note_id')}: {emb_err}")
            return {"status": "created", "note_id": result.get("note_id"), "title": result.get("title")}

        elif name == "update_note":
            from app.routes.agent_routes import _apply_update as _do_update
            from app.services.vector_service import upsert_note_embedding
            p = {
                "type": "update",
                "note_id": args.get("note_id", ""),
                "new_title": args.get("new_title"),
                "new_content": args.get("new_content"),
            }
            result = await _do_update(p, UUID(user_id), db)
            # Re-embed with the updated content/title
            try:
                updated_title = result.get("title", "")
                updated_content = args.get("new_content") or ""
                updated_folder = result.get("folder_path", "")
                if not updated_content:
                    # Reload from DB so we embed the full current content
                    from app.models import Note as _Note
                    note_obj = await db.get(_Note, UUID(result["note_id"]))
                    if note_obj:
                        updated_content = note_obj.content
                await asyncio.to_thread(
                    upsert_note_embedding,
                    result["note_id"], user_id,
                    updated_title, updated_content, updated_folder,
                )
            except Exception as emb_err:
                logger.warning(f"Embedding upsert failed for updated note {result.get('note_id')}: {emb_err}")
            return {"status": "updated", "note_id": result.get("note_id"), "title": result.get("title")}

        elif name == "delete_note":
            from app.routes.agent_routes import _apply_delete as _do_delete
            from app.services.vector_service import delete_note_embedding
            note_id_to_delete = args.get("note_id", "")
            p = {
                "type": "delete",
                "note_id": note_id_to_delete,
            }
            await _do_delete(p, UUID(user_id), db)
            try:
                await asyncio.to_thread(delete_note_embedding, note_id_to_delete)
            except Exception as emb_err:
                logger.warning(f"Embedding delete failed for note {note_id_to_delete}: {emb_err}")
            return {"status": "deleted"}

        elif name == "rename_note":
            from app.routes.agent_routes import _apply_rename_note as _do_rename
            from app.services.vector_service import upsert_note_embedding
            p = {
                "type": "rename_note",
                "note_id": args.get("note_id", ""),
                "new_title": args.get("new_title", ""),
            }
            result = await _do_rename(p, UUID(user_id), db)
            # Re-embed with new title (content unchanged)
            try:
                from app.models import Note as _Note
                note_obj = await db.get(_Note, UUID(result["note_id"]))
                if note_obj:
                    await asyncio.to_thread(
                        upsert_note_embedding,
                        result["note_id"], user_id,
                        result.get("title", ""), note_obj.content,
                        result.get("folder_path", ""),
                    )
            except Exception as emb_err:
                logger.warning(f"Embedding upsert failed for renamed note {result.get('note_id')}: {emb_err}")
            return {"status": "renamed", "note_id": result.get("note_id"), "title": result.get("title")}

        elif name == "move_note":
            from app.routes.agent_routes import _apply_move_note as _do_move
            from app.services.vector_service import upsert_note_embedding
            p = {
                "type": "move_note",
                "note_id": args.get("note_id", ""),
                "target_folder_path": args.get("target_folder_path", ""),
            }
            result = await _do_move(p, UUID(user_id), db)
            # Re-embed with updated folder_path
            try:
                from app.models import Note as _Note
                note_obj = await db.get(_Note, UUID(result["note_id"]))
                if note_obj:
                    await asyncio.to_thread(
                        upsert_note_embedding,
                        result["note_id"], user_id,
                        result.get("title", ""), note_obj.content,
                        result.get("folder_path", ""),
                    )
            except Exception as emb_err:
                logger.warning(f"Embedding upsert failed for moved note {result.get('note_id')}: {emb_err}")
            return {"status": "moved", "note_id": result.get("note_id"), "title": result.get("title")}

        elif name == "create_folder":
            from app.routes.agent_routes import _apply_create_folder as _do_create_folder
            p = {
                "type": "create_folder",
                "folder_path": args.get("folder_path", ""),
            }
            await _do_create_folder(p, UUID(user_id), db)
            return {"status": "folder_created", "folder_path": args.get("folder_path", "")}

        elif name == "rename_folder":
            from app.routes.agent_routes import _apply_rename_folder as _do_rename_folder
            from app.services.vector_service import upsert_note_embedding
            p = {
                "type": "rename_folder",
                "folder_path": args.get("folder_path", ""),
                "new_name": args.get("new_name", ""),
            }
            result = await _do_rename_folder(p, UUID(user_id), db)
            # Re-embed all notes that moved to the new folder path
            try:
                from app.models import Note as _Note, Folder as _Folder
                new_path = result.get("path", "")
                if new_path:
                    folder_result = await db.execute(
                        select(_Folder).where(_Folder.path == new_path, _Folder.user_id == UUID(user_id))
                    )
                    folder_obj = folder_result.scalar_one_or_none()
                    if folder_obj:
                        notes_result = await db.execute(
                            select(_Note).where(_Note.folder_id == folder_obj.id)
                        )
                        for note_obj in notes_result.scalars().all():
                            try:
                                await asyncio.to_thread(
                                    upsert_note_embedding,
                                    str(note_obj.id), user_id,
                                    note_obj.title, note_obj.content, new_path,
                                )
                            except Exception as emb_err:
                                logger.warning(f"Embedding upsert failed for note {note_obj.id} after folder rename: {emb_err}")
            except Exception as emb_err:
                logger.warning(f"Embedding re-index failed after folder rename: {emb_err}")
            return {"status": "folder_renamed"}

        elif name == "delete_folder":
            from app.routes.agent_routes import _apply_delete_folder as _do_delete_folder
            from app.services.vector_service import delete_note_embedding
            folder_path_to_delete = args.get("folder_path", "")
            # Collect note IDs before deletion so we can remove their embeddings
            deleted_note_ids: list[str] = []
            try:
                from app.models import Note as _Note, Folder as _Folder
                folders_result = await db.execute(
                    select(_Folder).where(
                        _Folder.user_id == UUID(user_id),
                        or_(
                            _Folder.path == folder_path_to_delete,
                            _Folder.path.like(f"{folder_path_to_delete}/%"),
                        ),
                    )
                )
                folder_ids = [f.id for f in folders_result.scalars().all()]
                if folder_ids:
                    notes_result = await db.execute(
                        select(_Note.id).where(_Note.folder_id.in_(folder_ids))
                    )
                    deleted_note_ids = [str(row[0]) for row in notes_result.all()]
            except Exception:
                pass
            p = {
                "type": "delete_folder",
                "folder_path": folder_path_to_delete,
            }
            await _do_delete_folder(p, UUID(user_id), db)
            for nid in deleted_note_ids:
                try:
                    await asyncio.to_thread(delete_note_embedding, nid)
                except Exception as emb_err:
                    logger.warning(f"Embedding delete failed for note {nid} after folder delete: {emb_err}")
            return {"status": "folder_deleted"}

        elif name == "web_search":
            # Execute a separate OpenAI Responses API call with built-in web search
            query = args.get("query", "")
            try:
                search_client = get_client()
                search_response = await search_client.aio.models.generate_content(
                    model=FLASH_MODEL,
                    contents=f"Recherchiere: {query}\n\nGib eine präzise, faktenbasierte Zusammenfassung.",
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(web_search=types.OpenAIWebSearch())],
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

        # ── Forge Fitness & Nutrition Tools ──────────────────────────────

        elif name == "get_fitness_overview":
            from app.services.forge_mcp_client import call_forge_tool

            include_plan = args.get("include_training_plan", True)
            days_weight = max(7, min(int(args.get("days_weight") or 90), 365))
            coaching_limit = max(1, min(int(args.get("coaching_memory_limit") or 3), 10))

            # Fire all calls concurrently
            profile_task = call_forge_tool("get_user_profile", {})
            weight_task = call_forge_tool("get_weight_history", {"days": days_weight})
            coaching_task = call_forge_tool("get_coaching_memory", {"limit": coaching_limit})
            plan_task = call_forge_tool("get_training_plan", {}) if include_plan else None

            if plan_task:
                profile, weight, coaching, plan = await asyncio.gather(
                    profile_task, weight_task, coaching_task, plan_task
                )
            else:
                profile, weight, coaching = await asyncio.gather(
                    profile_task, weight_task, coaching_task
                )
                plan = None

            result: dict = {}
            if not profile.get("error"):
                result["profile"] = profile
            if not weight.get("error"):
                result["weight_history"] = weight
            if not coaching.get("error"):
                result["coaching"] = coaching
            if plan and not plan.get("error"):
                result["training_plan"] = plan

            if not result:
                return {"error": "Forge konnte keine Daten liefern"}
            return result

        elif name == "get_workout_data":
            from app.services.forge_mcp_client import call_forge_tool

            mode = args.get("mode", "latest")

            if mode == "latest":
                return await call_forge_tool("get_latest_workout", {})

            elif mode == "history":
                limit = max(1, min(int(args.get("limit") or 10), 30))
                days = max(1, min(int(args.get("days") or 30), 365))
                return await call_forge_tool("get_workouts", {"limit": limit, "days": days})

            elif mode == "exercise_history":
                exercise_name = args.get("exercise_name", "").strip()
                if not exercise_name:
                    return {"error": "exercise_name ist erforderlich für mode='exercise_history'"}
                limit = max(1, min(int(args.get("limit") or 20), 30))
                return await call_forge_tool(
                    "get_exercise_history",
                    {"exercise_name": exercise_name, "limit": limit},
                )

            else:
                return {"error": f"Unbekannter mode: {mode}. Gültig: latest, history, exercise_history"}

        elif name == "get_health_data":
            from app.services.forge_mcp_client import call_forge_tool

            mode = args.get("mode", "day")
            date = args.get("date") or None  # None → server default = today

            if mode == "day":
                params: dict = {}
                if date:
                    params["date"] = date
                params["include_food_items"] = bool(args.get("include_food_items", False))
                return await call_forge_tool("get_nutrition_day", params)

            elif mode == "range":
                days = max(1, min(int(args.get("days") or 7), 14))
                return await call_forge_tool("get_nutrition_range", {"days": days})

            elif mode == "steps":
                params = {}
                if date:
                    params["date"] = date
                return await call_forge_tool("get_steps", params)

            elif mode == "sleep":
                params = {}
                if date:
                    params["date"] = date
                return await call_forge_tool("get_sleep", params)

            else:
                return {"error": f"Unbekannter mode: {mode}. Gültig: day, range, steps, sleep"}

        # ── Vesti Wardrobe Tools ──────────────────────────────────────────

        elif name == "get_wardrobe":
            from app.services.vesti_client import call_vesti

            # Build per-category filter dicts from prefixed args
            def _pick(prefix: str) -> dict:
                mapping = {
                    f"{prefix}_category":      "category",
                    f"{prefix}_color":         "color",
                    f"{prefix}_style":         "style",
                    f"{prefix}_occasion":      "occasion",
                    f"{prefix}_season":        "season",
                    f"{prefix}_brand":         "brand",
                    f"{prefix}_favorite":      "favorite",
                    f"{prefix}_type":          "type",
                    f"{prefix}_concentration": "concentration",
                    f"{prefix}_family":        "family",
                }
                return {v: args[k] for k, v in mapping.items() if k in args and args[k] is not None and args[k] != ""}

            tasks = {}
            if args.get("include_clothing", False):
                tasks["clothing"] = call_vesti("clothing", _pick("clothing"))
            if args.get("include_watches", False):
                tasks["watches"] = call_vesti("watches", _pick("watches"))
            if args.get("include_fragrances", False):
                tasks["fragrances"] = call_vesti("fragrances", _pick("fragrances"))
            if args.get("include_accessories", False):
                tasks["accessories"] = call_vesti("accessories", _pick("accessories"))

            # Default: load everything unfiltered if no category was specified
            if not tasks:
                tasks = {
                    "clothing":    call_vesti("clothing"),
                    "watches":     call_vesti("watches"),
                    "fragrances":  call_vesti("fragrances"),
                    "accessories": call_vesti("accessories"),
                }

            keys = list(tasks.keys())
            results = await asyncio.gather(*tasks.values())
            combined = {}
            for key, res in zip(keys, results):
                if not (isinstance(res, dict) and res.get("error")):
                    combined[key] = res
                else:
                    combined[key] = {"error": res.get("error")}

            if not any(
                not (isinstance(v, dict) and v.get("error")) for v in combined.values()
            ):
                return {"error": "Vesti konnte keine Daten liefern"}
            return combined

        elif name == "get_wardrobe_analytics":
            from app.services.vesti_client import call_vesti

            tasks = {}
            if args.get("include_watches", False):
                tasks["watches"] = call_vesti("analytics_watches")
            if args.get("include_fragrances", False):
                tasks["fragrances"] = call_vesti("analytics_fragrances")
            if args.get("include_accessories", False):
                tasks["accessories"] = call_vesti("analytics_accessories")

            # Default: load all analytics if nothing specified
            if not tasks:
                tasks = {
                    "watches":     call_vesti("analytics_watches"),
                    "fragrances":  call_vesti("analytics_fragrances"),
                    "accessories": call_vesti("analytics_accessories"),
                }

            keys = list(tasks.keys())
            results = await asyncio.gather(*tasks.values())
            combined = {}
            for key, res in zip(keys, results):
                if not (isinstance(res, dict) and res.get("error")):
                    combined[key] = res
                else:
                    combined[key] = {"error": res.get("error")}

            if not any(
                not (isinstance(v, dict) and v.get("error")) for v in combined.values()
            ):
                return {"error": "Vesti Analytics konnte keine Daten liefern"}
            return combined

        # ── Glowup Routine-Tracker Tools ──────────────────────────────────

        elif name == "list_routines":
            from app.services.glowup_mcp_client import call_glowup_tool

            arguments: dict = {}
            if args.get("include_archived") is not None:
                arguments["include_archived"] = bool(args["include_archived"])
            if args.get("name_query"):
                arguments["name_query"] = args["name_query"]
            return await call_glowup_tool("list_routines", arguments)

        elif name == "get_routine_summary":
            from app.services.glowup_mcp_client import call_glowup_tool

            routine_id = args.get("routine_id", "").strip()
            if not routine_id:
                return {"error": "routine_id ist erforderlich"}
            try:
                days = int(args.get("days", 30))
            except (ValueError, TypeError):
                days = 30
            if days not in (7, 30, 90):
                days = min((7, 30, 90), key=lambda d: abs(d - days))
            return await call_glowup_tool("get_routine_summary", {
                "routine_id": routine_id,
                "days": days,
            })

        elif name == "get_routine_entries":
            from app.services.glowup_mcp_client import call_glowup_tool

            routine_id = args.get("routine_id", "").strip()
            from_date = args.get("from", "").strip()
            to_date = args.get("to", "").strip()
            if not routine_id:
                return {"error": "routine_id ist erforderlich"}
            if not from_date or not to_date:
                return {"error": "'from' und 'to' sind erforderlich"}
            return await call_glowup_tool("get_routine_entries", {
                "routine_id": routine_id,
                "from": from_date,
                "to": to_date,
            })

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

# ── Short, natural German status phrases for the live activity line ───
# Kept to ~3 words, present tense, a touch playful — shown Gemini-style as a
# shimmering line that rotates as the agent moves from tool to tool.

_STATUS_PHRASES = {
    "search_notes": "Durchsucht deine Notizen",
    "read_note": "Liest eine Notiz",
    "list_folders": "Sieht Ordner durch",
    "list_notes_in_folder": "Öffnet einen Ordner",
    "search_images": "Sucht nach Bildern",
    "view_image": "Betrachtet ein Bild",
    "view_document": "Liest ein Dokument",
    "get_recent_notes": "Holt neueste Notizen",
    "create_note": "Schreibt eine Notiz",
    "update_note": "Aktualisiert eine Notiz",
    "delete_note": "Löscht eine Notiz",
    "rename_note": "Benennt Notiz um",
    "move_note": "Verschiebt eine Notiz",
    "create_folder": "Legt Ordner an",
    "rename_folder": "Benennt Ordner um",
    "delete_folder": "Löscht einen Ordner",
    "web_search": "Durchsucht das Web",
    "get_fitness_overview": "Prüft deinen Trainingsplan",
    "get_workout_data": "Schaut deine Workouts an",
    "get_health_data": "Checkt deine Ernährung",
    "get_wardrobe": "Schaut Klamotten durch",
    "get_wardrobe_analytics": "Analysiert deine Garderobe",
    "list_routines": "Lädt deine Routinen",
    "get_routine_summary": "Analysiert Routine-Performance",
    "get_routine_entries": "Liest Routine-Einträge",
}


def _status_phrase(tool_name: str) -> str:
    """Map a tool name to a short, natural German activity phrase."""
    return _STATUS_PHRASES.get(tool_name, "Arbeitet daran")


def _register_citations(
    tool_name: str,
    result: dict,
    citations: dict[str, dict],
    seen: dict[str, int],
) -> None:
    """Assign stable citation ids to every citable source in a tool result.

    Mutates ``result`` in place by adding a ``cite`` field to each source so the
    model sees the exact number it must use in ``[[cite:N]]`` markers. The
    ``citations`` registry is handed to the UI so each marker can be resolved to
    a clickable note or web link."""
    if not isinstance(result, dict) or "error" in result:
        return

    def _add(key: str, entry: dict) -> int:
        existing = seen.get(key)
        if existing is not None:
            return existing
        cid = len(citations) + 1
        seen[key] = cid
        citations[str(cid)] = entry
        return cid

    def _cite_note(item: dict) -> None:
        note_id = item.get("note_id")
        if not note_id:
            return
        item["cite"] = _add(f"note:{note_id}", {
            "type": "note",
            "note_id": note_id,
            "title": item.get("title", "") or "Notiz",
            "folder_path": item.get("folder_path", ""),
        })

    if tool_name == "search_notes":
        for item in result.get("results") or []:
            if isinstance(item, dict):
                _cite_note(item)
    elif tool_name in ("get_recent_notes", "list_notes_in_folder"):
        for item in result.get("notes") or []:
            if isinstance(item, dict):
                _cite_note(item)
    elif tool_name == "read_note":
        _cite_note(result)
    elif tool_name == "web_search":
        for item in result.get("sources") or []:
            if isinstance(item, dict) and item.get("url"):
                item["cite"] = _add(f"url:{item['url']}", {
                    "type": "web",
                    "url": item["url"],
                    "title": item.get("title", "") or item["url"],
                })
    elif tool_name == "search_images":
        for item in result.get("images") or []:
            if isinstance(item, dict) and item.get("image_id"):
                item["cite"] = _add(f"file:{item['image_id']}", {
                    "type": "file",
                    "file_id": item["image_id"],
                    "title": item.get("filename", "") or "Datei",
                    "url": item.get("url", ""),
                })


def _detail_from_tool_result(tool_name: str, result: dict) -> dict:
    """Pull out a compact, user-readable detail payload from a raw tool result.

    This is what the UI timeline shows under "Ergebnis". Everything that would
    make the chat unreadable (full note bodies, long base64, etc.) is trimmed."""
    if not isinstance(result, dict):
        return {"preview": str(result)[:400]}
    if "error" in result:
        return {"error": str(result["error"])[:400]}

    def _snip(text: str, n: int = 180) -> str:
        text = (text or "").strip().replace("\n", " ")
        return text if len(text) <= n else text[:n].rstrip() + "…"

    if tool_name == "search_notes":
        hits = result.get("results", [])[:8]
        return {"hits": [
            {
                "title": h.get("title", "?"),
                "folder_path": h.get("folder_path", ""),
                "snippet": _snip(h.get("snippet") or h.get("content", "")),
            }
            for h in hits
        ]}
    if tool_name == "read_note":
        body = result.get("content", "") or ""
        return {
            "title": result.get("title", "?"),
            "folder_path": result.get("folder_path", ""),
            "chars": len(body),
            "snippet": _snip(body, 320),
        }
    if tool_name == "list_folders":
        folders = result.get("folders", [])
        return {"folders": [f.get("path", str(f)) if isinstance(f, dict) else str(f) for f in folders[:30]], "total": len(folders)}
    if tool_name == "list_notes_in_folder":
        notes = result.get("notes", [])
        return {"notes": [n.get("title", "?") for n in notes[:20]], "total": len(notes)}
    if tool_name == "search_images":
        imgs = result.get("images", [])[:8]
        return {"images": [
            {"filename": i.get("filename", "?"), "snippet": _snip(i.get("description", ""))}
            for i in imgs
        ]}
    if tool_name in ("view_image", "view_document"):
        return {"filename": result.get("filename", "?"), "status": result.get("status", "")}
    if tool_name == "get_recent_notes":
        notes = result.get("notes", [])
        return {"notes": [n.get("title", "?") for n in notes[:15]], "total": len(notes)}
    if tool_name in ("create_note", "update_note", "rename_note", "move_note"):
        return {k: v for k, v in result.items() if k in ("title", "note_id", "folder_path", "new_title", "target_folder_path") and v}
    if tool_name in ("create_folder", "rename_folder", "delete_folder"):
        return {k: v for k, v in result.items() if k in ("folder_path", "new_name", "deleted") and v}
    if tool_name == "web_search":
        sources = result.get("sources", [])[:8]
        return {"sources": [{"title": s.get("title", s.get("url", "")), "url": s.get("url", "")} for s in sources]}
    if tool_name == "get_fitness_overview":
        return {k: v for k, v in result.items() if k in ("weight_count", "has_training_plan", "coaching_count") and v is not None}
    if tool_name == "get_workout_data":
        return {k: v for k, v in result.items() if k in ("mode", "count", "exercise_name") and v}
    if tool_name == "get_health_data":
        return {k: v for k, v in result.items() if k in ("mode", "date", "days") and v}
    if tool_name == "get_wardrobe":
        return {k: len(v) if isinstance(v, list) else v for k, v in result.items() if k in ("clothing", "watches", "fragrances", "accessories")}
    if tool_name == "get_wardrobe_analytics":
        return {k: v for k, v in result.items() if not isinstance(v, (list, dict)) or len(str(v)) < 200}
    if tool_name == "list_routines":
        routines = result.get("routines", result if isinstance(result, list) else [])
        return {
            "count": len(routines),
            "routines": [
                {"name": r.get("name", "?"), "id": r.get("id", "?"), "type": r.get("type", "")}
                for r in routines[:15]
            ],
        }
    if tool_name == "get_routine_summary":
        return {k: v for k, v in result.items() if k in (
            "routine_name", "days", "success_rate", "current_streak",
            "longest_streak", "total_done", "total_missed", "total_scheduled",
        ) and v is not None}
    if tool_name == "get_routine_entries":
        entries = result.get("entries", result if isinstance(result, list) else [])
        done = sum(1 for e in entries if (e.get("status") or "") == "done")
        return {"total_entries": len(entries), "done": done, "missed": len(entries) - done}

    # Fallback: a shallow dict with primitive values only
    out = {}
    for k, v in result.items():
        if k.startswith("_"):
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v if not isinstance(v, str) else _snip(v)
        elif isinstance(v, list):
            out[k] = f"[{len(v)} items]"
    return out


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
        # medium is the right level for the workspace agent: it handles file ops,
        # search, and multi-step reasoning but doesn't need full deep-think latency.
        thinking_config = types.ThinkingConfig(thinking_level="medium")
    except Exception:
        thinking_config = None

    config = types.GenerateContentConfig(
        system_instruction=AGENT_SYSTEM_INSTRUCTION,
        tools=_get_agent_tools(),
        temperature=0.8,
        max_output_tokens=8192,  # hard cap — prevents infinite generation loops
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        **({"thinking_config": thinking_config} if thinking_config else {}),
    )

    proposals = []
    steps = []
    # Citation registry: cite id → source entry (note / web / file). Filled as
    # tools surface sources, handed to the UI so [[cite:N]] markers resolve.
    citations: dict[str, dict] = {}
    citations_seen: dict[str, int] = {}
    # Aggregated token usage + cost across every model round (thinking, tool
    # rounds and the final answer) so the UI can show a single summary line.
    usage_agg = {"input": 0, "output": 0, "cost": 0.0}
    start_time = time.monotonic()

    def _accumulate_usage(um) -> None:
        if not um:
            return
        usage_agg["input"] += getattr(um, "prompt_token_count", 0) or 0
        usage_agg["output"] += getattr(um, "candidates_token_count", 0) or 0
        usage_agg["cost"] += getattr(um, "cost", 0.0) or 0.0

    # Kept intentionally low: each round is a full model call (thinking tokens
    # included). Without a tight cap the agent tends to fire many near-duplicate
    # searches instead of a couple of broad ones. See AGENT_SYSTEM_INSTRUCTION for
    # the matching "search broadly, don't repeat" guidance.
    max_tool_rounds = 5

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
            _accumulate_usage(getattr(response, "usage_metadata", None))

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
                            steps.append({"type": "thinking", "content": part.text, "round": round_num})
                            yield {"type": "thinking", "content": part.text, "round": round_num}
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
                                    steps.append({"type": "thinking", "content": part.text, "round": round_num})
                                    yield {"type": "thinking", "content": part.text, "round": round_num}
                                elif getattr(part, 'text', None) and not getattr(part, 'function_call', None):
                                    emitted_via_parts = True
                                    full_text_parts.append(part.text)
                                    yield {"type": "chunk", "content": part.text}

                # Capture token usage from the terminal usage chunk
                _accumulate_usage(getattr(chunk, "usage_metadata", None))

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

        # If we've exhausted rounds, force a final answer instead of silently
        # stopping (previously: `break` here meant zero text was ever streamed
        # if the model was still calling tools at the last round).
        if round_num >= max_tool_rounds:
            steps.append({"type": "tool_call", "content": "Fasse zusammen …", "round": round_num, "tool": "_summarize"})
            yield {"type": "tool_call", "content": "Fasse zusammen …", "status": "Fasst alles zusammen", "tool": "_summarize", "round": round_num}
            # Nudge the model to answer now, without offering more tools.
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=(
                    "Du hast das Recherche-Limit für diese Anfrage erreicht. "
                    "Antworte JETZT mit dem, was du bisher gefunden hast — nutze KEINE weiteren Tools."
                ))],
            ))
            final_config = types.GenerateContentConfig(
                system_instruction=AGENT_SYSTEM_INSTRUCTION,
                temperature=0.8,
                **({"thinking_config": thinking_config} if thinking_config else {}),
            )
            async for chunk in await client.aio.models.generate_content_stream(
                model=AGENT_MODEL, contents=contents, config=final_config,
            ):
                _accumulate_usage(getattr(chunk, "usage_metadata", None))
                if chunk.candidates:
                    for candidate in chunk.candidates:
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if getattr(part, 'thought', False) and getattr(part, 'text', None):
                                    steps.append({"type": "thinking", "content": part.text, "round": round_num})
                                    yield {"type": "thinking", "content": part.text, "round": round_num}
                                elif getattr(part, 'text', None):
                                    yield {"type": "chunk", "content": part.text}
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

            # Compact, chat-safe copy of the args for the UI timeline.
            display_args = {
                k: (v if (not isinstance(v, str) or len(v) <= 240) else v[:240] + "…")
                for k, v in tool_args.items()
                if not isinstance(v, (bytes, bytearray)) and not k.startswith("_")
            }

            yield {
                "type": "tool_call",
                "content": step_desc,
                "status": _status_phrase(tool_name),
                "tool": tool_name,
                "args": display_args,
                "round": round_num,
            }
            steps.append({
                "type": "tool_call",
                "content": step_desc,
                "tool": tool_name,
                "args": display_args,
                "round": round_num,
            })

            # Execute
            result = await _execute_tool(tool_name, tool_args, user_id, db)

            # Enrich step_desc for tools where the human-readable name is only
            # available after execution (read_note → title, view_image → filename).
            result_name = result.get("title") or result.get("filename") or ""
            if result_name and not detail:
                step_desc = f'{label}: „{result_name}"'
                # Also patch the already-pushed tool_call step so persisted AGENT_META is correct.
                if steps and steps[-1].get("type") == "tool_call" and steps[-1].get("tool") == tool_name:
                    steps[-1]["content"] = step_desc

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

            # Assign citation ids before the model sees the result, so it can
            # reference them with [[cite:N]] in its answer.
            _register_citations(tool_name, result, citations, citations_seen)

            # Summarize result for streaming UI
            result_summary = _summarize_tool_result(tool_name, result)
            result_details = _detail_from_tool_result(tool_name, result)
            yield {
                "type": "tool_result",
                "content": result_summary,
                "tool": tool_name,
                "details": result_details,
                "round": round_num,
            }
            steps.append({
                "type": "tool_result",
                "content": result_summary,
                "tool": tool_name,
                "details": result_details,
                "round": round_num,
            })

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

        # Add function responses to contents — Gemini API requires role="user" for function responses
        contents.append(types.Content(role="user", parts=function_response_parts))

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

    stats = {
        "input_tokens": usage_agg["input"],
        "output_tokens": usage_agg["output"],
        "total_tokens": usage_agg["input"] + usage_agg["output"],
        "cost": round(usage_agg["cost"], 6),
        "model": AGENT_MODEL,
        "duration_ms": int((time.monotonic() - start_time) * 1000),
    }
    yield {
        "type": "done",
        "proposals": proposals,
        "steps": steps,
        "stats": stats,
        "citations": citations,
    }


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
        return "Notiz erstellt"
    elif tool_name == "update_note":
        return "Notiz aktualisiert"
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
