"""Bounded page-local containment forest; other semantics remain explicit edges."""


def card_tree(items: list[dict], relationships: list[dict]) -> tuple[list[dict], list[dict]]:
    cards = {item["uid"]: item for item in items}
    edges = [edge for edge in relationships if edge["parent_card_uid"] in cards and edge["child_card_uid"] in cards]
    children = {uid: [] for uid in cards}
    incoming = set()
    for edge in edges:
        if edge.get("machine_semantic") == "contains":
            parent, child = edge["parent_card_uid"], edge["child_card_uid"]
            if child not in children[parent]:
                children[parent].append(child)
            incoming.add(child)
    emitted = set()

    def node(uid, ancestors):
        if uid in ancestors:
            return {"card_ref": uid, "reason": "cycle"}
        if uid in emitted:
            return {"card_ref": uid, "reason": "multiple_parent"}
        emitted.add(uid)
        return {**cards[uid], "children": [node(child, ancestors | {uid}) for child in children[uid]]}

    roots = [node(uid, set()) for uid in cards if uid not in incoming]
    # Cyclic components have no natural root; emit each remaining component once.
    for uid in cards:
        if uid not in emitted:
            roots.append(node(uid, set()))
    return roots, edges
