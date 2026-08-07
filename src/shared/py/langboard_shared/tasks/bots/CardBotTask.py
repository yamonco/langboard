from ...core.broker import Broker
from ...domain.models import Bot, Card, Project, ProjectColumn, User
from ...domain.models.bases import BotTriggerCondition
from .utils import BotTaskDataHelper, BotTaskHelper, BotTaskSchemaHelper


@BotTaskSchemaHelper.card_schema(BotTriggerCondition.CardCreated)
@Broker.wrap_async_task_decorator
async def card_created(user_or_bot: User | Bot, project: Project, card: Card):
    bots = BotTaskHelper.get_scoped_bots(
        BotTriggerCondition.CardCreated,
        project_id=project.id,
        project_column_id=card.project_column_id,
        card_id=card.id,
    )
    await BotTaskHelper.run(
        bots, BotTriggerCondition.CardCreated, BotTaskDataHelper.create_card(user_or_bot, project, card), project
    )


@BotTaskSchemaHelper.card_schema(BotTriggerCondition.CardUpdated)
@Broker.wrap_async_task_decorator
async def card_updated(user_or_bot: User | Bot, project: Project, card: Card):
    bots = BotTaskHelper.get_scoped_bots(
        BotTriggerCondition.CardUpdated,
        project_id=project.id,
        project_column_id=card.project_column_id,
        card_id=card.id,
    )
    await BotTaskHelper.run(
        bots, BotTriggerCondition.CardUpdated, BotTaskDataHelper.create_card(user_or_bot, project, card), project
    )


@BotTaskSchemaHelper.card_schema(BotTriggerCondition.CardMoved)
@Broker.wrap_async_task_decorator
async def card_moved(user_or_bot: User | Bot, project: Project, card: Card, old_column: ProjectColumn):
    bots = BotTaskHelper.get_scoped_bots(
        BotTriggerCondition.CardMoved, project_id=project.id, project_column_id=card.project_column_id, card_id=card.id
    )
    await BotTaskHelper.run(
        bots,
        BotTriggerCondition.CardMoved,
        {
            **BotTaskDataHelper.create_card(user_or_bot, project, card),
            "old_project_column_uid": old_column.get_uid(),
            "old_project_column_name": old_column.name,
            "old_project_column_is_archive": old_column.is_archive,
        },
        project,
    )


@BotTaskSchemaHelper.card_schema(BotTriggerCondition.CardLabelsUpdated)
@Broker.wrap_async_task_decorator
async def card_labels_updated(user_or_bot: User | Bot, project: Project, card: Card):
    bots = BotTaskHelper.get_scoped_bots(
        BotTriggerCondition.CardLabelsUpdated,
        project_id=project.id,
        project_column_id=card.project_column_id,
        card_id=card.id,
    )
    await BotTaskHelper.run(
        bots,
        BotTriggerCondition.CardLabelsUpdated,
        BotTaskDataHelper.create_card(user_or_bot, project, card),
        project,
    )


@BotTaskSchemaHelper.card_schema(BotTriggerCondition.CardRelationshipsUpdated)
@Broker.wrap_async_task_decorator
async def card_relationship_updated(user_or_bot: User | Bot, project: Project, card: Card):
    bots = BotTaskHelper.get_scoped_bots(
        BotTriggerCondition.CardRelationshipsUpdated,
        project_id=project.id,
        project_column_id=card.project_column_id,
        card_id=card.id,
    )
    await BotTaskHelper.run(
        bots,
        BotTriggerCondition.CardRelationshipsUpdated,
        BotTaskDataHelper.create_card(user_or_bot, project, card),
        project,
    )


@BotTaskSchemaHelper.card_schema(BotTriggerCondition.CardDeleted)
@Broker.wrap_async_task_decorator
async def card_deleted(user_or_bot: User | Bot, project: Project, card: Card):
    bots = BotTaskHelper.get_scoped_bots(
        BotTriggerCondition.CardDeleted,
        project_id=project.id,
        project_column_id=card.project_column_id,
        card_id=card.id,
    )
    await BotTaskHelper.run(
        bots, BotTriggerCondition.CardDeleted, BotTaskDataHelper.create_card(user_or_bot, project, card), project
    )
