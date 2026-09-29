"""Quick connectivity check for the configured OpenAI Sol and Luna models."""
import asyncio

from app.services.ai_service import FLASH_MODEL, PRO_MODEL, generate

MODELS = [PRO_MODEL, FLASH_MODEL]


async def ping(model: str) -> str:
    try:
        text = await generate("Antworte nur mit dem Wort: OK", model=model, temperature=0)
        return f"{model}: OK -> {text.strip()[:40]!r}"
    except Exception as exc:
        return f"{model}: FEHLER -> {type(exc).__name__}: {exc}"


async def main() -> None:
    for model in MODELS:
        print(await ping(model))


if __name__ == "__main__":
    asyncio.run(main())
