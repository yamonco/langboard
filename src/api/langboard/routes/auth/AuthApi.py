from fastapi import Request, status
from jwt import ExpiredSignatureError
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.utils.Encryptor import Encryptor
from langboard_shared.domain.models import Bot, BotDefaultScopeBranch, User, UserEmail, UserGroup, UserProfile
from langboard_shared.domain.models.UserNotification import NotificationType
from langboard_shared.domain.models.UserNotificationUnsubscription import NotificationChannel, NotificationScope
from langboard_shared.domain.models.UserSignInHistory import SignInErrorCode
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.security import Auth
from typing_extensions import Annotated
from .forms import AuthEmailForm, AuthEmailResponse, SignInForm


@AppRouter.api.get(
    "/auth/provider",
    tags=["Auth"],
    responses=OpenApiSchema().suc({"provider": "string", "oidc_enabled": "bool", "scim_enabled": "bool"}).get(),
)
def auth_provider() -> JsonResponse:
    return JsonResponse(
        content={
            "provider": Env.AUTH_PROVIDER,
            "oidc_enabled": Env.OIDC_ENABLED,
            "scim_enabled": Env.SCIM_ENABLED,
        }
    )


@AppRouter.api.post(
    "/auth/email",
    response_model=AuthEmailResponse,
    tags=["Auth"],
    responses=(
        OpenApiSchema().suc(AuthEmailResponse).err(406, ApiErrorCode.AU1002).err(404, ApiErrorCode.NF1004).get()
    ),
)
def auth_email(
    form: AuthEmailForm, service: Annotated[DomainService, DomainService.scope()]
) -> JsonResponse | AuthEmailResponse:
    if form.is_token:
        user, subemail = service.user.get_by_token(form.token, form.sign_token)
    else:
        user, subemail = service.user.get_by_email(form.email)

    if subemail and not subemail.verified_at:
        raise ApiException.NotAcceptable_406(ApiErrorCode.AU1002)

    if not user:
        raise ApiException.NotFound_404(ApiErrorCode.NF1004)

    token = Encryptor.encrypt(user.email, form.sign_token)
    return AuthEmailResponse(token=token, email=user.email)


@AppRouter.api.post(
    "/auth/signin",
    tags=["Auth"],
    responses=(
        OpenApiSchema()
        .suc({"access_token": "string"})
        .err(404, ApiErrorCode.VA1001, ApiErrorCode.VA1002)
        .err(406, ApiErrorCode.AU1002)
        .err(423, ApiErrorCode.AU1003)
        .get()
    ),
)
def sign_in(request: Request, form: SignInForm, service: DomainService = DomainService.scope()) -> JsonResponse:
    ip_address = AuthSecurity.get_client_ip(request.headers)

    user, subemail = service.user.get_by_token(form.email_token, form.sign_token)

    if not user:
        raise ApiException.NotFound_404(ApiErrorCode.VA1001)

    if subemail and not subemail.verified_at:
        service.user.log_sign_in(
            user=user, is_success=False, ip_address=ip_address, error_code=SignInErrorCode.EmailNotVerified
        )
        raise ApiException.NotAcceptable_406(ApiErrorCode.AU1002)

    if not user.check_password(form.password):
        service.user.log_sign_in(
            user=user, is_success=False, ip_address=ip_address, error_code=SignInErrorCode.InvalidPassword
        )
        raise ApiException.NotFound_404(ApiErrorCode.VA1002)

    if not user.activated_at:
        service.user.log_sign_in(
            user=user, is_success=False, ip_address=ip_address, error_code=SignInErrorCode.AccountNotActivated
        )
        raise ApiException.Locked_423(ApiErrorCode.AU1003)

    access_token, refresh_token = AuthSecurity.authenticate(user.id)

    service.user.log_sign_in(user=user, is_success=True, ip_address=ip_address)

    response = JsonResponse(content={"access_token": access_token})
    response.set_cookie(
        Env.REFRESH_TOKEN_NAME,
        refresh_token,
        max_age=Env.JWT_RT_EXPIRATION * 60 * 60 * 24,
        domain=Env.DOMAIN if Env.DOMAIN else None,
        httponly=True,
        secure=Env.PUBLIC_UI_URL.startswith("https"),
    )

    return response


@AppRouter.api.post(
    "/auth/refresh",
    tags=["Auth"],
    responses=(
        OpenApiSchema()
        .suc({"access_token": "string"})
        .err(422, ApiErrorCode.AU1004)
        .err(401, ApiErrorCode.AU1004)
        .get()
    ),
)
def refresh(request: Request) -> JsonResponse:
    try:
        refresh_token = request.cookies.get(Env.REFRESH_TOKEN_NAME, None)
        if not refresh_token:
            raise Exception()

        new_access_token = AuthSecurity.refresh(refresh_token)
        user = Auth.get_user_by_token(new_access_token)

        if not user:
            raise Exception()
    except ExpiredSignatureError:
        raise ApiException.UnprocessableContent_422()
    except Exception:
        raise ApiException.Unauthorized_401()

    return JsonResponse(content={"access_token": new_access_token})


@AppRouter.api.get(
    "/auth/me",
    tags=["Auth"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "user": (
                    (User, UserProfile),
                    {
                        "schema": {
                            "preferred_lang": "string",
                            "user_groups": [UserGroup],
                            "subemails": [UserEmail],
                            "is_admin?": "bool",
                            "notification_unsubs": {
                                NotificationScope.All.value: {
                                    NotificationType: {
                                        NotificationChannel: "bool",
                                    }
                                },
                                NotificationScope.Specific.value: {
                                    NotificationType: {
                                        NotificationChannel: ["<specific uid>"],
                                    }
                                },
                            },
                        }
                    },
                ),
                "bots": [Bot, {"schema": {"default_scope_branches": [BotDefaultScopeBranch]}}],
            }
        )
        .auth()
        .forbidden()
        .get()
    ),
)
@AuthFilter.add("user")
def about_me(user: User = Auth.scope("user"), service: DomainService = DomainService.scope()) -> JsonResponse:
    profile = service.user.get_api_profile(user)
    response = {
        **user.api_response(),
        **profile,
        "preferred_lang": service.user.get_preferred_lang(user),
    }
    response["user_groups"] = service.user_group.get_api_list_by_user(user)
    response["subemails"] = service.user.get_subemails(user)
    response["notification_unsubs"] = service.user_notification_setting.get_api_map_by_user(user)

    if user.is_admin:
        response["is_admin"] = True

    bots = service.bot.get_api_list()
    branches_by_bot = service.bot_default_scope_branch.get_api_map_by_bot_uid()

    bots_with_branches = []
    for bot_dict in bots:
        bot_uid = bot_dict["uid"]
        bot_dict["default_scope_branches"] = branches_by_bot.get(bot_uid, [])
        bots_with_branches.append(bot_dict)

    return JsonResponse(content={"user": response, "bots": bots_with_branches})


@AppRouter.api.post("/auth/signout", tags=["Auth"], responses=OpenApiSchema(202).get())
def sign_out():
    is_secure = Env.PUBLIC_UI_URL.startswith("https://")
    response = JsonResponse(status_code=status.HTTP_202_ACCEPTED)
    response.delete_cookie(
        Env.REFRESH_TOKEN_NAME, domain=Env.DOMAIN if Env.DOMAIN else None, httponly=True, secure=is_secure
    )

    return response
