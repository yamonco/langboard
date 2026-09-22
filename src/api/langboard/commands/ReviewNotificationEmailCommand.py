from json import dumps
from langboard_shared.core.bootstrap import BaseCommand, BaseCommandOptions
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.services import DomainService
from pydantic import Field


class ReviewNotificationEmailCommandOptions(BaseCommandOptions):
    action: str = Field(default="list", description="list, retry, confirm-sent, or close")
    id: int = Field(default=0, description="Numeric email delivery ID for a resolution")
    ticket: str = Field(default="", description="Operator decision ticket for a resolution")
    acknowledge_uncertain: bool = Field(
        default=False, description="Acknowledge that an uncertain email may already have been sent"
    )
    limit: int = Field(default=20, description="Maximum review rows to list (1-100)")


class ReviewNotificationEmailCommand(BaseCommand):
    @staticmethod
    def is_only_in_dev() -> bool:
        return False

    @property
    def option_class(self) -> type[ReviewNotificationEmailCommandOptions]:
        return ReviewNotificationEmailCommandOptions

    @property
    def command(self) -> str:
        return "notification:email:review"

    @property
    def positional_name(self) -> str:
        return ""

    @property
    def description(self) -> str:
        return "Review and resolve failed or uncertain notification emails"

    @property
    def choices(self) -> list[str] | None:
        return None

    @property
    def store_type(self) -> type[bool] | type[str]:
        return bool

    def execute(self, options: ReviewNotificationEmailCommandOptions) -> None:
        try:
            self._execute(options)
        except ValueError as error:
            raise SystemExit(str(error)) from None

    def _execute(self, options: ReviewNotificationEmailCommandOptions) -> None:
        if options.action not in ("list", "retry", "confirm-sent", "close"):
            raise ValueError("Action must be list, retry, confirm-sent, or close")
        if options.action != "list" and options.id <= 0:
            raise ValueError("A positive delivery ID is required")

        with DomainService.use() as service:
            if options.action == "list":
                for delivery in service.notification.get_email_deliveries_for_review(options.limit):
                    print(
                        dumps(
                            {
                                "id": int(delivery.id),
                                "recipient_email": delivery.recipient_email,
                                "status": delivery.status.value,
                                "created_at": str(delivery.created_at),
                                "failure_reason": delivery.failure_reason,
                                "review_note": delivery.review_note,
                            }
                        )
                    )
                return

            resolved = service.notification.resolve_email_delivery_review(
                SnowflakeID(options.id),
                options.action,
                options.ticket,
                options.acknowledge_uncertain,
            )
            if not resolved:
                raise ValueError("Delivery is no longer awaiting review")
            print(f"Resolved notification email delivery {options.id} with action {options.action}")
