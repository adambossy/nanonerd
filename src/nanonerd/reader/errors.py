class ReaderError(Exception):
    """Root of the reader's error taxonomy."""


class FetchError(ReaderError):
    """A URL could not be fetched (network, policy, or HTTP failure)."""


class RenderError(ReaderError):
    """A page could not be rendered in the browser."""


class ExtractionError(ReaderError):
    """No readable article content could be produced for a URL."""
