import json

from anthropic import Anthropic

MODEL = "claude-haiku-4-5"
MAX_CATEGORIES = 5
_PROMPT_TEMPLATE = """You are categorizing an article saved to a personal \
read-later app.

Article title: {title}

Article text (may be truncated):
{text}

Existing categories in the app (reuse these names when they fit, so the \
taxonomy stays consistent): {existing}

Assign 3 to 5 short topical category names for this article. Prefer reusing \
existing category names; invent a new name only when nothing existing fits.

Respond with ONLY a JSON array of category name strings, nothing else."""


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def assign_categories(
    title: str,
    text: str,
    existing: list[str],
    client: Anthropic | None = None,
) -> list[str]:
    if client is None:
        client = Anthropic()
    prompt = _PROMPT_TEMPLATE.format(
        title=title,
        text=text[:4000],
        existing=", ".join(existing) if existing else "(none yet)",
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    parsed = json.loads(_strip_code_fences(raw))
    if not isinstance(parsed, list):
        raise ValueError(f"expected JSON array of categories, got: {raw!r}")
    names = [str(name).strip() for name in parsed if str(name).strip()]
    return names[:MAX_CATEGORIES]
