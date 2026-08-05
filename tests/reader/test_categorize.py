import json
from types import SimpleNamespace
from typing import Any

from nanonerd.reader.categorize import assign_categories


def create_fake_client(raw_reply, calls):
    def create(**kwargs):
        calls.append(kwargs)
        block = SimpleNamespace(type="text", text=raw_reply)
        return SimpleNamespace(content=[block])

    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_assign_categories_parses_reply_and_prompts_with_existing():
    calls: list[Any] = []
    client = create_fake_client(json.dumps(["Transit", "Zoning", "Housing"]), calls)

    output = assign_categories(
        "A Title", "Body text about transit.", ["Zoning"], client=client
    )

    assert output == ["Transit", "Zoning", "Housing"]
    prompt = calls[0]["messages"][0]["content"]
    assert "Zoning" in prompt and "A Title" in prompt
    assert calls[0]["model"] == "claude-haiku-4-5"


def test_assign_categories_strips_code_fences_and_caps_at_five():
    calls: list[Any] = []
    reply = '```json\n["A", "B", "C", "D", "E", "F"]\n```'
    client = create_fake_client(reply, calls)

    output = assign_categories("T", "B", [], client=client)

    assert output == ["A", "B", "C", "D", "E"]
