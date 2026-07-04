"""Quick connectivity check: do both candidate models actually respond?"""
import asyncio
from google.genai import types
from app.services.ai_service import get_client

MODELS = ["gemini-3.1-pro-preview", "gemini-3.5-flash"]


async def ping(model: str):
    client = get_client()
    try:
        r = await client.aio.models.generate_content(
            model=model,
            contents="Antworte nur mit dem Wort: OK",
            config=types.GenerateContentConfig(temperature=0),
        )
        um = getattr(r, "usage_metadata", None)
        return f"{model}: OK -> {repr((r.text or '').strip()[:40])} | usage={um}"
    except Exception as e:
        return f"{model}: FEHLER -> {type(e).__name__}: {e}"


async def main():
    for m in MODELS:
        print(await ping(m))


if __name__ == "__main__":
    asyncio.run(main())
