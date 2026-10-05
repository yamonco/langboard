from typing import Any, Generic, TypeVar
from ..core.db import DbSession, SqlBuilder
from ..domain.models.bases import BaseRoleModel
from ..filter.RoleFilter import _RoleFinderFunc


_TRoleModel = TypeVar("_TRoleModel", bound=BaseRoleModel)


class RoleSecurity(Generic[_TRoleModel]):
    def __init__(self, model_class: type[_TRoleModel]):
        self._model_class = model_class

    def is_authorized(
        self,
        user_id: int,
        path_params: dict[str, Any],
        actions: list[str],
        role_finder: _RoleFinderFunc[_TRoleModel],
    ) -> bool:
        query = SqlBuilder.select.table(self._model_class).where(self._model_class.column("user_id") == user_id)

        query = role_finder(query, path_params, user_id)

        role = None
        # Authorization must observe committed revocations without replica lag.
        with DbSession.use(readonly=False) as db:
            result = db.exec(query.limit(1))
            role = result.first()

        if not role or not role.actions:
            return False
        return role.is_granted(actions)
