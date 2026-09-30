from secrets import token_urlsafe
from fastapi import status
from langboard_shared.core.caching import Cache
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.core.security import AuthSecurity, OidcClient
from langboard_shared.core.types import SafeDateTime
from langboard_shared.core.utils.String import generate_random_string
from langboard_shared.domain.models import IdentityProvider, User
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.security import Auth


@AppRouter.api.get(
    "/auth/oidc/login",
    tags=["Auth.OIDC"],
    responses=OpenApiSchema().suc({"authorize_url": "string", "state": "string"}).get(),
)
def oidc_login(redirect: str | None = None) -> JsonResponse:
    if not OidcClient.is_enabled():
        raise ApiException.NotFound_404()

    state = token_urlsafe(24)
    nonce = token_urlsafe(24)
    cache_payload = {"nonce": nonce}
    redirect = str(redirect or "").strip()
    if redirect:
        cache_payload["redirect"] = redirect
    Cache.set(f"oidc-state:{state}", cache_payload, 60 * 10)

    authorize_url = OidcClient.build_authorize_url(state=state, nonce=nonce)
    return JsonResponse(content={"authorize_url": authorize_url, "state": state})


@AppRouter.api.get(
    "/auth/oidc/link/login",
    tags=["Auth.OIDC"],
    responses=OpenApiSchema().suc({"authorize_url": "string", "state": "string"}).get(),
)
@AuthFilter.add("user")
def oidc_link_login(user: User = Auth.scope("user")) -> JsonResponse:
    """Start a dual-authenticated link to the currently signed-in Langboard account."""
    if not OidcClient.is_enabled():
        raise ApiException.NotFound_404()
    if not user.activated_at or user.deleted_at:
        raise ApiException.Unauthorized_401(ApiErrorCode.AU1004)

    state = token_urlsafe(24)
    nonce = token_urlsafe(24)
    Cache.set(
        f"oidc-state:{state}",
        {"nonce": nonce, "link_user_id": str(user.id), "redirect": "/account/profile"},
        60 * 10,
    )
    return JsonResponse(content={"authorize_url": OidcClient.build_authorize_url(state=state, nonce=nonce), "state": state})


