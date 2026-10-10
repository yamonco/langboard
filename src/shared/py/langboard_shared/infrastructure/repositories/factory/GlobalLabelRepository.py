from ....core.domain import BaseRepository
from ....domain.models import GlobalLabel


class GlobalLabelRepository(BaseRepository[GlobalLabel]):
    @staticmethod
    def model_cls():
        return GlobalLabel

    @staticmethod
    def name() -> str:
        return "global_label"
