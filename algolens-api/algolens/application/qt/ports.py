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


class DeskRiskUnavailable(Exception):
    """GetDeskRisk failed (the engine is down, timed out, refused the call).

    Not an HTTP error by itself: the desk state shows it, and the approval
    gate refuses while it lasts (contract C9: fail closed)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


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
        """One transaction under the day lock: refuse a published day or an
        open publish (DeskConflict), lock the proposal, plan the changes from
        the current quantities (the plan may raise DeskStaleError), upsert
        them and insert the save row."""

    def proposal_rows(self, portfolio_id: str, day: date) -> Sequence[Row]:
        """Every qt_proposal row of the day: strategy_name, symbol, quantity."""

    def symbol_choices(self, asset_class: str) -> Sequence[Row]:
        ...

    def get_command(self, command_id: int) -> Row | None:
        ...

    def commands(self, portfolio_id: str, day: date) -> Sequence[Row]:
        ...

    def insert_publish(
        self, portfolio_id: str, day: date, requested_by: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Row:
        """Under the day lock: refuse a published day or an open publish.
        `payload` names a C10 flow."""

    def approve_proposal(
        self,
        portfolio_id: str,
        day: date,
        plan: Callable[[Mapping[str, Any]], list[dict[str, Any]]],
        reason: str,
        requested_by: str,
    ) -> tuple[Row, Row]:
        """C10: save_proposal's save and a publish row {"flow": "auto",
        "after": <save id>} in one transaction. Returns (save, publish)."""

    def decide_override(
        self,
        request_id: int,
        approved: bool,
        approver: str,
        approver_role: str,
        reason: str | None,
    ) -> tuple[Row, Row | None]:
        """C10: insert_decision and, on an approval, a publish row
        {"flow": "override_b", "after": <decision id>} requested by the QT who
        asked, in one transaction. Returns (decision, publish or None)."""

    def insert_send(self, portfolio_id: str, day: date, requested_by: str) -> Row:
        """D-66: under the day lock, refuse (DeskConflict) unless the day is
        published and unsent and nothing is open; insert {"flow": "send"}."""

    def insert_rescind(
        self, portfolio_id: str, day: date, requested_by: str, is_approver: bool = False
    ) -> Row:
        """Under the day lock: refuse (DeskConflict) unless live_run_metadata
        says the day is published by the desk (publish_source 'desk') and not
        sent, and while a publish or a rescind is open (C8). A day an override
        published only the VP or the President (`is_approver`) takes back."""

    def insert_override_request(
        self, portfolio_id: str, day: date, requested_by: str, reason: str
    ) -> Row:
        """Under the day lock: refuse a published day, an open publish or an
        open request; insert with the proposal snapshot and its hash (C1)."""

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
        """Under the day lock: refuse (DeskConflict) a decided request, one
        not done, a published day, and an approval whose snapshot no longer
        matches the proposal; insert."""

    def publish_state(self, portfolio_id: str, day: date) -> Row | None:
        """published_by, published_at, publish_source and sent_at of a
        published day (the last two NULL before migration 026), or None."""

    def send_tracking(self) -> bool:
        """Whether live_run_metadata has 026's publish_source and sent_at."""


class SettingsRepositoryPort(Protocol):
    def latest_settings_used(self, portfolio_id: str) -> Row | None:
        """{date, settings_used} of the newest live run that reported them."""

    def config_versions(self, portfolio_id: str, limit: int = 50) -> Sequence[Row]:
        """trading.strategy_config rows, newest version first."""

    def config_version(self, portfolio_id: str, version: int) -> Row | None:
        ...

    def settings_locks(self) -> Sequence[Row] | None:
        """D-14: trading.desk_settings_locks as [{path, reason, locked_by, locked_at}], or None
        while the table is absent (AlgoLens migration 004)."""

    def set_settings_lock(self, path: Sequence[str], locked: bool, reason: str, by: str) -> None:
        """Lock or unlock one setting and log it (trading.desk_settings_lock_log), in one
        transaction."""

    def insert_config_version(
        self,
        portfolio_id: str,
        overrides: Mapping[str, Any],
        reason: str,
        created_by: str,
        expected_active_version: int | None,
    ) -> Row:
        """One transaction: refuse (DeskConflict) if the active version is no
        longer `expected_active_version`, deactivate it, insert max+1 active."""


class DeskAgentPort(Protocol):
    """The engine's desk service over gRPC (infrastructure/qt/desk_client.py).

    Commands are best effort: they never raise. Each returns a short outcome
    for the log ("ACCEPTED", "unavailable", ...). The command row is the
    record; when a call fails the row stays pending and the engine re-drives
    it (contract section 6).

    get_desk_risk is a read (contract C9): it returns the report or raises
    DeskRiskUnavailable.
    """

    def run_desk(self, command: Row) -> str:
        ...

    def request_override(self, command: Row) -> str:
        ...

    def record_decision(self, decision: Row, token: str) -> str:
        ...

    def publish(self, command: Row) -> str:
        ...

    def rescind(self, command: Row) -> str:
        ...

    def check_settings(self, portfolio_id: str, overrides: Mapping[str, Any]) -> tuple[bool, str]:
        """HD D-17: whether a live run would accept `overrides` as the portfolio's desk settings
        (CheckSettings, desk.proto 1.7.0): (ok, the refusal a run would give). Raises
        DeskRiskUnavailable when the engine cannot be asked."""
        ...

    def get_run_status(self, portfolio_id: str, day: date) -> dict[str, Any]:
        """D-56: the model run's state for the book and day (GetRunStatus): state
        ('not_started', 'running', 'succeeded', 'refused', 'failed'), startedAt, finishedAt
        (ISO or None) and message. Raises DeskRiskUnavailable when it cannot be read."""
        ...

    def get_desk_risk(self, portfolio_id: str, day: date) -> dict[str, Any]:
        """The risk report of the day's qt book (GetDeskRisk, desk.proto
        1.3.0, checks since 1.4.0), JSON-friendly with camelCase keys: state ('no_book', 'model',
        'desk', 'override', 'incomplete'), auditId, withinLimits, approvedOverride,
        breaches, m, bindingTerm, overLimitAfterRounding, overLimitByHold,
        refused, symbols, grossLeverage, netLeverage, marginCushion,
        equityToMargin (None when not recorded), limits and (1.4.0) checks:
        {term, label, value, max, unit, status, detail}, every limit with its
        reading and max as trade-ngin reports it, and (1.6.0) blocksPublish
        and blockers: decision 5's publish gate as the engine decides it; state
        'incomplete' is a qt book a desk or override run did not finish. Raises
        DeskRiskUnavailable when the call fails."""
