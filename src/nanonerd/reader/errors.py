class ReaderError(Exception):
    """Root of the reader's error taxonomy."""


class FetchError(ReaderError):
    """A URL could not be fetched (network, policy, or HTTP failure).

    The fidelity judge needs the status code and body of a refused fetch to
    tell a bot wall apart from an ordinary outage, so they ride along here.
    """

    def __init__(
        self, message: str, *, status_code: int | None = None, body: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class RenderError(ReaderError):
    """A page could not be rendered in the browser."""


class ExtractionError(ReaderError):
    """No readable article content could be produced for a URL."""
