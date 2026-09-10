from typing import Generic, TypeVar
from .....core.db import DbSession, SqlBuilder
from .....core.domain import BaseRepository
from .....domain.models.bases import BaseRoleModel


_TRoleModel = TypeVar("_TRoleModel", bound=BaseRoleModel)


class BaseRoleRepository(Generic[_TRoleModel], BaseRepository[_TRoleModel]):
    def get_list(self, **kwargs) -> list[_TRoleModel]:
        """Get roles by filtering with the given parameters.

        If the given parameters are not in the model's fields or are `None`, they will be ignored.

        If no parameters are given, all roles will be returned.
        """
        model_cls = self._get_model_cls()
        query = SqlBuilder.select.table(model_cls)

        for arg, value in kwargs.items():
            if arg in model_cls.model_fields and value is not None:
                if isinstance(value, list):
                    query = query.where(getattr(model_cls, arg).in_(value))
                else:
                    query = query.where(getattr(model_cls, arg) == value)

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            records = result.all()
        return records

    def get_one(self, **kwargs) -> _TRoleModel | None:
        """Get a role by filtering with the given parameters.

        If the given parameters are not in the model's fields or are `None`, they will be ignored.

        If no parameters are given, one role is returned without a guaranteed order.
        """
        consistent = bool(kwargs.pop("consistent", False))
        model_cls = self._get_model_cls()
        query = SqlBuilder.select.table(model_cls)

        for arg, value in kwargs.items():
            if arg in model_cls.model_fields and value is not None:
                query = query.where(getattr(model_cls, arg) == value)

        record = None
        with DbSession.use(readonly=not consistent) as db:
            result = db.exec(query.limit(1))
            record = result.first()
        return record

    def grant(self, **kwargs) -> _TRoleModel:
        """Grant actions to the role.

        If `user_id` aren't provided, a `ValueError` will be raised.

        After the method is executed, db must be committed to save the changes.
        """
        role = self._get_or_create_role(**kwargs)
        if not role.is_new():
            role.actions = kwargs.get("actions", role.actions)

        with DbSession.use(readonly=False) as db:
            if role.is_new():
                db.insert(role)
            else:
                db.update(role)

        return role

    def grant_all(self, **kwargs) -> _TRoleModel:
        """Grant all actions to the role. :meth:`BaseRoleModel.set_all_actions` will be called.

        If `user_id` aren't provided, a `ValueError` will be raised.

        After the method is executed, db must be committed to save the changes.
        """
        role = self._get_or_create_role(**kwargs)
        role.set_all_actions()

        with DbSession.use(readonly=False) as db:
            if role.is_new():
                db.insert(role)
            else:
                db.update(role)

        return role

    def grant_default(self, **kwargs) -> _TRoleModel:
        """Grant default actions to the role. :meth:`BaseRoleModel.set_default_actions` will be called.

        If `user_id` aren't provided, a `ValueError` will be raised.

        After the method is executed, db must be committed to save the changes.
        """
        role = self._get_or_create_role(**kwargs)
        role.set_default_actions()

        with DbSession.use(readonly=False) as db:
            if role.is_new():
                db.insert(role)
            else:
                db.update(role)

        return role

    def withdraw(self, **kwargs) -> _TRoleModel | None:
        """Withdraw the role.

        If `user_id` aren't provided, a `ValueError` will be raised.

        After the method is executed, db must be committed to save the changes.
        """
        role = self._get_or_create_role(**kwargs)
        if role.is_new():
            return None

        with DbSession.use(readonly=False) as db:
            db.delete(role)

        return role

    def _get_or_create_role(self, **kwargs) -> _TRoleModel:
        model_cls = self._get_model_cls()
        if kwargs.get("user_id", None) is not None:
            target_id_column = model_cls.user_id
            target_id = kwargs["user_id"]
        else:
            raise ValueError("user_id must be provided.")

        query = SqlBuilder.select.table(model_cls).where(target_id_column == target_id)
        filterable_columns = model_cls.get_filterable_columns()
        for arg, value in kwargs.items():
            if arg in filterable_columns and value is not None:
                query = query.where(model_cls.column(arg) == value)

        role = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(query.limit(1))
            role = result.first()
        return model_cls(**kwargs) if not role else role
