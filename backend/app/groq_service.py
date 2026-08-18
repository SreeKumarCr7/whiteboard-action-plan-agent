import os

from groq import Groq
from groq import GroqError


class GroqConfigError(Exception):
    """Raised when the Groq API key is missing or invalid."""


class GroqServiceError(Exception):
    """Raised when the Groq API call itself fails."""


_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Shared reliability guardrail injected into every Groq prompt. Non-negotiable:
# the model must never fabricate content, owners, or dates that aren't present.
_GUARDRAIL = (
    "You must never fabricate, invent, or guess at task owners, due dates, "
    "action items, or any content that is not clearly present in the source "
    "notes. When something is unclear or missing, leave it null or omit it "
    "rather than making it up. Fidelity to the source notes is the highest "
    "priority."
)

_CLEAN_SYSTEM = (
    "You are an OCR post-processing assistant. Split the raw OCR text into "
    "one fragment per physical line (one per bullet / sticky note). Do not "
    "merge or join lines together. It is fine if some fragments are "
    "incomplete or wrap oddly — a human will review them later.\n"
    "Rules:\n"
    "- Drop empty lines and unreadable gibberish rather than guessing.\n"
    "- Fix only very obvious single-character OCR errors you are highly "
    "confident about (e.g. '0wner' -> 'Owner').\n"
    "- De-duplicate exact or near-exact repeated lines.\n"
    "- Never invent, add, or merge content that is not in the raw text. "
    + _GUARDRAIL
)

_EXTRACT_SYSTEM = (
    "You are an action-plan extraction assistant. Look at each cleaned note "
    "and decide whether it represents an action item. For each action item "
    "return an object with:\n"
    "- text: the action itself, in plain language\n"
    "- owner: a person's name if clearly attached to this note, else null\n"
    "- due: a date or relative deadline if mentioned, else null\n"
    "- priority: 'high', 'medium', or 'low' if the tone/marking implies it, "
    "else null\n"
    "Task text must stick to the literal wording and terms from the source "
    "notes. Do not expand abbreviations or acronyms using outside general "
    "knowledge, even if you are confident what they stand for — e.g. if the "
    "notes say 'TKAM', the task text should say 'TKAM', not the expanded "
    "title. Clarifying unfamiliar terms is a separate research step's job, "
    "not yours.\n"
    "Separately, collect any unclear terms (tool names, company names, "
    "acronyms, product names) that would need a lookup to understand. Do not "
    "flag common English words or generic project terms. "
    + _GUARDRAIL
)


def _get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise GroqConfigError(
            "Groq API key is not configured. Set GROQ_API_KEY as an "
            "environment variable."
        )
    return Groq(api_key=api_key)


def _call_json(system_prompt, user_content):
    """Run a Groq call in JSON mode and return the parsed JSON object."""
    try:
        client = _get_groq_client()
        completion = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = completion.choices[0].message.content
        if not content:
            raise GroqServiceError("Groq returned an empty response.")
        return content
    except GroqConfigError:
        raise
    except GroqError as exc:
        raise GroqServiceError(f"Groq request failed: {exc}") from exc


def clean_notes(raw_text):
    """Break raw OCR text into cleaned, distinct note fragments."""
    if not raw_text or not raw_text.strip():
        return []
    raw = _call_json(
        _CLEAN_SYSTEM,
        "Return JSON only, shaped exactly as "
        '{"notes": ["fragment one", "fragment two", ...]}. '
        "Here is the raw OCR text:\n\n" + raw_text,
    )
    # Defensive parse: fall back to a plain list if the model returns one.
    import json

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GroqServiceError(
            "Groq returned invalid JSON for clean-notes."
        ) from exc
    if isinstance(data, list):
        notes = data
    elif isinstance(data, dict):
        notes = data.get("notes", [])
    else:
        notes = []
    if not isinstance(notes, list):
        notes = []
    fragments = [str(n).strip() for n in notes if str(n).strip()]
    return _dedupe_repeats(fragments)


def _dedupe_repeats(fragments):
    """Drop exact or near-exact repeated fragments, keeping first occurrence."""
    seen = []
    out = []
    for frag in fragments:
        key = frag.lower()
        if any(
            key == s
            or (abs(len(key) - len(s)) <= 1 and _levenshtein(key, s) <= 1)
            for s in seen
        ):
            continue
        seen.append(key)
        out.append(frag)
    return out


