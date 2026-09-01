from time import sleep
from typing import cast
from langboard_shared.core.bootstrap import BaseCommand, Commander
from langboard_shared.Env import Env
from langboard_shared.FastAPIAppConfig import FastAPIAppConfig
from pydantic import SecretStr
from .commands.DbUpgradeCommand import DbUpgradeCommand, DbUpgradeCommandOptions
from .commands.RunCommand import RunCommandOptions
from .Constants import APP_CONFIG_FILE, HOST
from .Loader import ModuleLoader
from .ServerRunner import run as run_server


def execute():
    commander = Commander()

    modules = ModuleLoader.load("commands", "Command", BaseCommand, log=False)
    for module in modules.values():
        for command in module:
            if not command.__name__.endswith("Command") or (Env.IS_EXECUTABLE and command.is_only_in_dev()):  # type: ignore
                continue
            commander.add_commands(command(run_app=_run_app))  # type: ignore

    commander.run()
    return 0


def _run_app(options: RunCommandOptions):
    ssl_options = options.create_ssl_options() if options.ssl_keyfile else None

    if Env.WORKER == "main":
        DbUpgradeCommand().execute(DbUpgradeCommandOptions())
        _init_internal_bots()
        _init_admin()
        _set_full_admin_access()

    app_config = FastAPIAppConfig(APP_CONFIG_FILE)
    app_config.create(
        host=HOST,
        port=Env.API_PORT,
        uds=options.uds,
        lifespan=options.lifespan,
        ssl_options=ssl_options,
        workers=options.workers,
        timeout_keep_alive=options.timeout_keep_alive,
        healthcheck_interval=options.healthcheck_interval,
        watch=options.watch,
    )

    try:
        run_server()
    except KeyboardInterrupt:
        return


def _init_internal_bots():
    from langboard_shared.core.db import DbSession, SqlBuilder
    from langboard_shared.domain.models import InternalBot
    from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
    from langboard_shared.domain.models.InternalBot import InternalBotType

    settings = []
    with DbSession.use(readonly=True) as db:
        result = db.exec(
            SqlBuilder.select.column(InternalBot.bot_type).where(
                InternalBot.column("bot_type").in_(
                    [InternalBotType.ProjectChat, InternalBotType.EditorChat, InternalBotType.EditorCopilot]
                )
                & (InternalBot.is_default == True)  # noqa: E712
            )
        )
        settings = result.all()

    if len(settings) == 3:
        return

    with DbSession.use(readonly=False) as db:
        for bot_type in [InternalBotType.ProjectChat, InternalBotType.EditorChat, InternalBotType.EditorCopilot]:
            if bot_type in settings:
                continue

            display_name = bot_type.value.replace("_", " ").title()
            setting = InternalBot(
                bot_type=bot_type,
                display_name=display_name,
                platform=BotPlatform.Default,
                platform_running_type=BotPlatformRunningType.Default,
                is_default=True,
            )
            db.insert(setting)


def _init_admin():
    from langboard_shared.core.db import DbSession, SqlBuilder
    from langboard_shared.core.types import SafeDateTime
    from langboard_shared.domain.models import User, UserProfile

    user_count = 0
    with DbSession.use(readonly=True) as db:
        result = db.exec(SqlBuilder.select.count(User, User.id).where(User.is_admin == True))  # noqa
        user_count = result.first()

    if user_count:
        return

    admin = User(
        firstname="Admin",
        lastname="User",
        email=Env.ADMIN_EMAIL,
        password=cast(SecretStr, Env.ADMIN_PASSWORD),
        username="admin",
        is_admin=True,
        activated_at=SafeDateTime.now(),
    )
    with DbSession.use(readonly=False) as db:
        db.insert(admin)

    if admin.is_new():
        _init_admin()
        return

    admin_profile = None
    while not admin_profile:
        with DbSession.use(readonly=False) as db:
            admin_profile = UserProfile(user_id=admin.id, industry="", purpose="")
            db.insert(admin_profile)
        sleep(1)


def _set_full_admin_access():
    if not Env.FULL_ADMIN_ACCESS_EMAILS:
        return

    from langboard_shared.core.db import DbSession, SqlBuilder
    from langboard_shared.domain.models import ApiKeyRole, McpRole, SettingRole, User
    from langboard_shared.domain.models.bases.BaseRoleModel import ALL_GRANTED

    with DbSession.use(readonly=False) as db:
        admin_users = db.exec(
            SqlBuilder.select.table(User).where(User.column("email").in_(Env.FULL_ADMIN_ACCESS_EMAILS))
        ).all()
        for admin in admin_users:
            setting_role = db.exec(
                SqlBuilder.select.table(SettingRole).where(SettingRole.column("user_id") == admin.id).limit(1)
            ).first()
            if not setting_role:
                setting_role = SettingRole(user_id=admin.id, actions=[ALL_GRANTED])
                db.insert(setting_role)
            if not setting_role.is_all_granted():
                setting_role.set_all_actions()
                db.update(setting_role)

            api_key_role = db.exec(
                SqlBuilder.select.table(ApiKeyRole).where(ApiKeyRole.column("user_id") == admin.id).limit(1)
            ).first()
            if not api_key_role:
                api_key_role = ApiKeyRole(user_id=admin.id, actions=[ALL_GRANTED])
                db.insert(api_key_role)
            if not api_key_role.is_all_granted():
                api_key_role.set_all_actions()
                db.update(api_key_role)

            mcp_role = db.exec(
                SqlBuilder.select.table(McpRole).where(McpRole.column("user_id") == admin.id).limit(1)
            ).first()
            if not mcp_role:
                mcp_role = McpRole(user_id=admin.id, actions=[ALL_GRANTED])
                db.insert(mcp_role)
            if not mcp_role.is_all_granted():
                mcp_role.set_all_actions()
                db.update(mcp_role)
