"""Typed, safe errors at the QT workflow boundary."""

_STATUS_BY_CODE = {
    "invalid_qt_payload": 400,
    "invalid_qt_exact": 400,
    "invalid_qt_key": 400,
    "invalid_qt_action": 400,
    "authorization_changed": 403,
    "approval_identity_unmapped": 403,
    "not_found": 404,
    "provenance_unresolved": 409,
    "draft_stale": 409,
    "draft_identity_unresolved": 409,
    "preview_unavailable": 409,
    "preview_stale": 409,
    "preview_mismatch": 409,
    "preview_required": 409,
    "preview_consumed": 409,
    "decision_not_publishable": 409,
    "idempotency_conflict": 409,
    "workflow_unavailable": 503,
}


class QtWorkflowError(Exception):
    def __init__(self, code: str, message: str = "QT workflow request rejected", http_status: int | None = None, retryable: bool = False) -> None:
        if code not in _STATUS_BY_CODE:
            raise ValueError("unknown_qt_error_code")
        expected = _STATUS_BY_CODE[code]
        if http_status is not None and http_status != expected:
            raise ValueError("qt_error_status_mismatch")
        if not isinstance(message, str) or not message or len(message) > 512 or type(retryable) is not bool:
            raise ValueError("invalid_qt_error_message")
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = expected
        self.retryable = retryable

    def __str__(self) -> str:
        return self.message

    def to_wire(self, *, book_id: str | None = None, preview_id: str | None = None) -> dict[str, object]:
        return {
            "schema_version": "qt-workflow/v1",
            "error": {"code": self.code, "message": self.message, "retryable": self.retryable},
            "book_id": book_id,
            "preview_id": preview_id,
        }
