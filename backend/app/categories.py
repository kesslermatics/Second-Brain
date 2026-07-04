"""Canonical content categories for courses and books.

The AI assigns exactly ONE of these (German) categories per course/book, so the
UI can group and colour-code them consistently. Keep this list in sync with the
frontend category map (frontend/src/lib/categories.ts).
"""

# Ordered canonical list — the AI must pick one of these exact strings.
CATEGORIES: list[str] = [
    "Produktivität",
    "Persönliche Finanzen",
    "Business & Unternehmertum",
    "Selbstentwicklung",
    "Kritisches Denken",
    "Beziehungen",
    "Menschliches Verhalten",
    "Philosophie",
    "Disziplin & Gewohnheiten",
    "Kommunikation",
    "Psychologie",
    "Führung",
    "Gesundheit & Fitness",
    "Achtsamkeit & Spiritualität",
    "Kreativität",
    "Lernen & Gedächtnis",
    "Wissenschaft & Technik",
    "Geschichte",
    "Wirtschaft & Gesellschaft",
    "Marketing & Verkauf",
    "Sonstiges",
]

DEFAULT_CATEGORY = "Sonstiges"


def normalize_category(value: str | None) -> str:
    """Map an AI-provided category to the closest canonical value.

    Falls back to DEFAULT_CATEGORY when the value is missing or unknown, so the
    stored category is always one of CATEGORIES.
    """
    if not value:
        return DEFAULT_CATEGORY
    v = value.strip()
    # Exact match
    for c in CATEGORIES:
        if v.lower() == c.lower():
            return c
    # Loose contains match (handles e.g. "Business" -> "Business & Unternehmertum")
    for c in CATEGORIES:
        head = c.split(" & ")[0].strip().lower()
        if v.lower() == head or head in v.lower() or v.lower() in c.lower():
            return c
    return DEFAULT_CATEGORY


def categories_prompt_block() -> str:
    """Render the category list for inclusion in an LLM prompt."""
    joined = ", ".join(f'"{c}"' for c in CATEGORIES)
    return (
        "Wähle GENAU EINE Kategorie aus dieser festen Liste (exakt so geschrieben):\n"
        f"{joined}\n"
        'Wenn nichts eindeutig passt, wähle "Sonstiges".'
    )
