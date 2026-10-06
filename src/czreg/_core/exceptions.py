class CzregError(Exception):
    """Base class for every error this library raises."""


class InvalidIco(CzregError, ValueError):
    """The IČO failed the local validation. No request was sent."""


class CursorExpired(CzregError):
    """ARES no longer has the notification batches after this cursor (it keeps about four weeks):
    the changes in between are lost. Fetch the subjects again and start with a new cursor."""


class SourceError(CzregError):
    """The source replied with an error.

    `source` says which one (`"ares"`, `"isir"`, ...); `code` is the source's own error code.
    """

    def __init__(self, message: str, *, source: str, code: str | None = None):
        self.source: str = source
        self.code: str | None = code
        super().__init__(message)


class NotFound(SourceError):
    """The source does not know the subject."""


class InvalidRequest(SourceError): ...


class SourceUnavailable(SourceError):
    """The source failed on its side, and the retries did not help."""
