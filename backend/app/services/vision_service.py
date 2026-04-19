"""
Gemini Vision service — interprets images and generates text descriptions for RAG.
"""
import asyncio
import google.generativeai as genai
from pathlib import Path
from app.config import get_settings

settings = get_settings()
_genai_configured = False


def _ensure_genai():
    global _genai_configured
    if not _genai_configured:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _genai_configured = True


VISION_MODEL = "gemini-3-flash-preview"

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

    # Upload the file to Gemini
    _ensure_genai()
    uploaded = genai.upload_file(path)

    model = genai.GenerativeModel(VISION_MODEL)
    prompt = custom_prompt or DESCRIBE_PROMPT

    response = await asyncio.to_thread(model.generate_content, [prompt, uploaded])

    # Clean up the uploaded file
    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass  # non-critical

    return response.text.strip()


async def describe_image_from_bytes(
    image_bytes: bytes,
    content_type: str,
    custom_prompt: str | None = None,
) -> str:
    """
    Describe an image from raw bytes (useful for inline / pasted images).
    """
    _ensure_genai()
    model = genai.GenerativeModel(VISION_MODEL)
    prompt = custom_prompt or DESCRIBE_PROMPT

    image_part = {
        "mime_type": content_type,
        "data": image_bytes,
    }

    response = await asyncio.to_thread(model.generate_content, [prompt, image_part])
    return response.text.strip()
