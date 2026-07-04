"""
Real A/B evaluation: gemini-3.1-pro-preview  vs  gemini-3.5-flash
as the "Infinite Teacher" model.

This is NOT a mock. It fires real Gemini calls with the SAME system instruction
and lesson context the live teacher uses, across a small sample course, and
measures for each model:
  - wall-clock latency per task
  - token usage (prompt / thoughts / output / total) from usage_metadata
  - estimated cost (rough public preview pricing — edit RATES below)
  - blind quality rating by a judge model (didactic quality, correctness,
    structure, "duzen"/tone), 1-10

Tasks exercised (the ones that actually matter for UX):
  1. teach_start   — explain the first lesson section (grounded, thinking)
  2. teach_next    — explain a follow-up section
  3. curriculum    — generate a structured curriculum (JSON)
  4. quiz          — generate a 3-question MC quiz (JSON)

Run:
  python3 eval_teacher_models.py
  python3 eval_teacher_models.py --repeat 2      # average over N runs
  python3 eval_teacher_models.py --no-judge      # skip quality judging
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field

from google.genai import types

from app.services.ai_service import get_client
from app.services.teacher_service import (
    FORMATTING_RULES, _build_sections_block, CURRICULUM_SCHEMA,
)

# ── Candidate models ──────────────────────────────────────────────────
MODEL_A = "gemini-3.1-pro-preview"   # current
MODEL_B = "gemini-3.5-flash"         # candidate: faster/cheaper/newer
JUDGE_MODEL = "gemini-3.1-pro-preview"

# ── Rough pricing ($ per 1M tokens). EDIT to match official pricing. ──
# Thought tokens are billed as output tokens on Gemini.
RATES = {
    "gemini-3.1-pro-preview": {"in": 1.25, "out": 10.00},
    "gemini-3.5-flash":       {"in": 0.30, "out": 2.50},
}


# ── Sample course ─────────────────────────────────────────────────────
SAMPLE_COURSE_TITLE = "Einführung in die Wahrscheinlichkeitsrechnung"

SAMPLE_LESSON = {
    "title": "Bedingte Wahrscheinlichkeit und der Satz von Bayes",
    "description": (
        "Wie sich Wahrscheinlichkeiten ändern, wenn Vorwissen vorliegt, und wie man "
        "mit dem Satz von Bayes von P(A|B) auf P(B|A) schließt."
    ),
    "objectives": [
        "Bedingte Wahrscheinlichkeit P(A|B) definieren und berechnen",
        "Den Satz von Bayes herleiten und anwenden",
        "Typische Anwendungsfälle (z.B. medizinische Tests) durchrechnen",
    ],
    "sections": [
        {"title": "Was bedeutet bedingte Wahrscheinlichkeit?",
         "focus": "Intuition + Definition P(A|B) = P(A∩B)/P(B) mit einem Alltagsbeispiel."},
        {"title": "Der Satz von Bayes",
         "focus": "Herleitung aus der Definition, Bedeutung von Prior/Posterior."},
        {"title": "Anwendung: medizinischer Test",
         "focus": "Ein durchgerechnetes Beispiel mit Basisrate, Sensitivität, Spezifität."},
    ],
}


def _teacher_system_instruction(year: int = 2026) -> str:
    return f"""Du bist ein exzellenter, warmherziger Universitätsprofessor und persönlicher Tutor ({year}).
