from typing import TYPE_CHECKING, TypeVar
from ...core.types import Factory
from ...infrastructure.repositories import Repository
from . import factory


if TYPE_CHECKING:
    from ...core.domain import BaseDomainService


_TBaseDomainService = TypeVar("_TBaseDomainService", bound="BaseDomainService")


class DomainService(Factory):
    def __init__(self):
        super().__init__()
        self.__repo: Repository | None = None

    def _create_or_get_product(self, product: type[_TBaseDomainService]):
        if self.__repo is None:
            self.__repo = Repository()

        product_name = product.name()
        if product_name not in self._products:
            self._products[product_name] = product(self._create_or_get_product, self._get_product_by_name, self.__repo)
        target_product: _TBaseDomainService = self._products[product_name]  # type: ignore

        return target_product

    def initialize(self, repository: Repository):
        self.__repo = repository

    @property
    def user(self):
        return self._create_or_get_product(factory.UserService)

    @property
    def project(self):
        return self._create_or_get_product(factory.ProjectService)

    @property
    def project_invitation(self):
        return self._create_or_get_product(factory.ProjectInvitationService)

    @property
    def notification(self):
        return self._create_or_get_product(factory.NotificationService)

    @property
    def email(self):
        return self._create_or_get_product(factory.EmailService)

    @property
    def project_column(self):
        return self._create_or_get_product(factory.ProjectColumnService)

    @property
    def project_label(self):
        return self._create_or_get_product(factory.ProjectLabelService)

    @property
    def user_notification_setting(self):
        return self._create_or_get_product(factory.UserNotificationSettingService)

    @property
    def user_group(self):
        return self._create_or_get_product(factory.UserGroupService)

    @property
    def activity(self):
        return self._create_or_get_product(factory.ActivityService)

    @property
    def graph_approval_request(self):
        return self._create_or_get_product(factory.GraphApprovalRequestService)

    @property
    def app_setting(self):
        return self._create_or_get_product(factory.AppSettingService)

    @property
    def bot_log(self):
        return self._create_or_get_product(factory.BotLogService)

    @property
    def bot(self):
        return self._create_or_get_product(factory.BotService)

    @property
    def bot_default_scope_branch(self):
        return self._create_or_get_product(factory.BotDefaultScopeBranchService)

    @property
    def reaction(self):
        return self._create_or_get_product(factory.ReactionService)

    @property
    def project_wiki(self):
        return self._create_or_get_product(factory.ProjectWikiService)

    @property
    def chat(self):
        return self._create_or_get_product(factory.ChatService)

    @property
    def internal_bot(self):
        return self._create_or_get_product(factory.InternalBotService)

    @property
    def identity_link(self):
        return self._create_or_get_product(factory.IdentityLinkService)

    @property
    def scim_provisioning(self):
        return self._create_or_get_product(factory.ScimProvisioningService)

    @property
    def metadata(self):
        return self._create_or_get_product(factory.MetadataService)

    @property
    def orchestration_task(self):
        return self._create_or_get_product(factory.OrchestrationTaskService)

    @property
    def card(self):
        return self._create_or_get_product(factory.CardService)

    @property
    def card_relationship(self):
        return self._create_or_get_product(factory.CardRelationshipService)

    @property
    def card_attachment(self):
        return self._create_or_get_product(factory.CardAttachmentService)

    @property
    def card_comment(self):
        return self._create_or_get_product(factory.CardCommentService)

    @property
    def docling_metadata(self):
        return self._create_or_get_product(factory.DoclingMetadataService)

    @property
    def checkitem(self):
        return self._create_or_get_product(factory.CheckitemService)

    @property
    def checklist(self):
        return self._create_or_get_product(factory.ChecklistService)

    @property
    def mcp_tool_group(self):
        return self._create_or_get_product(factory.McpToolGroupService)

    @property
    def api_key(self):
        return self._create_or_get_product(factory.ApiKeyService)
