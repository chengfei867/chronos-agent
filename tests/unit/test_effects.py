"""Unit tests for ``chronos.adapters.effects`` (PH3-02 / R44-A).

Coverage targets:

- ``classify_effects``: each signal path (LLM auto-tag, TOOL keyword
  branches, override precedence, empty-list for pure nodes).
- ``count_dangerous_downstream``: default taxonomy behavior + custom
  dangerous sets.
- Pattern robustness: the regex tables resist common false positives
  (``run`` the noun vs ``run_command`` the verb).
"""

from __future__ import annotations

import pytest

from chronos.adapters.effects import (
    DANGEROUS_EFFECTS_DEFAULT,
    classify_effects,
    count_dangerous_downstream,
)
from chronos.core.models import NodeKind

# ---------------------------------------------------------------------------
# Signal 1: LLM auto-tagging
# ---------------------------------------------------------------------------


class TestLLMSignal:
    def test_llm_kind_with_model_name_gets_llm_tag(self) -> None:
        assert classify_effects(node_name="agent", kind=NodeKind.LLM, model_name="gpt-4o-mini") == [
            "llm"
        ]

    def test_llm_kind_without_model_name_gets_no_tag(self) -> None:
        # Defensive: LLM kind but no model_name means the usage
        # extractor didn't see a real call — don't claim LLM effect.
        assert classify_effects(node_name="agent", kind=NodeKind.LLM, model_name=None) == []

    def test_non_llm_kind_with_model_name_ignores_model(self) -> None:
        # A FN with a model_name leak shouldn't tag as LLM.
        assert classify_effects(node_name="helper", kind=NodeKind.FN, model_name="gpt-4") == []


# ---------------------------------------------------------------------------
# Signal 3: TOOL keyword heuristic
# ---------------------------------------------------------------------------


class TestToolKeywordHeuristic:
    @pytest.mark.parametrize(
        "node_name",
        [
            "call_weather_api",
            "fetch_user_profile",
            "request_stripe_charge",
            "send_email",
            "send_slack_notification",
            "http_get",
            "search_web",
            "post_to_webhook",
        ],
    )
    def test_network_keywords(self, node_name: str) -> None:
        tags = classify_effects(node_name=node_name, kind=NodeKind.TOOL)
        assert "network" in tags

    @pytest.mark.parametrize(
        "node_name",
        [
            "read_file",
            "write_file",
            "save_json",
            "load_file",
            "append_file",
            "download_report",
            "upload_artifact",
        ],
    )
    def test_fs_keywords(self, node_name: str) -> None:
        tags = classify_effects(node_name=node_name, kind=NodeKind.TOOL)
        assert "fs" in tags

    @pytest.mark.parametrize(
        "node_name",
        [
            "query_postgres",
            "insert_record",
            "update_order_status",
            "read_db",
            "vector_upsert",
            "save_to_db",
            "redis_set",
        ],
    )
    def test_db_keywords(self, node_name: str) -> None:
        tags = classify_effects(node_name=node_name, kind=NodeKind.TOOL)
        assert "db" in tags

    @pytest.mark.parametrize(
        "node_name",
        [
            "execute_python",
            "run_shell_command",
            "run_subprocess",
            "deploy_to_k8s",
            "publish_release",
        ],
    )
    def test_external_keywords(self, node_name: str) -> None:
        tags = classify_effects(node_name=node_name, kind=NodeKind.TOOL)
        assert "external" in tags

    def test_pure_tool_name_gets_no_tag(self) -> None:
        # ``compute_sum`` is a TOOL node but its name doesn't match
        # any keyword → conservative empty list.
        assert classify_effects(node_name="compute_sum", kind=NodeKind.TOOL) == []

    def test_fn_kind_ignores_keywords(self) -> None:
        # Even if the name screams "network", a FN kind isn't examined.
        # This keeps the heuristic conservative: only user-declared TOOL
        # nodes get the keyword treatment.
        assert classify_effects(node_name="call_api", kind=NodeKind.FN) == []

    def test_multi_tag_node(self) -> None:
        # A tool that both hits the network and the DB. We choose a
        # name that has two top-level keyword matches (not prefix-glued
        # like ``fetch_then_save_to_db`` — that's one compound word,
        # which is genuinely ambiguous for a heuristic).
        tags = classify_effects(node_name="http_write_db", kind=NodeKind.TOOL)
        # Taxonomy order preserved: network before db.
        assert tags == ["network", "db"]


# ---------------------------------------------------------------------------
# Signal 2: explicit override wins
# ---------------------------------------------------------------------------


class TestOverride:
    def test_override_replaces_heuristic(self) -> None:
        # Name would match ``network`` but user says it's pure.
        assert classify_effects(node_name="call_api", kind=NodeKind.TOOL, override=[]) == []

    def test_override_wins_over_llm_signal(self) -> None:
        # User asserts this LLM node has extra effects.
        assert classify_effects(
            node_name="agent",
            kind=NodeKind.LLM,
            model_name="gpt-4",
            override=["llm", "db"],
        ) == ["llm", "db"]

    def test_override_list_is_copied(self) -> None:
        # Defensive: caller mutations to the returned list mustn't
        # leak back into the recorder's effects_map.
        supplied = ["fs"]
        returned = classify_effects(node_name="x", kind=NodeKind.TOOL, override=supplied)
        returned.append("llm")
        assert supplied == ["fs"]


# ---------------------------------------------------------------------------
# count_dangerous_downstream
# ---------------------------------------------------------------------------


class TestCountDangerous:
    def test_llm_alone_is_not_dangerous_by_default(self) -> None:
        # Key design call: "llm" is NOT in the default dangerous set,
        # because re-running an LLM call on a fork IS the point.
        assert count_dangerous_downstream(downstream_effects=[["llm"], ["llm"]]) == 0

    def test_counts_network_fs_db_external(self) -> None:
        effects = [["network"], ["fs"], ["db"], ["external"], ["llm"], []]
        assert count_dangerous_downstream(downstream_effects=effects) == 4

    def test_multi_tag_node_counts_once(self) -> None:
        # A single node with both ``fs`` and ``db`` still counts as 1.
        assert count_dangerous_downstream(downstream_effects=[["fs", "db"], []]) == 1

    def test_custom_dangerous_set(self) -> None:
        # Team that is bill-sensitive about LLM spend can widen the set.
        assert (
            count_dangerous_downstream(
                downstream_effects=[["llm"], []],
                dangerous=frozenset({"llm"}),
            )
            == 1
        )

    def test_default_set_shape(self) -> None:
        # Lock the public default so future changes are intentional.
        assert frozenset({"network", "fs", "db", "external"}) == DANGEROUS_EFFECTS_DEFAULT
