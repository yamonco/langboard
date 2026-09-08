class CardDeleteForbidden(PermissionError):
    """The authenticated actor is neither an administrator nor the original author."""

    code = "CARD_DELETE_AUTHOR_OR_ADMIN_REQUIRED"
