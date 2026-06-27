from ...core.broker import Broker
from ...domain.models import Bot, Project, User
from ...domain.models.bases import BotTriggerCondition
from .utils import BotTaskDataHelper, BotTaskHelper, BotTaskSchemaHelper


@BotTaskSchemaHelper.project_schema(BotTriggerCondition.ProjectUpdated)
@Broker.wrap_async_task_decorator
async def project_updated(user_or_bot: User | Bot, project: Project):
    bots = BotTaskHelper.get_scoped_bots(BotTriggerCondition.ProjectUpdated, project_id=project.id)
    await BotTaskHelper.run(
        bots, BotTriggerCondition.ProjectUpdated, BotTaskDataHelper.create_project(user_or_bot, project), project
    )


@BotTaskSchemaHelper.project_schema(BotTriggerCondition.ProjectDeleted)
@Broker.wrap_async_task_decorator
async def project_deleted(user: User, project: Project):
    bots = BotTaskHelper.get_scoped_bots(
        BotTriggerCondition.ProjectDeleted,
        project_id=project.id,
        with_deleted_target=True,
    )
    await BotTaskHelper.run(
        bots, BotTriggerCondition.ProjectDeleted, BotTaskDataHelper.create_project(user, project), project
    )