def _dedupe_terms(terms):
    """Collapse near-identical variants (case / single-char OCR misreads)."""
    seen = []
    for term in terms:
        t = str(term).strip()
        if not t:
            continue
        tl = t.lower()
        if any(
            tl == s
            or (abs(len(tl) - len(s)) <= 1 and _levenshtein(tl, s) <= 1)
            for s in seen
        ):
            continue
        seen.append(tl)
    return seen


def _levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(
                min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
            )
        prev = curr
    return prev[-1]


def extract_items(notes):
    """Extract candidate action items and flag unclear terms."""
    if not notes:
        return {"items": [], "unclear_terms": []}
    raw = _call_json(
        _EXTRACT_SYSTEM,
        'Return JSON only, shaped exactly as '
        '{"items": [{"text": "...", "owner": null, "due": null, '
        '"priority": null}], "unclear_terms": ["..."]}. '
        "Here are the cleaned notes:\n\n"
        + "\n".join(f"- {n}" for n in notes),
    )
    import json

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GroqServiceError(
            "Groq returned invalid JSON for extract-items."
        ) from exc
    if not isinstance(data, dict):
        data = {}
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []
    unclear_terms = data.get("unclear_terms", [])
    if not isinstance(unclear_terms, list):
        unclear_terms = []
    return {"items": items, "unclear_terms": _dedupe_terms(unclear_terms)}


_SYNTHESIZE_SYSTEM = (
    "You are an action-plan synthesis assistant. Given extracted action "
    "items and optional research context, produce a final structured plan.\n"
    "Rules:\n"
    "- Use research context only to add a short clarifying note to relevant "
    "tasks — never to invent new tasks.\n"
    "- Before using any research_context entry in the summary, judge whether "
    "it plausibly relates to the actual content and domain of the extracted "
    "notes. If the notes are clearly about one kind of document (e.g. "
    "handwritten personal or clinical notes, an outline, a list) and a "
    "research result describes something unrelated (e.g. social media posts, "
    "job ads, companies with no evident connection), do not incorporate it — "
    "treat that research entry as unreliable/irrelevant and omit it entirely, "
    "the same as a 'no reliable information found' result.\n"
    "- The summary must be grounded primarily in what the extracted items "
    "and cleaned notes actually say. Research context should only ever add a "
    "small clarifying detail to something already present in the notes — it "
    "must never become the primary source of the summary's content, and it "
    "must never introduce a topic, organization, or scenario that isn't "
    "otherwise evidenced by the notes themselves.\n"
    "- If there are zero action items AND the available research doesn't "
    "clearly relate to the note content either, give an honest summary such "
    "as 'This image doesn't appear to contain clear meeting or task-related "
    "content' rather than constructing a specific alternative story about "
    "what it might be.\n"
    "- If a term's research came back as 'No reliable information found', "
    "omit added context for that task rather than making something up.\n"
    "- If owner or due date is missing on an item, leave it blank and add a "
    "corresponding entry to open_questions instead of guessing.\n"
    "- Task titles must be short and verb-first.\n"
    "- Write a 2-3 sentence plain-language summary of what the notes are "
    "about.\n"
    "Never fabricate content, owners, dates, or tasks not grounded in the "
    "items or research. "
    + _GUARDRAIL
)


def synthesize_plan(items, research_context):
    """Produce the final structured plan from items + research context."""
    import json

    items_json = json.dumps(items or [], ensure_ascii=False)
    ctx_json = json.dumps(research_context or {}, ensure_ascii=False)
    raw = _call_json(
        _SYNTHESIZE_SYSTEM,
        'Return JSON only, shaped exactly as '
        '{"has_tasks": true, "tasks": [{"title": "...", "owner": "...", '
        '"due": "...", "priority": "...", "context": "..."}], '
        '"open_questions": ["..."], "summary": "..."}. '
        "If there are no action items, return has_tasks=false with an empty "
        "tasks array, still provide a summary describing what the image "
        "actually contained based on the notes and research context, and add "
        "relevant open_questions (e.g. whether the right photo was uploaded). "
        "Here are the extracted items:\n\n"
        + items_json
        + "\n\nResearch context:\n\n"
        + ctx_json,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GroqServiceError(
            "Groq returned invalid JSON for synthesize-plan."
        ) from exc
    if not isinstance(data, dict):
        data = {}
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        tasks = []
    open_questions = data.get("open_questions", [])
    if not isinstance(open_questions, list):
        open_questions = []
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        summary = ""
    has_tasks = bool(data.get("has_tasks", bool(tasks)))
    return {
        "has_tasks": has_tasks,
        "tasks": tasks,
        "open_questions": open_questions,
        "summary": summary,
    }
