"""Server-owned browser links for authorized modern card reads."""

from functools import wraps
from inspect import signature
from urllib.parse import quote
from langboard_shared.Env import Env
from ..card_workspace.application.dtos import CardBundleResponse


class LinkedCardBundleResponse(CardBundleResponse):
    card_url: str
    card_link_markdown: str


def with_card_links(handler):
    """Enrich a successful read without changing authorization or legacy schemas."""

    @wraps(handler)
    async def linked(**kwargs):
        result = CardBundleResponse.model_validate(await handler(**kwargs))
        project_uid = quote(kwargs["project_uid"], safe="")
        card_uid = quote(result.card_uid, safe="")
        url = f"{Env.PUBLIC_UI_URL.rstrip('/')}/board/{project_uid}/{card_uid}"
        return LinkedCardBundleResponse(
            **result.model_dump(),
            card_url=url,
            card_link_markdown=f"[Open card in Langboard]({url})",
        )

    linked.__signature__ = signature(handler).replace(return_annotation=LinkedCardBundleResponse)
    return linked
