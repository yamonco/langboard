from langboard_shared.core.security import AuthSecurity
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env


def main() -> None:
    user, _subemail = DomainService().user.get_by_email(Env.ADMIN_EMAIL)
    if not user or not user.activated_at:
        raise RuntimeError("The configured administrator must be activated")

    access_token, _refresh_token = AuthSecurity.authenticate(user.id)
    print(access_token)
    print(user.get_uid())


if __name__ == "__main__":
    main()
