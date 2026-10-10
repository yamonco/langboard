from typing import Literal
from sqlalchemy import func
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TCheckitemParam
from ....domain.models import Checkitem, CheckitemTimerRecord
from ....helpers import InfraHelper


class CheckitemTimerRecordRepository(BaseRepository[CheckitemTimerRecord]):
    @staticmethod
    def model_cls():
        return CheckitemTimerRecord

    @staticmethod
    def name() -> str:
        return "checkitem_timer_record"

    def get_by_checkitem_and_arc_type(self, checkitem: TCheckitemParam, arc_type: Literal["first", "last"]):
        checkitem_id = InfraHelper.convert_id(checkitem)
        order_by = (
            CheckitemTimerRecord.column("created_at").asc()
            if arc_type == "first"
            else CheckitemTimerRecord.column("created_at").desc()
        )

        record = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(CheckitemTimerRecord)
                .where(CheckitemTimerRecord.column("checkitem_id") == checkitem_id)
                .order_by(order_by)
                .limit(1)
            )
            record = result.first()
        return record

    def get_arc_map_by_checkitems(
        self, checkitems: list[Checkitem]
    ) -> dict[int, dict[Literal["first", "last"], CheckitemTimerRecord]]:
        checkitem_ids = [checkitem.id for checkitem in checkitems]
        if not checkitem_ids:
            return {}

        first_ids = self.__get_arc_ids(checkitem_ids, "first")
        last_ids = self.__get_arc_ids(checkitem_ids, "last")
        timer_ids = [*first_ids, *last_ids]
        if not timer_ids:
            return {}

        with DbSession.use(readonly=True) as db:
            records = db.exec(
                SqlBuilder.select.table(CheckitemTimerRecord).where(CheckitemTimerRecord.column("id").in_(timer_ids))
            ).all()

        timers_by_id = {timer.id: timer for timer in records}
        result: dict[int, dict[Literal["first", "last"], CheckitemTimerRecord]] = {}
        for timer_id in first_ids:
            timer = timers_by_id.get(timer_id)
            if timer:
                result.setdefault(timer.checkitem_id, {})["first"] = timer
        for timer_id in last_ids:
            timer = timers_by_id.get(timer_id)
            if timer:
                result.setdefault(timer.checkitem_id, {})["last"] = timer
        return result

    def __get_arc_ids(
        self, checkitem_ids: list[SnowflakeID] | list[int], arc_type: Literal["first", "last"]
    ) -> list[SnowflakeID]:
        order_by = (
            (CheckitemTimerRecord.column("created_at").asc(), CheckitemTimerRecord.column("id").asc())
            if arc_type == "first"
            else (CheckitemTimerRecord.column("created_at").desc(), CheckitemTimerRecord.column("id").desc())
        )
        ranked = (
            SqlBuilder.select.columns(
                CheckitemTimerRecord.column("id"),
                func.row_number()
                .over(partition_by=CheckitemTimerRecord.column("checkitem_id"), order_by=order_by)
                .label("row_number"),
            )
            .where(CheckitemTimerRecord.column("checkitem_id").in_(checkitem_ids))
            .subquery()
        )

        with DbSession.use(readonly=True) as db:
            rows = db.exec(SqlBuilder.select.column(ranked.c.id).where(ranked.c.row_number == 1)).all()
        return [SnowflakeID(row) for row in rows]
