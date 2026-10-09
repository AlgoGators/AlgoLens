"""Ports of the QT desk use cases."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any, Protocol

from algolens.application.shared.errors import ApplicationError, NotFoundError

Row = Mapping[str, Any]


class DeskNotSeeded(ApplicationError):
    """The day's model run has not seeded the qt_proposal book (ruling 14). HTTP 409."""


class DeskConflict(ApplicationError):
    """The request conflicts with the command log's state. HTTP 409."""


class DeskForbidden(ApplicationError):
    """The user may not do this (not an approver, own request, ...). HTTP 403."""


class DeskNotFound(NotFoundError):
    """No such command, request or portfolio. HTTP 404."""


class DeskGone(ApplicationError):
    """The approval link has expired. HTTP 410."""


class DeskRepositoryPort(Protocol):
    def desk_date(self, portfolio_id: str) -> date | None:
        """The latest model-run date of the portfolio (system or qt_proposal)."""

    def book_rows(self, portfolio_id: str, day: date, book: str) -> Sequence[Row]:
        ...

    def save_proposal(
        self,
        portfolio_id: str,
        day: date,
        plan: Callable[[Mapping[str, Any]], list[dict[str, Any]]],
        reason: str,
        requested_by: str,
    ) -> Row:
        """One transaction: lock the proposal, plan the changes from the
        current quantities, upsert them and insert the save row."""

    def symbol_choices(self, asset_class: str) -> Sequence[Row]:
        ...

    def get_command(self, command_id: int) -> Row | None:
        ...

    def commands(self, portfolio_id: str, day: date) -> Sequence[Row]:
        ...

    def insert_command(
        self,
        portfolio_id: str,
        day: date,
        kind: str,
        requested_by: str,
        reason: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Row:
        ...

    def find_request_by_token_hash(self, token_hash: str) -> Row | None:
        ...

    def insert_decision(
        self,
        request_id: int,
        approved: bool,
        approver: str,
        approver_role: str,
        reason: str | None,
    ) -> Row:
        """Lock the request, refuse a second decision (DeskConflict), insert."""

    def publish_state(self, portfolio_id: str, day: date) -> Row | None:
        ...


class DeskAgentPort(Protocol):
    """The engine's desk-agent (gRPC). Best effort: never raises.

    Each call returns a short outcome for the log ("ACCEPTED", "unavailable",
    ...). The command row is the record; when a call fails the row stays
    pending and the engine re-drives it (contract section 6).
    """

    def run_desk(self, command: Row) -> str:
        ...

    def request_override(self, command: Row) -> str:
        ...

    def record_decision(self, decision: Row, token: str) -> str:
        ...

    def publish(self, command: Row) -> str:
        ...
