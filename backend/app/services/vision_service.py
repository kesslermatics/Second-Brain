"""
Gemini Vision service — interprets images and generates text descriptions for RAG.
Uses the new google-genai SDK.
"""
import asyncio
from pathlib import Path
from google.genai import types
from app.services.ai_service import get_client, FLASH_MODEL

VISION_MODEL = FLASH_MODEL

DESCRIBE_PROMPT = """Analysiere dieses Bild detailliert und beschreibe es auf Deutsch.

Beschreibe:
1. **Was ist zu sehen?** — Hauptmotiv, Objekte, Personen, Szenen
2. **Text im Bild** — Lies jeden sichtbaren Text vollständig ab (OCR)
3. **Diagramme / Grafiken** — Beschreibe Achsen, Datenpunkte, Trends, Beschriftungen
4. **Kontext** — Was könnte der Zweck oder die Bedeutung dieses Bildes sein?

Schreibe eine strukturierte, informative Beschreibung in 3-10 Sätzen.
Wenn das Bild Text enthält, gib diesen VOLLSTÄNDIG wieder.
Wenn es ein Diagramm oder eine Grafik ist, beschreibe alle Daten und Zusammenhänge."""


async def describe_image(file_path: str, custom_prompt: str | None = None) -> str:
    """
    Send an image to Gemini Vision and get a detailed text description.

    Args:
        file_path: Absolute or relative path to the image file on disk.
        custom_prompt: Optional custom prompt to override the default.

    Returns:
        AI-generated text description of the image.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {file_path}")

    client = get_client()
    prompt = custom_prompt or DESCRIBE_PROMPT

    # Read file and determine mime type
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
    mime_type = mime_map.get(path.suffix.lower(), "image/png")
    image_bytes = path.read_bytes()

    response = await client.aio.models.generate_content(
        model=VISION_MODEL,
        contents=[
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
    )
    return response.text.strip()


async def describe_image_from_bytes(
    image_bytes: bytes,
    content_type: str,
    custom_prompt: str | None = None,
) -> str:
    """
    Describe an image from raw bytes (useful for inline / pasted images).
    """
    client = get_client()
    prompt = custom_prompt or DESCRIBE_PROMPT

    response = await client.aio.models.generate_content(
        model=VISION_MODEL,
        contents=[
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type=content_type),
        ],
    )
    return response.text.strip()


# ── Document analysis (PDF, DOCX, etc.) ───────────────────────────────

DOCUMENT_PROMPT = """Analysiere dieses Dokument detailliert und erstelle eine strukturierte Zusammenfassung auf Deutsch.

Beschreibe:
1. **Worum geht es?** — Thema, Zweck und Hauptaussagen des Dokuments
2. **Kernpunkte** — Die wichtigsten Informationen, Argumente oder Daten
3. **Struktur** — Wie ist das Dokument aufgebaut (Kapitel, Abschnitte, etc.)
4. **Wichtige Details** — Zahlen, Daten, Namen, Definitionen die relevant sind

Schreibe eine informative Zusammenfassung in 5-15 Sätzen.
Gib auch an, wie viele Seiten/Abschnitte das Dokument ungefähr hat."""


async def analyze_document(file_bytes: bytes, content_type: str, filename: str, custom_prompt: str | None = None) -> str:
    """
    Analyze a document (PDF, DOCX, etc.) using Gemini's document understanding.

    Args:
        file_bytes: Raw bytes of the document.
        content_type: MIME type of the document.
        filename: Original filename for context.
        custom_prompt: Optional custom prompt.

    Returns:
        AI-generated text summary/analysis of the document.
    """
    client = get_client()
    prompt = custom_prompt or DOCUMENT_PROMPT

    # For text files, just include the text directly
    if content_type in ("text/plain", "text/markdown", "text/csv"):
        try:
            text_content = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text_content = file_bytes.decode("latin-1")

        response = await client.aio.models.generate_content(
            model=VISION_MODEL,
            contents=[
                f"{prompt}\n\nDateiname: {filename}\n\nInhalt:\n{text_content[:50000]}",
            ],
        )
        return response.text.strip()

    # For PDFs and Office docs, use Gemini's native document processing
    response = await client.aio.models.generate_content(
        model=VISION_MODEL,
        contents=[
            prompt + f"\n\nDateiname: {filename}",
            types.Part.from_bytes(data=file_bytes, mime_type=content_type),
        ],
    )
    return response.text.strip()
