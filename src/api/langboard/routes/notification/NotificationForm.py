from langboard_shared.core.schema import Pagination


class NotificationForm(Pagination):
    time_range: str  # "3d", "7d", "1m", "all"
    limit: int = 20
    unread_only: bool = False
