# SPDX-License-Identifier: Apache-2.0
"""MCP server for quickpoll (fork of abstimmbar): rooms, question sets, import, results.

It calls the app's REST API with a bearer token from API_TOKENS (accounts/token_auth.py),
so it acts as that user and sees exactly that user's rooms. Streamable HTTP at /mcp,
guarded by MCP_TOKEN.

Env: QUICKPOLL_API (internal base URL, e.g. http://app:8000), QUICKPOLL_API_TOKEN,
PUBLIC_BASE_URL (for the links it returns), MCP_TOKEN.
"""
import hmac
import json
import os
from typing import Any

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

API = os.environ.get("QUICKPOLL_API", "http://app:8000").rstrip("/")
API_TOKEN = os.environ["QUICKPOLL_API_TOKEN"]
PUBLIC = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
MCP_TOKEN = os.environ["MCP_TOKEN"]

FORMAT_GUIDE = """\
A question set for import_set is a JSON object (export format "abstimmbar-set-v2"; get_set returns the same shape):

{"title": "...", "type": "live_poll" | "self_paced" | "self_check", "description": "...",
 "questions": [{"kind": "...", "text": "...", "options": [{"text": "...", "is_correct": true}], "time_limit": 60}]}

- type: live_poll = presenter-driven on the beamer (all kinds); self_paced = students work through it at their own
  pace in class; self_check = a standing practice link with instant feedback (single_choice, multiple_choice,
  ordering, open_text only).
- kind: single_choice, multiple_choice (options; mark right answers with is_correct), word_cloud, likert,
  open_text, priorities, ordering (options in the right order), mindmap (mindmap_root), matrix.
  Optionless kinds: word_cloud, likert, open_text, mindmap, matrix.
- Text fields take a plain string (stored in the instance's content language) or a {"de": ..., "en": ...} map.
  Question text may contain simple HTML (<p>, <strong>, <code>, lists); it is sanitized.
- Optional per question: time_limit (seconds), shuffle_options, reveal_answers, wordcloud_max_answers.
- Results (votes) are never part of a set; they come from get_results.
"""

mcp = FastMCP(
    "quickpoll",
    instructions=(
        "quickpoll: live polls, word clouds, Likert scales and quizzes for class (students join anonymously by "
        "QR code or room code). Rooms hold question sets; a set is presented from the web UI. Typical flow: "
        "list_rooms (or create_room), then import_set with a set built per format_guide, then give the user the "
        "present_url. get_set returns a set as importable JSON (edit it and import_set again for a variant); "
        "get_results returns the answers of past runs. Write the content in Hungarian unless asked otherwise."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _client() -> httpx.AsyncClient:
    # Host must be in DJANGO_ALLOWED_HOSTS; X-Forwarded-Proto keeps Django on its https code paths.
    return httpx.AsyncClient(base_url=API, timeout=60, headers={
        "Authorization": f"Bearer {API_TOKEN}", "Host": "localhost", "X-Forwarded-Proto": "https"})


async def _call(method: str, path: str, **kw) -> Any:
    async with _client() as c:
        r = await c.request(method, path, **kw)
    if r.status_code >= 400:
        raise ValueError(f"quickpoll API {method} {path} -> {r.status_code}: {r.text[:500]}")
    return r.json() if r.content else None


def _links(set_id: int, room_code: str | None = None) -> dict:
    out = {"edit_url": f"{PUBLIC}/sets/{set_id}", "present_url": f"{PUBLIC}/sets/{set_id}/present",
           "results_url": f"{PUBLIC}/sets/{set_id}/results"}
    if room_code:
        out["join_url"] = f"{PUBLIC}/p/{room_code}"
    return out


def _text(value) -> str:
    """A {de, en} map from the API as one string (whichever language is filled)."""
    if isinstance(value, dict):
        return next((v for v in (value.get("en"), value.get("de")) if v), "")
    return value or ""


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


async def _all(path: str, params: dict | None = None) -> list:
    items, page = [], 1
    while True:
        data = await _call("GET", path, params={**(params or {}), "page": page})
        items += data["results"]
        if not data.get("next"):
            return items
        page += 1


@mcp.tool()
async def format_guide() -> str:
    """How to write a question set for import_set: set types, question kinds, fields."""
    return FORMAT_GUIDE


@mcp.tool()
async def list_rooms() -> str:
    """The user's rooms: id, code (students join with it), title, number of question sets."""
    rooms = await _all("/api/rooms/")
    return _json([{"id": r["id"], "code": r["code"], "title": _text(r["title"]),
                   "sets": r.get("question_set_count"), "join_url": f"{PUBLIC}/p/{r['code']}"} for r in rooms])


@mcp.tool()
async def create_room(title: str, description: str = "") -> str:
    """Create a room (e.g. one per cohort or course). Returns its id and join code."""
    lang = (await _call("GET", "/api/whoami/"))["content_default_language"]
    r = await _call("POST", "/api/rooms/", json={"title": {lang: title}, "description": {lang: description}})
    return _json({"id": r["id"], "code": r["code"], "title": _text(r["title"]), "join_url": f"{PUBLIC}/p/{r['code']}"})


@mcp.tool()
async def list_sets(room_id: int | None = None, search: str | None = None) -> str:
    """Question sets, optionally of one room or matching a text search (titles, questions, answers)."""
    params = {k: v for k, v in (("room", room_id), ("search", search)) if v}
    sets = await _all("/api/question-sets/", params)
    return _json([{"id": s["id"], "room": s["room"], "room_title": _text(s.get("room_title")),
                   "title": _text(s["title"]), "type": s["type"], "questions": s.get("question_count"),
                   "has_results": s.get("has_results"), **_links(s["id"])} for s in sets])


@mcp.tool()
async def get_set(set_id: int) -> str:
    """One question set as importable JSON (the export format), plus its links."""
    data = await _call("GET", f"/api/question-sets/{set_id}/export/")
    return _json({"set": data, "links": _links(set_id)})


@mcp.tool()
async def import_set(room_id: int, question_set: dict) -> str:
    """Create a question set in a room from JSON (see format_guide). A title already used in the room gets a
    suffix. Returns the new set's id and its edit / present links."""
    data = {"format": "abstimmbar-set-v2", **question_set}
    s = await _call("POST", f"/api/rooms/{room_id}/import-set/", json=data)
    room = await _call("GET", f"/api/rooms/{room_id}/")
    return _json({"id": s["id"], "title": _text(s["title"]), "type": s["type"],
                  "questions": s.get("question_count"), **_links(s["id"], room["code"])})


@mcp.tool()
async def delete_set(set_id: int) -> str:
    """Delete a question set (with its results). Only when the user asks for it."""
    await _call("DELETE", f"/api/question-sets/{set_id}/")
    return _json({"deleted": set_id})


@mcp.tool()
async def get_results(set_id: int) -> str:
    """Answers of every run of a set (newest first), aggregated per question: vote counts per option, word-cloud
    terms, Likert distribution, free texts."""
    return _json(await _call("GET", f"/api/question-sets/{set_id}/results/"))


app = mcp.streamable_http_app()


async def guarded(scope, receive, send):
    """Bearer MCP_TOKEN on every HTTP request; lifespan passes through."""
    if scope["type"] == "http":
        auth = dict(scope["headers"]).get(b"authorization", b"").decode()
        if not hmac.compare_digest(auth, f"Bearer {MCP_TOKEN}"):
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
    await app(scope, receive, send)


if __name__ == "__main__":
    uvicorn.run(guarded, host="0.0.0.0", port=8000)
