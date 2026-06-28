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
