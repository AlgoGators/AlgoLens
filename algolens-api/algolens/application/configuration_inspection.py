"""Read-only configuration inspection use case and fixed public outcomes."""

from datetime import datetime, timezone
from typing import Protocol

from algolens.domain.portfolio.portfolio_assignment import normalize_portfolio_id


class InspectionError(Exception):
    def __init__(self, code, status):
        self.code = code
        self.status = status
        super().__init__(code)


class InspectionReader(Protocol):
    def read(self, registry_id: str, portfolio_id: str, read_at: datetime) -> tuple[str, object, str]: ...


class ConfigurationInspectionService:
    def __init__(self, reader: InspectionReader, clock=None):
        self.reader = reader
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def inspect(self, registry_id, requested_book):
        book = normalize_portfolio_id(requested_book)
        now = self.clock().astimezone(timezone.utc)
        status, payload, selected_book = self.reader.read(registry_id, book, now)
        return {
            "api_version": 1,
            "scope": {"registry_id": registry_id, "portfolio_id": selected_book},
            "read_at": now.isoformat().replace("+00:00", "Z"),
            "status": status,
            "reason": "none" if status == "available" else
                      payload["reason"] if type(payload) is dict else payload,
            "publication": payload if type(payload) is dict else None,
        }