Du DUZT den Studenten IMMER ("du/dein/dir", NIEMALS "Sie/Ihr/Ihnen").
Du unterrichtest abschnittsweise: behandle immer nur den aktuell markierten Abschnitt —
substantiell, mit Beispiel (2-4 Absätze), fokussiert auf dieses eine Teilkonzept.
Bei mathematischen Themen: LaTeX ($...$ inline, $$...$$ als Block).
{FORMATTING_RULES}
Antworte auf Deutsch."""


def _teach_context(current_section: int) -> str:
    objectives = "\n".join(f"  - {o}" for o in SAMPLE_LESSON["objectives"])
    subject = (
        f'KURS: "{SAMPLE_COURSE_TITLE}"\n'
        f'LEKTION: "{SAMPLE_LESSON["title"]}"\n{SAMPLE_LESSON["description"]}\n'
        f'LERNZIELE:\n{objectives}'
    )
    sblock = _build_sections_block(SAMPLE_LESSON["sections"], current_section)
    return f"{subject}\n\n{sblock}"


# ── Result records ────────────────────────────────────────────────────
@dataclass
class TaskResult:
    task: str
    model: str
    latency_s: float
    prompt_tokens: int
    thought_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    text: str = ""
    error: str | None = None
    quality: dict = field(default_factory=dict)


def _usage(resp) -> tuple[int, int, int, int]:
    um = getattr(resp, "usage_metadata", None)
    if not um:
        return 0, 0, 0, 0
    prompt = getattr(um, "prompt_token_count", 0) or 0
    thoughts = getattr(um, "thoughts_token_count", 0) or 0
    cand = getattr(um, "candidates_token_count", 0) or 0
    total = getattr(um, "total_token_count", 0) or (prompt + thoughts + cand)
    return prompt, thoughts, cand, total


def _cost(model: str, prompt_toks: int, thought_toks: int, out_toks: int) -> float:
    r = RATES.get(model)
    if not r:
        return 0.0
    billed_out = thought_toks + out_toks  # thoughts billed as output
    return (prompt_toks * r["in"] + billed_out * r["out"]) / 1_000_000


async def _run_call(model: str, task: str, *, system: str | None, contents,
                    grounded: bool, thinking: bool,
                    response_schema=None) -> TaskResult:
    client = get_client()
    cfg_kwargs = {}
    if system:
        cfg_kwargs["system_instruction"] = system
    tools = []
    if grounded:
        tools.append(types.Tool(google_search=types.GoogleSearch()))
    if tools:
        cfg_kwargs["tools"] = tools
    if thinking:
        try:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(include_thoughts=True)
        except Exception:
            pass
    if response_schema is not None:
        # structured output can't combine with search grounding
        cfg_kwargs["response_mime_type"] = "application/json"
        cfg_kwargs["response_schema"] = response_schema
    config = types.GenerateContentConfig(**cfg_kwargs)

    t0 = time.perf_counter()
    try:
        resp = await client.aio.models.generate_content(
            model=model, contents=contents, config=config,
        )
        dt = time.perf_counter() - t0
        p, th, o, tot = _usage(resp)
        return TaskResult(
            task=task, model=model, latency_s=dt,
            prompt_tokens=p, thought_tokens=th, output_tokens=o, total_tokens=tot,
            cost_usd=_cost(model, p, th, o),
            text=(resp.text or "").strip(),
        )
    except Exception as e:
        dt = time.perf_counter() - t0
        return TaskResult(
            task=task, model=model, latency_s=dt,
            prompt_tokens=0, thought_tokens=0, output_tokens=0, total_tokens=0,
            cost_usd=0.0, error=f"{type(e).__name__}: {e}",
        )


# ── Task definitions ──────────────────────────────────────────────────
async def task_teach_start(model: str) -> TaskResult:
    ctx = _teach_context(0)
    contents = f"{ctx}\n\nNACHRICHT DES STUDENTEN: [START]"
    return await _run_call(
        model, "teach_start", system=_teacher_system_instruction(),
        contents=contents, grounded=True, thinking=True,
    )


async def task_teach_next(model: str) -> TaskResult:
    ctx = _teach_context(1)
    contents = f"{ctx}\n\nNACHRICHT DES STUDENTEN: [ABSCHNITT_WEITER]"
    return await _run_call(
        model, "teach_next", system=_teacher_system_instruction(),
        contents=contents, grounded=True, thinking=True,
    )


async def task_curriculum(model: str) -> TaskResult:
    prompt = f"""Erstelle einen strukturierten Lehrplan für "{SAMPLE_COURSE_TITLE}".
Module (level 1) und Lektionen (level 2), unit_number als String ("1", "1.1", …),
je Lektion klare learning_objectives. Genau 2 Module mit insgesamt 6 Lektionen."""
    return await _run_call(
        model, "curriculum", system=None, contents=prompt,
        grounded=False, thinking=True, response_schema=CURRICULUM_SCHEMA,
    )


async def task_quiz(model: str) -> TaskResult:
    prompt = f"""Erstelle GENAU 3 Multiple-Choice-Fragen zum Thema
"{SAMPLE_LESSON['title']}" ({SAMPLE_LESSON['description']}).
Jede Frage: 4 Optionen, genau eine richtig. Antworte NUR als JSON:
{{"questions":[{{"question":"...","options":["A","B","C","D"],"correct_index":0,"explanation":"..."}}]}}"""
    return await _run_call(
        model, "quiz", system=None, contents=prompt,
        grounded=False, thinking=True,
    )


TASKS = {
    "teach_start": task_teach_start,
    "teach_next": task_teach_next,
    "curriculum": task_curriculum,
    "quiz": task_quiz,
}


# ── Quality judging (blind A/B) ───────────────────────────────────────
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "score_a": {"type": "integer"},
        "score_b": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["winner", "score_a", "score_b", "reason"],
}


async def judge_pair(task: str, text_a: str, text_b: str) -> dict:
    """Blind-judge two answers for the same task. Returns scores + winner + reason."""
    client = get_client()
    criteria = (
        "didaktische Qualität, fachliche Korrektheit, Struktur/Formatierung, "
        "passender Umfang für EINEN Abschnitt, konsequentes Duzen, guter Tutor-Ton"
    )
    prompt = f"""Du bist ein strenger Didaktik-Gutachter. Bewerte zwei Antworten (A und B)
