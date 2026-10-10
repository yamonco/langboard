from contextlib import contextmanager
from typing import Any, Generic, TypeVar, overload
from sqlalchemy import func
from ...helpers import InfraHelper
from ..db import BaseDbModel, DbSession, SoftDeleteModel, SqlBuilder
from ..types.ParamTypes import TBaseParam
from .BaseRepository import BaseRepository


_TModel = TypeVar("_TModel", bound=BaseDbModel)
_TParentModel = TypeVar("_TParentModel", bound=BaseDbModel)
_TModelParam = TypeVar("_TModelParam", bound=BaseDbModel)
_TParentModelParam = TypeVar("_TParentModelParam", bound=BaseDbModel)


class BaseOrderRepository(Generic[_TModel, _TParentModel], BaseRepository[_TModel]):
    _parent_model_cls: type[_TParentModel] | None = None

    @staticmethod
    def parent_model_cls() -> type[_TParentModel]:
        raise NotImplementedError("This class does not support base model operations.")

    @contextmanager
    def with_lock_for_update(
        self,
        models: BaseDbModel | TBaseParam | list[BaseDbModel | TBaseParam],
        *,
        model_cls: type[_TModelParam] | None = None,
        parent_model_cls: type[_TParentModelParam] | None = None,
    ):
        if not isinstance(models, list):
            models = [models]
        model_ids = [InfraHelper.convert_id(m) for m in models]
        model_class = self._get_model_cls(model_cls)
        parent_foreign_key_name = self._get_parent_foreign_key_name(parent_model_cls)
        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.select.table(model_class)
                .where(model_class.column(parent_foreign_key_name).in_(model_ids))
                .with_for_update()
            ).all()
            yield db

    def update_column_order(
        self,
        model: _TModel | TBaseParam,
        parent_model: _TParentModel | TBaseParam,
        old_order: int,
        new_order: int,
        *,
        model_cls: type[_TModelParam] | None = None,
        parent_model_cls: type[_TParentModelParam] | None = None,
    ):
        model_id = InfraHelper.convert_id(model)
        parent_id = InfraHelper.convert_id(parent_model)
        model_class = self._get_model_cls(model_cls)
        parent_foreign_key_name = self._get_parent_foreign_key_name(parent_model_cls)

        with DbSession.use(readonly=False) as db:
            update_query = SqlBuilder.update.table(model_class).where(
                model_class.column(parent_foreign_key_name) == parent_id
            )
            update_query = InfraHelper.set_order_in_column(update_query, model_class, old_order, new_order)
            db.exec(update_query)

            db.exec(
                SqlBuilder.update.table(model_class)
                .where(model_class.column("id") == model_id)
                .values({model_class.column("order"): new_order})
            )

    def update_row_order(
        self,
        model: _TModel | TBaseParam,
        old_parent_model: _TParentModel | TBaseParam,
        old_order: int,
        new_order: int,
        new_parent_model: _TParentModel | TBaseParam | None = None,
        *,
        preserve_shifted_updated_at: bool = False,
        model_cls: type[_TModelParam] | None = None,
        parent_model_cls: type[_TParentModelParam] | None = None,
    ):
        model_id = InfraHelper.convert_id(model)
        old_parent_id = InfraHelper.convert_id(old_parent_model)
        new_parent_id = InfraHelper.convert_id(new_parent_model) if new_parent_model else None
        model_class = self._get_model_cls(model_cls)
        parent_foreign_key_name = self._get_parent_foreign_key_name(parent_model_cls)

        with DbSession.use(readonly=False) as db:
            shared_update_query = SqlBuilder.update.table(model_class)
            if preserve_shifted_updated_at:
                # A neighbor shifting position was not edited by the user.
                shared_update_query = shared_update_query.values(
                    {model_class.column("updated_at"): model_class.column("updated_at")}
                )

            if new_parent_id:
                db.exec(
                    shared_update_query.values({model_class.column("order"): model_class.column("order") - 1}).where(
                        (model_class.column("order") >= old_order)
                        & (model_class.column(parent_foreign_key_name) == old_parent_id)
                    )
                )

                db.exec(
                    shared_update_query.values({model_class.column("order"): model_class.column("order") + 1}).where(
                        (model_class.column("order") >= new_order)
                        & (model_class.column(parent_foreign_key_name) == new_parent_id)
                    )
                )
            else:
                update_query = InfraHelper.set_order_in_column(shared_update_query, model_class, old_order, new_order)
                update_query = update_query.where(model_class.column(parent_foreign_key_name) == old_parent_id)
                db.exec(update_query)

            target_update = SqlBuilder.update.table(model_class).where(model_class.column("id") == model_id)
            if preserve_shifted_updated_at:
                target_update = target_update.values({model_class.column("updated_at"): model_class.column("updated_at")})
            db.exec(target_update.values({model_class.column("order"): new_order}))

    def get_next_order(
        self,
        parent_model: _TParentModel | TBaseParam,
        where_clauses: dict[str, Any] | None = None,
        *,
        model_cls: type[_TModelParam] | None = None,
        parent_model_cls: type[_TParentModelParam] | None = None,
    ) -> int:
        parent_id = InfraHelper.convert_id(parent_model)
        model_class = self._get_model_cls(model_cls)
        parent_foreign_key_name = self._get_parent_foreign_key_name(parent_model_cls)

        query = (
            SqlBuilder.select.columns(
                func.sum(model_class.column("order")),
                func.count(model_class.column("id")),
            )
            .where(model_class.column(parent_foreign_key_name) == parent_id)
            .group_by(model_class.column(parent_foreign_key_name))
            .limit(1)
        )
        if issubclass(model_class, SoftDeleteModel):
            query = query.where(model_class.column("deleted_at") == None)  # noqa
        if where_clauses:
            query = InfraHelper.where_recursive(query, model_class, **where_clauses)
        sum_all, count_all = None, None
        with DbSession.use(readonly=True) as target_db:
            result = target_db.exec(query)
            sum_all, count_all = result.first() or (None, None)

        if sum_all is None or count_all is None:
            sum_all = 0
            count_all = 0

        expected_sum = (count_all * (count_all - 1)) // 2
        if sum_all != expected_sum:
            new_order_cte = SqlBuilder.select.columns(
                model_class.column("id"),
                (func.row_number().over(order_by=model_class.column("order")) - 1).label("new_order"),
            ).where(model_class.column(parent_foreign_key_name) == parent_id)
            if where_clauses:
                new_order_cte = InfraHelper.where_recursive(new_order_cte, model_class, **where_clauses)
            new_order_cte = new_order_cte.cte("new_order_cte")

            update_query = (
                SqlBuilder.update.table(model_class)
                .filter(model_class.column("id") == new_order_cte.c.id)
                .values({model_class.column("order"): new_order_cte.c.new_order})
            )

            with DbSession.use(readonly=False) as target_db:
                target_db.exec(update_query)

        return count_all

    def reoder_after_delete(
        self,
        parent_model: _TParentModel | TBaseParam,
        model_order: int,
        *,
        model_cls: type[_TModelParam] | None = None,
        parent_model_cls: type[_TParentModelParam] | None = None,
    ):
        parent_model_id = InfraHelper.convert_id(parent_model)
        model_class = self._get_model_cls(model_cls)
        parent_foreign_key_name = self._get_parent_foreign_key_name(parent_model_cls)

        with DbSession.use(readonly=False) as db:
            # Lock
            db.exec(
                SqlBuilder.select.table(model_class)
                .where(model_class.column(parent_foreign_key_name) == parent_model_id)
                .with_for_update()
            ).all()

            db.exec(
                SqlBuilder.update.table(model_class)
                .values({model_class.column("order"): model_class.column("order") - 1})
                .where(
                    (model_class.column(parent_foreign_key_name) == parent_model_id)
                    & (model_class.column("order") > model_order)
                )
            )

    def _get_parent_foreign_key_name(
        self, parent_model_cls: type[_TParentModel] | type[_TParentModelParam] | None = None
    ) -> str:
        parent_model_cls = self._get_parent_model_cls(parent_model_cls)
        return f"{parent_model_cls.__tablename__}_id"

    @overload
    def _get_parent_model_cls(self, parent_model_cls: type[_TParentModel] | None = None) -> type[_TParentModel]: ...
    @overload
    def _get_parent_model_cls(
        self, parent_model_cls: type[_TParentModelParam] | None = None
    ) -> type[_TParentModelParam]: ...
    def _get_parent_model_cls(
        self, parent_model_cls: type[_TParentModel] | type[_TParentModelParam] | None = None
    ) -> type[_TParentModel] | type[_TParentModelParam]:
        if parent_model_cls:
            return parent_model_cls
        if not self._parent_model_cls:
            self._parent_model_cls = self.parent_model_cls()
        return self._parent_model_cls
