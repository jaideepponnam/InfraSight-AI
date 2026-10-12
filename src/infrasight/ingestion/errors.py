class SourceError(Exception):
    """Permanent extraction failure; error messages are not persisted verbatim."""


class TransientSourceError(SourceError):
    """An adapter may retry this failure at the same cursor."""


class SourceBusyError(Exception):
    """Another database session owns this source."""


class SourceLockLostError(Exception):
    """The dedicated lock session no longer owns its source lock."""
