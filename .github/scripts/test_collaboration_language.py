import unittest

from check_collaboration_language import violations


class CollaborationLanguageTest(unittest.TestCase):
    def test_detects_title_and_body_prose(self):
        event = {"pull_request": {"title": "제목", "body": "English\n한글 설명"}}
        self.assertEqual(violations("pull_request_target", event), [("PR title", 1), ("PR body", 2)])

    def test_title_cannot_use_markdown_exemption(self):
        event = {"pull_request": {"title": "`한글`", "body": ""}}
        self.assertEqual(violations("pull_request_target", event), [("PR title", 1)])

    def test_intentional_examples_are_exempt(self):
        body = "English `완료` example.\n```text\n한글\n```\n> 외부 인용\n<!-- langboard:localized-example:start -->\n예시\n<!-- langboard:localized-example:end -->\nEnglish"
        self.assertEqual(violations("pull_request_target", {"pull_request": {"title": "English", "body": body}}), [])

    def test_detection_resumes_after_example(self):
        body = "~~~text\n예시\n~~~\n<!-- langboard:localized-example:start -->\n예시\n<!-- langboard:localized-example:end -->\n잘못된 설명"
        event = {"issue": {"pull_request": {}}, "comment": {"body": body}}
        self.assertEqual(violations("issue_comment", event), [("PR comment", 7)])

    def test_comments_and_reviews_include_bots(self):
        for name, key, label in [("issue_comment", "comment", "PR comment"), ("pull_request_review", "review", "PR review"), ("pull_request_review_comment", "comment", "PR review comment")]:
            event = {"issue": {"pull_request": {}}, key: {"body": "사전대조", "user": {"type": "Bot"}}}
            self.assertEqual(violations(name, event), [(label, 1)])

    def test_normal_issue_comments_are_out_of_scope(self):
        self.assertEqual(violations("issue_comment", {"issue": {}, "comment": {"body": "한글"}}), [])

    def test_empty_body(self):
        self.assertEqual(violations("pull_request_target", {"pull_request": {"title": "English", "body": None}}), [])

    def test_jamo_is_detected(self):
        self.assertEqual(violations("pull_request_review", {"review": {"body": "ㄱ"}}), [("PR review", 1)])


if __name__ == "__main__":
    unittest.main()
