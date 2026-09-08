class CardDeleteForbidden(PermissionError):
    """The authenticated actor is not the card's immutable original author."""

    code = "CARD_DELETE_ORIGINAL_AUTHOR_REQUIRED"
