from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....domain.models import ApiComfortTool


class ApiComfortToolRepository(BaseRepository[ApiComfortTool]):
    @staticmethod
    def model_cls():
        return ApiComfortTool

    @staticmethod
    def name() -> str:
        return "api_comfort_tool"

    def get_all(self) -> list[ApiComfortTool]:
        with DbSession.use(readonly=True) as db:
            result = db.exec(SqlBuilder.select.table(ApiComfortTool).order_by(ApiComfortTool.column("name").asc()))
            return result.all()

    def get_by_name(self, name: str) -> ApiComfortTool | None:
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ApiComfortTool).where(ApiComfortTool.column("name") == name).limit(1)
            )
            return result.first()
