"""Known pre-save wiki concurrency conflict."""


class WikiContentConflict(ValueError):
    """The wiki changed after the caller reviewed it; no append was saved."""