auf DIESELBE Lehr-Aufgabe blind. Aufgabe: "{task}".
Kriterien: {criteria}.
Gib je eine Note 1-10 (score_a, score_b), den Gewinner (A/B/tie) und eine KURZE Begründung.

--- ANTWORT A ---
{text_a[:6000]}

--- ANTWORT B ---
{text_b[:6000]}"""
    try:
        resp = await client.aio.models.generate_content(
            model=JUDGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=JUDGE_SCHEMA,
            ),
        )
        parsed = getattr(resp, "parsed", None)
        if parsed:
            return parsed if isinstance(parsed, dict) else json.loads(resp.text)
        return json.loads((resp.text or "{}"))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ── Runner ────────────────────────────────────────────────────────────
def _fmt_row(r: TaskResult) -> str:
    if r.error:
        return f"    {r.model:<26} FEHLER: {r.error}"
    return (
        f"    {r.model:<26} {r.latency_s:6.2f}s | "
        f"in {r.prompt_tokens:>5} · think {r.thought_tokens:>5} · out {r.output_tokens:>5} · "
        f"tot {r.total_tokens:>6} | ${r.cost_usd:.5f}"
    )


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1, help="Runs per task (averaged)")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--tasks", default=",".join(TASKS), help="Comma-separated task subset")
    args = ap.parse_args()

    selected = [t.strip() for t in args.tasks.split(",") if t.strip() in TASKS]

    print("=" * 78)
    print(f"TEACHER MODEL EVAL — {MODEL_A}  vs  {MODEL_B}")
    print(f"Course: {SAMPLE_COURSE_TITLE}")
    print(f"Lesson: {SAMPLE_LESSON['title']}")
    print(f"Repeats per task: {args.repeat}")
    print("=" * 78)

    # Aggregates per model
    agg = {MODEL_A: {"lat": 0.0, "cost": 0.0, "tot": 0, "n": 0},
           MODEL_B: {"lat": 0.0, "cost": 0.0, "tot": 0, "n": 0}}
    quality_wins = {"A": 0, "B": 0, "tie": 0}
    last_texts: dict[str, dict[str, str]] = {}

    for task in selected:
        print(f"\n[{task}]")
        for model in (MODEL_A, MODEL_B):
            runs = [await TASKS[task](model) for _ in range(args.repeat)]
            ok = [r for r in runs if not r.error]
            if not ok:
                print(_fmt_row(runs[-1]))
                continue
            # average
            avg = TaskResult(
                task=task, model=model,
                latency_s=sum(r.latency_s for r in ok) / len(ok),
                prompt_tokens=round(sum(r.prompt_tokens for r in ok) / len(ok)),
                thought_tokens=round(sum(r.thought_tokens for r in ok) / len(ok)),
                output_tokens=round(sum(r.output_tokens for r in ok) / len(ok)),
                total_tokens=round(sum(r.total_tokens for r in ok) / len(ok)),
                cost_usd=sum(r.cost_usd for r in ok) / len(ok),
                text=ok[-1].text,
            )
            print(_fmt_row(avg))
            agg[model]["lat"] += avg.latency_s
            agg[model]["cost"] += avg.cost_usd
            agg[model]["tot"] += avg.total_tokens
            agg[model]["n"] += 1
            last_texts.setdefault(task, {})[model] = avg.text

        # Blind quality judging for text tasks
        if not args.no_judge and task in last_texts and len(last_texts[task]) == 2:
            verdict = await judge_pair(task, last_texts[task][MODEL_A], last_texts[task][MODEL_B])
            if "error" in verdict:
                print(f"    judge: {verdict['error']}")
            else:
                w = verdict.get("winner", "tie")
                quality_wins[w] = quality_wins.get(w, 0) + 1
                print(f"    judge: A={verdict.get('score_a')} B={verdict.get('score_b')} "
                      f"-> Gewinner {w} | {verdict.get('reason', '')[:150]}")

    # ── Summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("ZUSAMMENFASSUNG")
    print("=" * 78)
    for model in (MODEL_A, MODEL_B):
        a = agg[model]
        n = max(1, a["n"])
        print(f"  {model:<26} Ø {a['lat']/n:5.2f}s/Task | "
              f"Σ ${a['cost']:.5f} | Σ {a['tot']} tok über {a['n']} Tasks")

    if agg[MODEL_A]["cost"] > 0 and agg[MODEL_B]["cost"] > 0:
        speedup = agg[MODEL_A]["lat"] / max(agg[MODEL_B]["lat"], 1e-9)
        saving = 1 - agg[MODEL_B]["cost"] / agg[MODEL_A]["cost"]
        print(f"\n  {MODEL_B} ist ~{speedup:.1f}x schneller und ~{saving*100:.0f}% günstiger als {MODEL_A}")

    if not args.no_judge:
        print(f"\n  Qualität (blind gewertet): A({MODEL_A})={quality_wins['A']} · "
              f"B({MODEL_B})={quality_wins['B']} · unentschieden={quality_wins['tie']}")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
