from typing import Any
from ....core.domain import BaseDomainService
from ....core.types.ParamTypes import TCardParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ...contracts.content_block_migration import extract_legacy_blocks
from ...contracts.content_blocks import (
    ContentBlockType,
    build_payload,
    check_revision,
)
from ...models import Card, CardContentBlock, Project


class CardContentBlockService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "card_content_block"

    def get_by_id_like(self, block) -> CardContentBlock | None:
        return InfraHelper.get_by_id_like(CardContentBlock, block)

    def get_blocks_by_card(self, card: TCardParam) -> list[CardContentBlock]:
        return self.repo.card_content_block.get_all_by_card(card)

    def api_blocks_by_card(self, card: TCardParam) -> list[dict[str, Any]]:
        """Public projection of a card's blocks (bounded payloads)."""

        return [
            {
                "block_uid": block.get_uid(),
                "type": block.block_type,
                "order": block.order,
                "revision": block.revision,
                "payload": block.payload,
                "updated_at": block.updated_at.isoformat() if block.updated_at else None,
            }
            for block in self.get_blocks_by_card(card)
        ]

    def create(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        block_type: str,
        payload: dict[str, Any],
        order: int | None = None,
        after_block_uid: str | None = None,
    ) -> CardContentBlock | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        _project, card = params

        resolved_type = ContentBlockType(block_type)
        normalized = build_payload(resolved_type, payload)

        siblings = self.repo.card_content_block.get_all_by_card(card)
        insert_at = len(siblings)
        if after_block_uid is not None:
            anchor_index = next(
                (i for i, s in enumerate(siblings) if s.get_uid() == after_block_uid), None
            )
            if anchor_index is None:
                raise ValueError(f"after_block_uid {after_block_uid} not found")
            insert_at = anchor_index + 1
        elif order is not None:
            if order < 0 or order > len(siblings):
                raise ValueError(f"order must be 0..{len(siblings)}")
            insert_at = order

        block = CardContentBlock(
            card_id=card.id,
            block_type=resolved_type.value,
            order=insert_at,
            revision=1,
            payload=normalized,
        )
        self.repo.card_content_block.insert(block)

        siblings.insert(insert_at, block)
        self.repo.card_content_block.renumber(card.id, [b.id for b in siblings])
        block.order = insert_at

        from .CardService import CardService

        card_service = self._get_service(CardService)
        card_service.mark_card_changed(card, "card", block.id)

        return block

    def update(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        block_uid: str,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> CardContentBlock | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        _project, card = params

        block = self.repo.card_content_block.get_by_uid_card(block_uid, card)
        if not block:
            return None
        check_revision(expected_revision, block.revision)

        merged = {**block.payload, **{k: v for k, v in payload.items() if v is not None}}
        block.payload = build_payload(ContentBlockType(block.block_type), merged)
        block.revision += 1
        self.repo.card_content_block.update(block)

        from .CardService import CardService

        card_service = self._get_service(CardService)
        card_service.mark_card_changed(card, "card", block.id)
        return block

    def delete(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        block_uid: str,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        _project, card = params

        block = self.repo.card_content_block.get_by_uid_card(block_uid, card)
        if not block:
            return None

        self.repo.card_content_block.delete(block)
        siblings = self.repo.card_content_block.get_all_by_card(card)
        self.repo.card_content_block.renumber(card.id, [b.id for b in siblings])

        from .CardService import CardService

        card_service = self._get_service(CardService)
        card_service.mark_card_changed(card, "card")
        return True

    def move(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        block_uid: str,
        after_block_uid: str | None,
        order: int | None = None,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        _project, card = params

        siblings = self.repo.card_content_block.get_all_by_card(card)
        uid_list = [b.get_uid() for b in siblings]
        if block_uid not in uid_list:
            return None

        moving = next(b for b in siblings if b.get_uid() == block_uid)
        siblings.remove(moving)
        if after_block_uid is not None:
            if after_block_uid == block_uid:
                raise ValueError("cannot place a block after itself")
            anchor_index = next((i for i, b in enumerate(siblings) if b.get_uid() == after_block_uid), None)
            if anchor_index is None:
                raise ValueError(f"after_block_uid {after_block_uid} not found")
            insert_at = anchor_index + 1
        elif order is not None:
            if order < 0 or order > len(siblings):
                raise ValueError(f"order must be 0..{len(siblings)}")
            insert_at = order
        else:
            insert_at = len(siblings)

        siblings.insert(insert_at, moving)
        self.repo.card_content_block.renumber(card.id, [b.id for b in siblings])

        from .CardService import CardService

        card_service = self._get_service(CardService)
        card_service.mark_card_changed(card, "card", moving.id)
        return True

    def replace_blocks(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Atomically replace every block of a card (editor full-save).

        Each entry: {block_type, payload, order}. Order is renumbered
        from the given sequence; empty list clears the card's blocks so
        the viewer falls back to the legacy description.
        """

        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return []
        _project, card = params

        for entry in blocks:
            resolved_type = ContentBlockType(entry["block_type"])
            build_payload(resolved_type, entry["payload"])

        existing = self.repo.card_content_block.get_all_by_card(card)
        for block in existing:
            self.repo.card_content_block.delete(block)

        created = []
        for index, entry in enumerate(blocks):
            resolved_type = ContentBlockType(entry["block_type"])
            block = CardContentBlock(
                card_id=card.id,
                block_type=resolved_type.value,
                order=index,
                revision=1,
                payload=build_payload(resolved_type, entry["payload"]),
            )
            self.repo.card_content_block.insert(block)
            created.append(block)

        from .CardService import CardService

        card_service = self._get_service(CardService)
        card_service.mark_card_changed(card, "card", created[-1].id if created else None)
        return self.api_blocks_by_card(card)

    def migrate_card_description(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
    ) -> list[dict[str, Any]] | None:
        """Migrate one card's legacy description into blocks (idempotent).

        Cards that already have blocks are skipped unchanged. Cards whose
        description has no code/diagram segments are skipped too — the
        legacy description remains the render source.
        """

        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        _project, card = params

        if self.repo.card_content_block.get_all_by_card(card):
            return []  # already migrated

        blocks = extract_legacy_blocks(card.description.content or "")
        if not blocks:
            return []

        return self.replace_blocks(user_or_bot, project, card, blocks)

    def migrate_project(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Batch-migrate every legacy card of a project; returns an audit report."""

        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return {"scanned": 0, "migrated": 0, "skipped_has_blocks": 0, "skipped_no_segments": 0, "failed": []}
        cards = self.repo.card.get_all_by_project(project, limit=limit)
        scanned = migrated = skipped_blocks = skipped_plain = 0
        failures: list[str] = []
        for card in cards:
            scanned += 1
            try:
                result = self.migrate_card_description(user_or_bot, project, card)
                if result is None:
                    failures.append(card.get_uid())
                elif result == []:
                    if self.repo.card_content_block.get_all_by_card(card):
                        skipped_blocks += 1
                    else:
                        skipped_plain += 1
                else:
                    migrated += 1
            except Exception:
                failures.append(card.get_uid())
        return {
            "scanned": scanned,
            "migrated": migrated,
            "skipped_has_blocks": skipped_blocks,
            "skipped_no_segments": skipped_plain,
            "failed": failures,
        }
