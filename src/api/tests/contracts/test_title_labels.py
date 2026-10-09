from langboard_shared.domain.contracts.title_labels import global_label_names, parse_title_labels


def names():
    return global_label_names(
        [
            {"uid": "bug", "name": "Bug", "translations": {"ko": {"name": "버그"}}},
            {"uid": "question", "name": "Question", "translations": {"ja": {"name": "質問"}}},
        ]
    )


def test_contiguous_prefix_exact_translation_and_deduplication():
    result = parse_title_labels("[Bug] [버그][Unknown] [質問] Fix [Bug] literally", names())
    assert result.title == "[Unknown] Fix [Bug] literally"
    assert result.global_label_uids == ("bug", "question")


def test_nonmatches_are_byte_preserved_and_interior_tokens_are_literal():
    for title in ["[bug] Fix", "[ Bug ] Fix", "Fix [Bug]", " [Bug] Fix", "[Unknown]  Fix", "[Unknown]\n[Bug] Fix"]:
        result = parse_title_labels(title, names())
        assert result.title == title
        assert result.global_label_uids == ()


def test_empty_result_and_malformed_tokens_preserve_input():
    for title in ["[Bug]", "[Bug] [Question]  ", "[[Bug]] Fix", "[Bug\n] Fix", "[" + "x" * 101 + "] [Bug] Fix"]:
        result = parse_title_labels(title, names())
        assert result.title == title
        assert result.global_label_uids == ()


def test_ambiguous_translated_name_never_selects_by_iteration_order():
    labels = [
        {"uid": "first", "name": "One", "translations": {"ko": {"name": "동일"}}},
        {"uid": "second", "name": "Two", "translations": {"ko": {"name": "동일"}}},
    ]
    for ordered in [labels, list(reversed(labels))]:
        index = global_label_names(ordered)
        result = parse_title_labels("[동일] [One] Fix", index)
        assert result.title == "[동일] Fix"
        assert result.global_label_uids == ("first",)


def test_aliases_match_exactly_and_collisions_stay_literal():
    labels = [
        {"uid": "bug", "name": "Bug", "aliases": ["Defect", "同じ"]},
        {"uid": "question", "name": "Question", "aliases": ["同じ"]},
    ]
    for ordered in [labels, list(reversed(labels))]:
        index = global_label_names(ordered)
        assert parse_title_labels("[Defect] Fixed", index).global_label_uids == ("bug",)
        assert parse_title_labels("[defect] Fixed", index).title == "[defect] Fixed"
        assert parse_title_labels("[同じ] Fixed", index).title == "[同じ] Fixed"
