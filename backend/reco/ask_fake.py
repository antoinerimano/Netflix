# reco/ask_fake.py
"""
A scripted stand-in for Claude in "Ask Taurus" (reco/ask.py), used when settings.AI_FAKE is on
(the end-to-end tests: they must never call the API). It behaves like the real loop: first a
find_titles call built from a few words of the message, then a JSON answer with the first 4 titles
the search returned, a fixed reply and 3 chips.
"""
import json
from types import SimpleNamespace as NS

WORDS = {  # word in the message -> mood (English + French, the e2e profiles' languages)
    "funny": "funny", "drôle": "funny", "comedy": "funny", "scary": "scary", "peur": "scary",
    "exciting": "exciting", "action": "exciting", "romantic": "romantic", "feel-good": "feelgood",
}
REPLY = "Here are a few ideas for tonight."
CHIPS = ["Shorter", "Something lighter", "A series instead"]
USAGE = NS(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0)


class _Messages:
    def create(self, **kwargs):
        messages = kwargs["messages"]
        last = messages[-1]["content"]
        if isinstance(last, str):  # the viewer's message: search first
            text = last.lower()
            moods = sorted({mood for word, mood in WORDS.items() if word in text})
            kind = "tv" if any(w in text for w in ("series", "show", "série")) else "any"
            call = NS(type="tool_use", id="toolu_fake", name="find_titles", input={
                "query": None, "like_title": None, "kind": kind, "moods": moods, "genres": [],
                "max_minutes": None, "year_from": None, "year_to": None,
            })
            return NS(stop_reason="tool_use", content=[call], usage=USAGE)
        found = json.loads(last[0]["content"]) if last and last[0].get("type") == "tool_result" else []
        answer = {"reply": REPLY, "title_ids": [t["id"] for t in found[:4]], "chips": CHIPS}
        return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(answer))], usage=USAGE)


class FakeClient:
    def __init__(self):
        self.messages = _Messages()
