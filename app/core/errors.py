"""Error types.

DocumentError and its subclasses signal a problem with the *incoming document*
(the caller's fault). The API layer turns these into 4xx responses and they do
not count as pipeline failures. Transient / LLM errors are defined near the LLM
client in a later step.
"""


class DocumentError(Exception):
    """Base: the submitted document cannot be processed as-is."""


class UnsupportedDocumentError(DocumentError):
    """Not a PDF (or not a format we handle)."""


class CorruptDocumentError(DocumentError):
    """Bytes claim to be a PDF but cannot be parsed."""


class EncryptedDocumentError(DocumentError):
    """PDF is password-protected and cannot be opened."""
