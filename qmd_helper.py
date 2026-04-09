"""
qmd_helper.py — shared QMD search utility

Calls the QMD MCP HTTP server on localhost:8181 via JSON-RPC 2.0.
All functions return empty results on failure — never raise.

Search types:
  "lex"    → BM25 keyword search (~0.3s — use in daemon loops)
  "vec"    → semantic vector search (~4s — use for weekly/one-off)
  "expand" → lex+vec combined (~8s — good balance)

Default is "lex" for daemon safety.

Compatible with qmd >= 0.9.9 (single "query" tool with searches[] param).
"""

import json
import logging
import os
import re
import socket
import threading
import urllib.request
import urllib.error

QMD_HOST = os.environ.get("QMD_HOST", "localhost")
QMD_PORT = int(os.environ.get("QMD_PORT", "8181"))
QMD_MCP_URL = os.environ.get("QMD_MCP_URL", f"http://{QMD_HOST}:{QMD_PORT}/mcp")
QMD_PREFLIGHT_TIMEOUT_SECONDS = float(os.environ.get("QMD_PREFLIGHT_TIMEOUT_SECONDS", "0.35"))
QMD_TIMEOUTS_SECONDS = {
    "lex": float(os.environ.get("QMD_TIMEOUT_LEX_SECONDS", "12")),
    "vec": float(os.environ.get("QMD_TIMEOUT_VEC_SECONDS", "20")),
    "expand": float(os.environ.get("QMD_TIMEOUT_EXPAND_SECONDS", "30")),
}
logger = logging.getLogger("qmd_helper")

# MCP session cache — one session ID per process (thread-safe)
# None = not tried; empty string "" = init failed (skip retries); str = active session
_session_lock = threading.Lock()
_session_id: str | None = None


def _clean_snippet(raw: str) -> str:
    """Strip @@ diff header from QMD snippet output and trim."""
    cleaned = re.sub(r"^@@.*?@@[^\n]*\n+", "", raw, flags=re.DOTALL).strip()
    return cleaned[:200]


def _qmd_timeout_for(search_type: str) -> float:
    return QMD_TIMEOUTS_SECONDS.get(search_type, QMD_TIMEOUTS_SECONDS["lex"])


