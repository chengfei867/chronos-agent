"""Side-effect classification heuristic (PH3-02 / R44-A).

Given a node's ``NodeKind`` and its ``node_name``, guess which
side-effect classes the node touches. Tags are written into
``node.metadata['effects']`` by the adapter.

This is a **heuristic**, not a proof. It exists to power UX hints
(the Web UI ForkPlan warning badge; downstream analysis scripts),
not to enforce isolation. ADR-019 "Chronos does not sandbox"
remains the governing decision — if a user wants *guaranteed*
isolation they implement one of the patterns in
``docs/guides/side-effects.md``.

Tag taxonomy (kept deliberately small — extending means all
downstream consumers need to learn new tags):

- ``"llm"``    — calls an LLM provider (OpenAI, Anthropic, local, etc.)
- ``"network"`` — calls an HTTP/gRPC/websocket endpoint that isn't an LLM
- ``"fs"``     — reads or writes files on the host filesystem
- ``"db"``     — reads or writes a database or data store
- ``"external"`` — known side-effect but not in the above four
  (escape valve; avoid if possible)

Classification signals (in priority order):

1. ``NodeKind.LLM`` + non-null ``model_name``  → ``["llm"]`` with high
   confidence. This is the one signal we trust fully because the
   adapter already has it via the usage extractor.
2. Explicit user override via ``effects_map`` argument to the
   adapter  → whatever the user said, verbatim. Always wins.
3. ``NodeKind.TOOL`` + ``node_name`` keyword match  → heuristic tag
   list. Keywords derived from surveying the top 20 LangGraph tool
   node names in public repos (Oct 2025 sample).
4. ``NodeKind.FN`` / ``ROUTER`` / ``FORK`` / ``END``  → empty list.
   Pure-function / control-flow nodes are assumed effect-free unless
   the user says otherwise via ``effects_map``.

The heuristic is intentionally conservative: false negatives (a real
side effect missed) are worse UX than false positives (warning on a
safe node). So we only tag when the node-name keyword is
unambiguous — e.g. ``call_weather_api`` gets ``["network"]`` but
``run_node`` gets ``[]``.
"""

from __future__ import annotations

import re

from chronos.core.models import NodeKind

# ---------------------------------------------------------------------------
# Keyword tables (ordered: most-specific first so "http_db_sync" picks db).
# Each entry is a pair (tag, regex). Regexes compiled case-insensitively.
# Public so tests and downstream consumers can introspect/override.
# ---------------------------------------------------------------------------

NETWORK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(http|https|api|rest|webhook|graphql|grpc|soap)(_\w+)?\b",
        r"\bcall_\w+_api\b",
        r"\bfetch_\w+\b",
        r"\brequest_\w+\b",
        r"\bsend_\w*(email|sms|slack|discord|webhook|notification|message)\w*\b",
        r"\bpost_to_\w+\b",
        r"\b(search|crawl|scrape)_web\b",
    )
]

FS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(read|write|append|save|load)_file\b",
        r"\b(read|write)_json\b",
        r"\bsave_json\b",
        r"\bdownload_\w+\b",
        r"\bupload_\w+\b",
    )
]

DB_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(insert|update|delete|query|select)_\w*\b",
        r"\w*(read|write)_db\b",
        r"\b(save|load)_to_db\b",
        r"\b(sqlite|postgres|mysql|mongo|redis|chroma|pinecone|weaviate)(_\w+)?\b",
        r"\bvector_?(store|search|upsert)\b",
    )
]

EXTERNAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bexecute_\w+\b",
        r"\brun_\w*(script|command|shell|subprocess)\w*\b",
        r"\bdeploy_\w+\b",
        r"\bpublish_\w+\b",
    )
]

# Ordered: first match wins a tag. A node can collect multiple tags
# if multiple pattern groups fire.
_TAG_GROUPS: list[tuple[str, list[re.Pattern[str]]]] = [
    ("network", NETWORK_PATTERNS),
    ("fs", FS_PATTERNS),
    ("db", DB_PATTERNS),
    ("external", EXTERNAL_PATTERNS),
]


def classify_effects(
    *,
    node_name: str,
    kind: NodeKind,
    model_name: str | None = None,
    override: list[str] | None = None,
) -> list[str]:
    """Return an effect-tag list for the given node.

    Args:
        node_name: semantic name from the framework (e.g. ``"call_api"``).
        kind: the :class:`NodeKind` assigned by the adapter.
        model_name: populated for LLM nodes; drives the ``"llm"`` tag.
        override: if given (from ``effects_map``), returned verbatim.
            Use an empty list to explicitly mark a node effect-free.

    Returns:
        A list of unique effect tags, ordered by the taxonomy above
        (``llm`` / ``network`` / ``fs`` / ``db`` / ``external``).
    """
    if override is not None:
        # User-asserted tags win absolutely. We *copy* to protect the
        # caller's override dict from downstream mutation.
        return list(override)

    tags: list[str] = []

    # Signal 1: high-confidence LLM detection.
    if kind == NodeKind.LLM and model_name:
        tags.append("llm")

    # Signal 2: name-keyword heuristic. Only considered for TOOL nodes —
    # plain FN / ROUTER / FORK / END are assumed pure unless the user
    # says otherwise via `override`.
    if kind == NodeKind.TOOL:
        for tag, patterns in _TAG_GROUPS:
            if any(p.search(node_name) for p in patterns) and tag not in tags:
                tags.append(tag)

    return tags


# ---------------------------------------------------------------------------
# UI-side helpers (also import-safe for the FastAPI response models).
# ---------------------------------------------------------------------------


DANGEROUS_EFFECTS_DEFAULT: frozenset[str] = frozenset({"network", "fs", "db", "external"})
"""The set of effect tags that the Web UI flags by default on a ForkPlan.

``llm`` is intentionally NOT dangerous by default — an LLM call on a
replayed fork is the *point* of forking (you want the new prompt to
re-run). Teams that bill-sensitive LLM calls can extend this set via
frontend settings.
"""


def count_dangerous_downstream(
    *,
    downstream_effects: list[list[str]],
    dangerous: frozenset[str] = DANGEROUS_EFFECTS_DEFAULT,
) -> int:
    """Count nodes whose effect tags intersect the dangerous set.

    ``downstream_effects`` is a list-of-lists — one inner list per node
    downstream of the fork point (caller resolves what "downstream"
    means; typically via the existing DAG walker).
    """
    return sum(1 for tags in downstream_effects if any(t in dangerous for t in tags))
