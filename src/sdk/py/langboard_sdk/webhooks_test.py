import unittest
from hashlib import sha256
from hmac import new
from .webhooks import InvalidWebhook, verify_webhook


class WebhookTest(unittest.TestCase):
    def test_exact_signed_bytes_window_and_case_insensitive_headers(self):
        body = '{"event_id":"one","title":"한글"}'.encode()
        timestamp, secret = "1700000000", "example-secret"
        headers = {"X-Langboard-Webhook-Version": "1", "X-Langboard-Webhook-Timestamp": timestamp,
                   "X-Langboard-Webhook-Signature": "v1=" + new(secret.encode(), timestamp.encode() + b"." + body, sha256).hexdigest()}
        verify_webhook(body, headers, secret, now=1700000000)
        verify_webhook(body, {k.lower(): v for k, v in headers.items()}, secret, now=1700000300)
        for changed_body, changed_headers, changed_secret, now in (
            (body+b" ", headers, secret, 1700000000),
            (body, headers, "wrong", 1700000000),
            (body, headers, secret, 1700000301),
            (body, headers, secret, 1699999969),
            (body, {**headers, "x-langboard-webhook-version": "1"}, secret, 1700000000),
            (body, {**headers, "X-Langboard-Webhook-Version": "2"}, secret, 1700000000),
            (body, headers, "", 1700000000),
        ):
            with self.subTest(now=now), self.assertRaises(InvalidWebhook):
                verify_webhook(changed_body, changed_headers, changed_secret, now=now)

    def test_rejects_unsigned_unbounded_or_malformed_requests(self):
        for body, headers in ((b"x", {}), (b"x"*1048577, {}), ("not bytes", {})):
            with self.assertRaises(InvalidWebhook):
                verify_webhook(body, headers, "secret", now=1)