def _qmd_daemon_reachable() -> bool:
    """Fast preflight so callers degrade immediately if localhost:8181 is down."""
    try:
        with socket.create_connection((QMD_HOST, QMD_PORT), timeout=QMD_PREFLIGHT_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def _get_session_id(timeout: float = 3.0) -> str | None:
    """Return a cached MCP session ID, initializing one if needed.

    Returns None if init fails. Caches "" (empty string) on failure so subsequent
    calls skip the retry HTTP request — prevents hammering a dead endpoint.
    """
    global _session_id
    with _session_lock:
        if _session_id is not None:
            # "" = previously failed; str = active session
            return _session_id if _session_id else None
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "qmd_helper", "version": "1.0"},
            },
        }).encode()
        req = urllib.request.Request(
            QMD_MCP_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    _session_id = sid
                    return _session_id
        except Exception as e:
            logger.debug("QMD session init failed: %s", e)
        _session_id = ""  # cache failure — skip future retries this process lifetime
        return None


def _mcp_call(tool_name: str, arguments: dict, timeout: float) -> list | None:
    """Call a QMD MCP tool via JSON-RPC 2.0 over HTTP.

    Returns the parsed JSON from the first text content block, or None on error.
    """
    sid = _get_session_id()
    if not sid:
        logger.debug("QMD: no session ID — daemon not reachable or init failed")
        return None

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }).encode()
    req = urllib.request.Request(
        QMD_MCP_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "mcp-session-id": sid,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    # JSON-RPC error — spec-compliant: error key present and non-null
    if body.get("error") is not None:
        logger.debug("MCP error: %s", body["error"])
        return None
    # MCP tools/call result → content[]
    content = body.get("result", {}).get("content", [])
    for block in content:
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except json.JSONDecodeError as e:
                logger.debug("MCP text block not valid JSON: %s", e)
                return None
    return None


def qmd_query(
    query: str,
    collection: str,
    n: int = 2,
    search_type: str = "lex",
    max_chars: int = 200,
    *,
    intent: str | None = None,
) -> list[dict]:
    """
    Run a QMD search via MCP HTTP. Returns list of dicts:
      [{date: str, file: str, score: float, snippet: str}]
    Returns [] on any failure — never raises.

    Parameters
    ----------
    intent : str, optional
        Intent hint for expand queries (search_type="expand").
    """
    # qmd >= 0.9.9: single "query" tool with searches[] param
    # "lex" → BM25 keyword, "vec" → semantic vector, "expand" → lex+vec combined
    qmd_type = "lex" if search_type in ("lex", "expand") else "vec"
    timeout_seconds = _qmd_timeout_for(search_type)

    try:
        if not _qmd_daemon_reachable():
            logger.warning("qmd daemon unreachable at %s:%s — returning empty results", QMD_HOST, QMD_PORT)
            return []

        searches = [{"type": qmd_type, "query": query}]
        # "expand" mode: combine lex + vec for better recall
        if search_type == "expand":
            searches = [{"type": "lex", "query": query}, {"type": "vec", "query": query}]

        arguments: dict = {
            "searches": searches,
            "collections": [collection],
            "limit": n,
        }
        if intent:
            arguments["intent"] = intent

        data = _mcp_call("query", arguments, timeout_seconds)
        if not isinstance(data, list):
            logger.debug("qmd query: unexpected response type for: %s", query[:60])
            return []

        out = []
        for item in data:
            fp = item.get("file", "")
            dm = re.search(r"(\d{4}-\d{2}-\d{2})", fp)
            out.append({
                "date": dm.group(1) if dm else "",
                "file": fp,
                "score": item.get("score", 0),
                "snippet": _clean_snippet(item.get("snippet", ""))[:max_chars],
            })
        return out

    except (urllib.error.URLError, OSError, TimeoutError) as e:
        logger.warning("qmd query timed out for: %s (%s)", query[:60], e)
        return []
    except Exception as e:
        logger.warning("qmd_query failed: %s", e)
        return []


def qmd_context(
    keyword: str,
    collections: list[str] | str = "diarium",
    query_type: str = "lex",
    top_n: int = 3,
    max_chars: int = 200,
    label: str = "CONTEXT",
) -> str:
    """One-call convenience: keyword → formatted context string.

    Searches one or more collections, merges by score, returns a compact
    formatted block ready to inject into a prompt or event notes.
    Returns '' on any failure or if QMD is unreachable — never raises.

    Parameters
    ----------
    keyword     : Search query (natural language or keywords)
    collections : Collection name(s) — string or list of strings
    query_type  : 'lex' (fast, BM25), 'vec' (semantic), 'expand' (deep rerank)
                  Note: use MCP mcp__qmd__query directly for 'hyde' in skill files
    top_n       : Max results to include
    max_chars   : Max chars per snippet
    label       : Header label for the formatted block
    """
    try:
        if isinstance(collections, str):
            collections = [collections]

        all_results: list[dict] = []
        for col in collections:
            hits = qmd_query(keyword, collection=col, n=top_n, search_type=query_type, max_chars=max_chars)
            all_results.extend(hits)

        if not all_results:
            return ""

        # Deduplicate by file, keep highest score, sort descending
        seen: dict[str, dict] = {}
        for r in all_results:
            fp = r.get("file", "")
            if fp not in seen or r.get("score", 0) > seen[fp].get("score", 0):
                seen[fp] = r
        merged = sorted(seen.values(), key=lambda x: x.get("score", 0), reverse=True)[:top_n]

        return format_echo_for_prompt(merged, label)
    except Exception:
        return ""


def parse_film_snippet(snippet: str, desc_max: int = 100) -> dict:
    """
    Parse a film markdown snippet from QMD search results.

    Returns dict with keys: title, year, genres, desc (empty strings if not found).
    """
    title = ""
    year = ""
    genres = ""
    desc = ""
    for raw_line in snippet.split("\n"):
        s = raw_line.strip()
        if s.startswith("# "):
            title = s[2:].strip()
        elif s.startswith("- Year:"):
            year = s[7:].strip()
        elif s.startswith("- Genres:"):
            genres = s[9:].strip()
        elif not s.startswith("- ") and not s.startswith("#") and len(s) > 20:
            desc = s[:desc_max]
    return {"title": title, "year": year, "genres": genres, "desc": desc}


def format_film_line(film: dict) -> str:
    """Format a parsed film dict as a compact line: Title — Genres — Description."""
    parts = []
    if film.get("title"):
        parts.append(film["title"])
    if film.get("genres"):
        parts.append(film["genres"])
    if film.get("desc"):
        parts.append(film["desc"])
    return " — ".join(parts) if parts else ""


_FILM_STOPWORDS = frozenset(
    "this that with from been have were also just really things about people think "
    "every would could should there their being which some what when into more "
    "always might other where after before still".split()
)


def query_films_by_mood(
    texts: list[str],
    *,
    n: int = 5,
    min_word_len: int = 4,
    desc_max: int = 100,
    fallback_query: str = "drama comfort",
) -> list[str]:
    """Extract mood keywords from texts, search QMD films collection, return formatted lines.

    Returns list of ``"- Title — Genres — Desc"`` strings, or empty list on failure.
    """
    try:
        words = []
        for text in texts:
            for raw_word in text.lower().split():
                word = re.sub(r"[^\w]", "", raw_word)
                if len(word) >= min_word_len and word not in _FILM_STOPWORDS:
                    words.append(word)
        query = " ".join(words[:8]) if words else fallback_query

        hits = qmd_query(query, collection="films", n=n, search_type="vec")
        if not hits:
            return []

        lines = []
        for h in hits[:n]:
            film = parse_film_snippet(h.get("snippet", ""), desc_max=desc_max)
            line = format_film_line(film)
            if line:
                lines.append(f"- {line}")
        return lines
    except Exception:
        return []


def format_echo_for_prompt(
    results: list[dict],
    label: str = "HISTORICAL PARALLEL",
) -> str:
    """
    Format QMD results as a compact prompt block.
    Returns '' if no results. ~200-400 chars total.
    """
    if not results:
        return ""
    lines = [f"{label}:"]
    for r in results[:2]:
        if r.get("date") and r.get("snippet"):
            lines.append(f"- {r['date']}: {r['snippet'][:180]}")
    return "\n".join(lines)
