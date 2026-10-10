"""Explicit app event delivery; no scheduler or implicit runtime start."""

from ...domain.services.AppEventDelivery import claim_app_event, finish_app_event, revalidate_app_event_claim
from .utils import ensure_public_webhook_url
from .WebhookTask import EXECUTION_WEBHOOK_TIMEOUT, post_resolved_webhook_bytes


class AppEventDeliveryFailed(RuntimeError):
    """A bounded HTTP attempt failed; retry state remains durable."""


async def deliver_app_event(event_id, expected_destination_revision):
    claim = claim_app_event(event_id, expected_destination_revision)
    if claim is None:
        return None
    try:
        target = await ensure_public_webhook_url(claim["url"])
        current = revalidate_app_event_claim(event_id, claim["claim_token"], expected_destination_revision)
        if current is None:
            return None
        if current["url"] != claim["url"] or current["body"] != claim["body"]:
            raise AppEventDeliveryFailed("Delivery snapshot changed")
        await post_resolved_webhook_bytes(
            target, current["body"], current["headers"], timeout=EXECUTION_WEBHOOK_TIMEOUT
        )
    except Exception as error:
        finish_app_event(event_id, claim["claim_token"], delivered=False)
        raise AppEventDeliveryFailed("App event HTTP delivery failed") from error
    return finish_app_event(event_id, claim["claim_token"], delivered=True)
