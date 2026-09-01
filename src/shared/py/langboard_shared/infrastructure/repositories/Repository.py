from ...core.types import Factory
from . import factory


class Repository(Factory):
    @property
    def user(self):
        return self._create_or_get_product(factory.UserRepository)

    @property
    def project(self):
        return self._create_or_get_product(factory.ProjectRepository)

    @property
    def project_template(self):
        return self._create_or_get_product(factory.ProjectTemplateRepository)

    @property
    def role(self):
        return self._create_or_get_product(factory.RoleRepository)

    @property
    def project_column(self):
        return self._create_or_get_product(factory.ProjectColumnRepository)

    @property
    def project_email_notification(self):
        return self._create_or_get_product(factory.ProjectEmailNotificationRepository)

    @property
    def card(self):
        return self._create_or_get_product(factory.CardRepository)

    @property
    def project_label(self):
        return self._create_or_get_product(factory.ProjectLabelRepository)

    @property
    def user_group(self):
        return self._create_or_get_product(factory.UserGroupRepository)

    @property
    def checklist(self):
        return self._create_or_get_product(factory.ChecklistRepository)

    @property
    def checkitem(self):
        return self._create_or_get_product(factory.CheckitemRepository)

    @property
    def card_attachment(self):
        return self._create_or_get_product(factory.CardAttachmentRepository)

    @property
    def card_comment(self):
        return self._create_or_get_product(factory.CardCommentRepository)

    @property
    def card_relationship(self):
        return self._create_or_get_product(factory.CardRelationshipRepository)

    @property
    def bot(self):
        return self._create_or_get_product(factory.BotRepository)

    @property
    def bot_default_scope_branch(self):
        return self._create_or_get_product(factory.BotDefaultScopeBranchRepository)

    @property
    def project_bot_scope(self):
        return self._create_or_get_product(factory.ProjectBotScopeRepository)

    @property
    def project_column_bot_scope(self):
        return self._create_or_get_product(factory.ProjectColumnBotScopeRepository)

    @property
    def card_bot_scope(self):
        return self._create_or_get_product(factory.CardBotScopeRepository)

    @property
    def bot_log(self):
        return self._create_or_get_product(factory.BotLogRepository)

    @property
    def project_bot_default_scope(self):
        return self._create_or_get_product(factory.ProjectBotDefaultScopeRepository)

    @property
    def project_column_bot_default_scope(self):
        return self._create_or_get_product(factory.ProjectColumnBotDefaultScopeRepository)

    @property
    def card_bot_default_scope(self):
        return self._create_or_get_product(factory.CardBotDefaultScopeRepository)

    @property
    def global_card_relationship_type(self):
        return self._create_or_get_product(factory.GlobalCardRelationshipTypeRepository)

    @property
    def graph_approval_request(self):
        return self._create_or_get_product(factory.GraphApprovalRequestRepository)

    @property
    def activity(self):
        return self._create_or_get_product(factory.ActivityRepository)

    @property
    def internal_bot(self):
        return self._create_or_get_product(factory.InternalBotRepository)

    @property
    def metadata(self):
        return self._create_or_get_product(factory.MetadataRepository)

    @property
    def user_notification(self):
        return self._create_or_get_product(factory.UserNotificationRepository)

    @property
    def project_invitation(self):
        return self._create_or_get_product(factory.ProjectInvitationRepository)

    @property
    def reaction(self):
        return self._create_or_get_product(factory.ReactionRepository)

    @property
    def user_notification_setting(self):
        return self._create_or_get_product(factory.UserNotificationSettingRepository)

    @property
    def user_profile(self):
        return self._create_or_get_product(factory.UserProfileRepository)

    @property
    def user_email(self):
        return self._create_or_get_product(factory.UserEmailRepository)

    @property
    def project_assigned_user(self):
        return self._create_or_get_product(factory.ProjectAssignedUserRepository)

    @property
    def project_user_relationship(self):
        return self._create_or_get_product(factory.ProjectUserRelationshipRepository)

    @property
    def user_group_assigned_email(self):
        return self._create_or_get_product(factory.UserGroupAssignedEmailRepository)

    @property
    def scim_group(self):
        return self._create_or_get_product(factory.ScimGroupRepository)

    @property
    def scim_group_member(self):
        return self._create_or_get_product(factory.ScimGroupMemberRepository)

    @property
    def user_identity_link(self):
        return self._create_or_get_product(factory.UserIdentityLinkRepository)

    @property
    def project_wiki(self):
        return self._create_or_get_product(factory.ProjectWikiRepository)

    @property
    def project_wiki_assigned_user(self):
        return self._create_or_get_product(factory.ProjectWikiAssignedUserRepository)

    @property
    def project_wiki_attachment(self):
        return self._create_or_get_product(factory.ProjectWikiAttachmentRepository)

    @property
    def project_assigned_internal_bot(self):
        return self._create_or_get_product(factory.ProjectAssignedInternalBotRepository)

    @property
    def chat_history(self):
        return self._create_or_get_product(factory.ChatHistoryRepository)

    @property
    def chat_session(self):
        return self._create_or_get_product(factory.ChatSessionRepository)

    @property
    def chat_template(self):
        return self._create_or_get_product(factory.ChatTemplateRepository)

    @property
    def card_assigned_user(self):
        return self._create_or_get_product(factory.CardAssignedUserRepository)

    @property
    def card_assigned_project_label(self):
        return self._create_or_get_product(factory.CardAssignedProjectLabelRepository)

    @property
    def checkitem_timer_record(self):
        return self._create_or_get_product(factory.CheckitemTimerRecordRepository)

    @property
    def mcp_tool_group(self):
        return self._create_or_get_product(factory.McpToolGroupRepository)

    @property
    def api_key(self):
        return self._create_or_get_product(factory.ApiKeyRepository)

    @property
    def api_key_usage(self):
        return self._create_or_get_product(factory.ApiKeyUsageRepository)

    @property
    def api_comfort_tool(self):
        return self._create_or_get_product(factory.ApiComfortToolRepository)

    @property
    def user_sign_in_history(self):
        return self._create_or_get_product(factory.UserSignInHistoryRepository)

    @property
    def mcp_tool_group_usage(self):
        return self._create_or_get_product(factory.McpToolGroupUsageRepository)

    @property
    def webhook_setting(self):
        return self._create_or_get_product(factory.WebhookSettingRepository)

    @property
    def notification_schedule_rule(self):
        return self._create_or_get_product(factory.NotificationScheduleRuleRepository)
