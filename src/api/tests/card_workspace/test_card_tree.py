from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.card_workspace.application.card_tree import card_tree
from langboard.card_workspace.application.queries import list_project_cards


def edge(parent, child, semantic="contains"):
    return {"parent_card_uid": parent, "child_card_uid": child, "machine_semantic": semantic}


def test_tree_cycles_multiple_parents_and_other_semantics_are_not_duplicated():
    items = [{"uid": uid, "title": uid} for uid in "abcde"]
    tree, edges = card_tree(items, [edge("a", "b"), edge("a", "c"), edge("c", "b"),
        edge("b", "a"), edge("d", "e", "blocks"), edge("e", "d", "references"), edge("a", "hidden")])
    def flatten(nodes):
        return [node for n in nodes for node in [n, *flatten(n.get("children", []))]]
    nodes = flatten(tree)
    assert sorted(n["uid"] for n in nodes if "uid" in n) == list("abcde")
    assert {n["reason"] for n in nodes if "reason" in n} == {"cycle", "multiple_parent"}
    assert len(edges) == 6
    assert "hidden" not in str(tree) + str(edges)
    assert next(n for n in nodes if n.get("uid") == "d")["children"] == []


def test_normal_has_original_shape_and_tree_keeps_page_cursor_and_counts():
    port = SimpleNamespace(get_project_card_page=Mock(return_value=SimpleNamespace(
        items=[{"uid": "a", "title": "A"}, {"uid": "b", "title": "B"}], total_count=100,
        next_cursor_fields=("2026-10-08T00:00:00+00:00", "b"), workflow_stages={}, columns={},
    )), get_project_card_relationships=Mock(return_value=[edge("a", "b")]))
    normal = list_project_cards(port, "board", format="normal").model_dump(mode="json")
    assert set(normal) == {"project_uid", "cards", "workflow_stages", "columns"}
    port.get_project_card_relationships.assert_not_called()
    tree = list_project_cards(port, "board", format="tree").model_dump(mode="json")
    assert tree["cards"]["items"][0]["children"][0]["uid"] == "b"
    assert tree["cards"]["next_cursor"] == normal["cards"]["next_cursor"]
    assert tree["cards"]["total_count"] == 100
    assert tree["relationship_scope"] == "current_page"
    port.get_project_card_relationships.assert_called_once_with("board", ["a", "b"])
    with pytest.raises(ValueError, match="format"):
        list_project_cards(port, "board", format="invalid")