@AppRouter.api.get(
    "/auth/oidc/callback",
    tags=["Auth.OIDC"],
    responses=(
        OpenApiSchema().suc({"access_token": "string", "redirect?": "string"}).err(401, ApiErrorCode.AU1004).get()
    ),
)
def oidc_callback(
    code: str | None = None,
    state: str | None = None,
    service: DomainService = DomainService.scope(),
) -> JsonResponse:
    if not OidcClient.is_enabled():
        raise ApiException.NotFound_404()

    if not code or not state:
        raise ApiException.Unauthorized_401(ApiErrorCode.AU1004)

    cached_state = Cache.get(f"oidc-state:{state}")
    Cache.delete(f"oidc-state:{state}")
    if not isinstance(cached_state, dict):
        raise ApiException.Unauthorized_401(ApiErrorCode.AU1004)

    nonce = str(cached_state.get("nonce", ""))
    redirect = str(cached_state.get("redirect", "")).strip() or None
    link_user_id = str(cached_state.get("link_user_id", "")).strip()

    try:
        token_payload = OidcClient.exchange_code(code)
        id_token = str(token_payload.get("id_token", "")).strip()
        if not id_token:
            raise RuntimeError("id_token is missing")

        claims = OidcClient.validate_id_token(id_token, nonce=nonce)
        subject = str(claims.get("sub", "")).strip()
        issuer = str(claims.get("iss", Env.OIDC_ISSUER)).strip().rstrip("/")
        if not subject or not issuer:
            raise RuntimeError("OIDC subject or issuer is missing")

        claim_name = Env.OIDC_EMAIL_CLAIM or "email"
        email = claims.get(claim_name, claims.get("email", ""))
        if isinstance(email, list):
            email = email[0] if email else ""
        email = str(email).strip().lower()

        if not email:
            access_token = str(token_payload.get("access_token", "")).strip()
            if access_token:
                userinfo = OidcClient.fetch_userinfo(access_token)
                email = userinfo.get(claim_name, userinfo.get("email", ""))
                if isinstance(email, list):
                    email = email[0] if email else ""
                email = str(email).strip().lower()

        if not email:
            raise RuntimeError("OIDC email claim is missing")

        firstname = str(claims.get("given_name", "")).strip()
        lastname = str(claims.get("family_name", "")).strip()
        fullname = str(claims.get("name", "")).strip()
        if fullname and not firstname:
            firstname = fullname.split(" ", maxsplit=1)[0]
        if fullname and not lastname and " " in fullname:
            lastname = fullname.split(" ", maxsplit=1)[1]

        firstname = firstname or "OIDC"
        lastname = lastname or "User"

        user = service.identity_link.get_user_by_provider_external_id(
            IdentityProvider.Oidc,
            subject,
            issuer,
        )
        if link_user_id:
            linking_user = service.user.get_by_id_like(link_user_id)
            if not linking_user or not linking_user.activated_at or linking_user.deleted_at:
                raise RuntimeError("Langboard account is no longer active")
            if user and user.id != linking_user.id:
                raise RuntimeError("OIDC identity belongs to another Langboard account")
            current_link = service.identity_link.get_by_user_provider(linking_user, IdentityProvider.Oidc)
            if current_link and (current_link.external_id != subject or current_link.issuer != issuer):
                raise RuntimeError("Langboard account has a different OIDC identity")
            user = linking_user
        elif not user and Env.OIDC_AUTO_LINK_BY_EMAIL:
            user, _ = service.user.get_by_email(email)
        if not user:
            existing_user, _ = service.user.get_by_email(email)
            if existing_user or not Env.OIDC_AUTO_PROVISION:
                raise RuntimeError("OIDC identity requires an explicit account link")
            now = SafeDateTime.now()
            form = {
                "firstname": firstname,
                "lastname": lastname,
                "email": email,
                "password": generate_random_string(48),
                "industry": "OIDC",
                "purpose": "SSO",
                "affiliation": None,
                "position": None,
                "created_at": now,
                "updated_at": now,
                "activated_at": now,
            }
            user, _ = service.user.create(form)
        else:
            if not user.activated_at or user.deleted_at:
                raise RuntimeError("Langboard account is not active")
            update_form = {}
            if not link_user_id and firstname and firstname != user.firstname:
                update_form["firstname"] = firstname
            if not link_user_id and lastname and lastname != user.lastname:
                update_form["lastname"] = lastname
            if update_form:
                service.user.update(user, update_form)

        service.identity_link.upsert_user_link(
            user=user,
            provider=IdentityProvider.Oidc,
            external_id=subject,
            issuer=issuer,
            email=email,
        )

        access_token, refresh_token = AuthSecurity.authenticate(user.id)

        response = JsonResponse(content={"access_token": access_token, "redirect": redirect})
        response.set_cookie(
            Env.REFRESH_TOKEN_NAME,
            refresh_token,
            max_age=Env.JWT_RT_EXPIRATION * 60 * 60 * 24,
            domain=Env.DOMAIN if Env.DOMAIN else None,
            httponly=True,
            secure=Env.PUBLIC_UI_URL.startswith("https"),
        )
        return response
    except Exception:
        raise ApiException.Unauthorized_401(ApiErrorCode.AU1004)


@AppRouter.api.post("/auth/oidc/logout", tags=["Auth.OIDC"], responses=OpenApiSchema(202).get())
def oidc_logout() -> JsonResponse:
    response = JsonResponse(status_code=status.HTTP_202_ACCEPTED)
    response.delete_cookie(
        Env.REFRESH_TOKEN_NAME,
        domain=Env.DOMAIN if Env.DOMAIN else None,
        httponly=True,
        secure=Env.PUBLIC_UI_URL.startswith("https"),
    )
    return response
