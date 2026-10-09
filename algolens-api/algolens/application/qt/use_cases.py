"""QT desk use cases (contract sections 4, 6 and 7).

AlgoLens inserts a trading.position_overrides row, then calls the engine's
desk service with its id. The call is a fast path only: if it fails the row
stays pending and the engine re-drives it, so a gRPC failure never fails the
user's action.
"""

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from algolens.application.qt.ports import (
    DeskAgentPort,
    DeskForbidden,
    DeskGone,
    DeskNotFound,
    DeskNotSeeded,
    DeskRepositoryPort,
)
from algolens.domain.portfolio.registry import desk_edit_allowed
from algolens.domain.qt.desk import (
    DONE,
    OPEN_STATUSES,
    OVERRIDE_DECISION,
    OVERRIDE_REQUEST,
    PUBLISH,
    SAVE,
    DeskRuleError,
    as_number,
    asked_vs_given,
    open_override_request,
    plan_desk_edit,
    proposal_snapshot,
    request_matches,
    require_reason,
    snapshot_sha256,
    three_books,
    token_hash,
)

logger = logging.getLogger(__name__)

# Columns of a command row shown to the browser. token_hash never leaves.
COMMAND_FIELDS = (
    "id",
    "portfolio_id",
    "date",
    "kind",
    "status",
    "requested_by",
    "reason",
    "payload",
    "parent_id",
    "approver_role",
    "token_expires_at",
    "result",
    "message",
    "created_at",
    "started_at",
    "finished_at",
)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def public_command(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {field: _iso(row.get(field)) for field in COMMAND_FIELDS}


def public_position(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row["symbol"],
        "quantity": as_number(row["quantity"]),
        "average_price": float(row["average_price"]) if row.get("average_price") is not None else None,
        "moved_by": row.get("moved_by"),
    }


def _same_person(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower() != ""


def _require_editable(entry: Mapping[str, Any]) -> None:
    if not desk_edit_allowed(entry):
        raise DeskForbidden(
            "This portfolio is not desk-editable (desk editing is on for "
            "desk_editable futures portfolios only)"
        )


def _desk_day(repo: DeskRepositoryPort, portfolio_id: str):
    day = repo.desk_date(portfolio_id)
    if day is None or not repo.book_rows(portfolio_id, day, "qt_proposal"):
        raise DeskNotSeeded(
            "The day's model run has not seeded the QT proposal for this "
            "portfolio yet; edits open once it has"
        )
    return day


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _current_sha256(repo: DeskRepositoryPort, portfolio_id, day) -> str | None:
    """The hash of the day's proposal as it is now (C1), or None if it cannot
    be snapshotted (a fractional quantity): then no request matches it."""
    try:
        return snapshot_sha256(proposal_snapshot(repo.proposal_rows(portfolio_id, day)))
    except DeskRuleError:
        logger.warning("[DESK] %s %s: the proposal cannot be snapshotted", portfolio_id, day)
        return None


def _published_record(repo: DeskRepositoryPort, portfolio_id, day, publishes):
    """C3: published_by/at from live_run_metadata; a done publish row stands
    in should live_run_metadata not say so (yet)."""
    published = repo.publish_state(portfolio_id, day)
    if published and published.get("published_at"):
        return {
            "published_by": published.get("published_by"),
            "published_at": _iso(published.get("published_at")),
        }
    done = [c for c in publishes if c["status"] == DONE]
    if done:
        return {
            "published_by": done[-1]["requested_by"],
            "published_at": _iso(done[-1].get("finished_at")),
        }
    return None


class GetDeskState:
    """Everything the desk page shows for one portfolio's book date."""

    def __init__(self, repo: DeskRepositoryPort, now=None):
        self.repo = repo
        self.now = now or _utcnow

    def execute(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        portfolio_id = entry["portfolio_id"]
        day = self.repo.desk_date(portfolio_id)
        state: dict[str, Any] = {
            "portfolioId": portfolio_id,
            "deskEditable": desk_edit_allowed(entry),
            "date": _iso(day),
            "seeded": False,
            "books": {"system": [], "qt_proposal": [], "qt": []},
            "comparison": [],
            "latestSave": None,
            "overrideRequests": [],
            "publish": None,
            "published": None,
            # Why save, override request and publish are closed, or None:
            # "published" (C3) or "publishing" (a publish is pending/running).
            "locked": None,
            "openOverrideRequestId": None,
        }
        if day is None:
            return state

        books = {
            book: list(self.repo.book_rows(portfolio_id, day, book))
            for book in ("system", "qt_proposal", "qt")
        }
        commands = list(self.repo.commands(portfolio_id, day))
        saves = [c for c in commands if c["kind"] == SAVE]
        publishes = [c for c in commands if c["kind"] == PUBLISH]
        decisions = {
            c["parent_id"]: c for c in commands if c["kind"] == OVERRIDE_DECISION
        }
        requests = [
            {**public_command(c), "decision": public_command(decisions.get(c["id"]))}
            for c in commands
            if c["kind"] == OVERRIDE_REQUEST
        ]
        published = _published_record(self.repo, portfolio_id, day, publishes)
        publishing = any(c["status"] in OPEN_STATUSES for c in publishes)
        open_request = open_override_request(
            commands, self.now(), _current_sha256(self.repo, portfolio_id, day)
        )

        state.update(
            {
                "seeded": bool(books["qt_proposal"]),
                "books": {
                    book: [public_position(r) for r in rows] for book, rows in books.items()
                },
                "comparison": asked_vs_given(books["qt_proposal"], books["qt"]),
                "latestSave": public_command(saves[-1]) if saves else None,
                "overrideRequests": requests,
                "publish": public_command(publishes[-1]) if publishes else None,
                "published": published,
                "locked": "published" if published else "publishing" if publishing else None,
                "openOverrideRequestId": open_request["id"] if open_request else None,
            }
        )
        return state


class ListSymbolChoices:
    """Symbols the desk may add: metadata.contract_metadata of the book's
    asset class, each with its latest close (never typed by the user)."""

    def __init__(self, repo: DeskRepositoryPort):
        self.repo = repo

    def execute(self, entry: Mapping[str, Any]) -> list[dict[str, Any]]:
        _require_editable(entry)
        return [
            {
                "symbol": row["symbol"],
                "root": row["root"],
                "name": row["name"],
                "sector": row.get("sector"),
                "price": float(row["price"]),
                "price_date": _iso(row.get("price_date")),
            }
            for row in self.repo.symbol_choices(entry.get("asset_class") or "futures")
        ]


class SaveDeskEdit:
    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort):
        self.repo = repo
        self.agent = agent

    def execute(
        self, entry: Mapping[str, Any], edits: Any, reason: Any, requested_by: str
    ) -> dict[str, Any]:
        _require_editable(entry)
        reason = require_reason(reason)
        # Validate the shape before touching the database; the plan itself
        # runs again inside the transaction against the locked rows.
        if not isinstance(edits, list) or not edits:
            raise DeskRuleError("changes must be a non-empty list of {symbol, quantity, expected}")
        portfolio_id = entry["portfolio_id"]
        day = _desk_day(self.repo, portfolio_id)
        # The published/publishing refusal (C3) and the stale-edit check run
        # inside the save transaction, under the day lock.
        command = self.repo.save_proposal(
            portfolio_id,
            day,
            lambda current: plan_desk_edit(current, edits),
            reason,
            requested_by,
        )
        outcome = self.agent.run_desk(command)
        return {"command": public_command(command), "agent": outcome}


class GetCommand:
    def __init__(self, repo: DeskRepositoryPort):
        self.repo = repo

    def execute(self, command_id: int) -> dict[str, Any]:
        row = self.repo.get_command(command_id)
        if row is None:
            raise DeskNotFound(f"No desk command {command_id}")
        return public_command(row)


class RequestOverride:
    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort):
        self.repo = repo
        self.agent = agent

    def execute(self, entry: Mapping[str, Any], reason: Any, requested_by: str) -> dict[str, Any]:
        _require_editable(entry)
        reason = require_reason(reason)
        portfolio_id = entry["portfolio_id"]
        day = _desk_day(self.repo, portfolio_id)
        # One transaction: the C3 refusals, one open request a day (C2) and
        # the proposal snapshot with its hash (C1).
        command = self.repo.insert_override_request(portfolio_id, day, requested_by, reason)
        outcome = self.agent.request_override(command)
        return {"command": public_command(command), "agent": outcome}


def _request_for_token(repo: DeskRepositoryPort, token: Any, now: datetime):
    if not isinstance(token, str) or not token.strip():
        raise DeskNotFound("No approval link token given")
    row = repo.find_request_by_token_hash(token_hash(token.strip()))
    if row is None or row["kind"] != OVERRIDE_REQUEST:
        raise DeskNotFound("This approval link is not valid")
    expires = row.get("token_expires_at")
    if expires is None or expires <= now:
        raise DeskGone("This approval link has expired")
    return row


class LookupApproval:
    """The approval page: the request with the book it snapshotted (C1), and
    the model book (system) next to the desk's request (qt_proposal) and the
    current qt book."""

    def __init__(self, repo: DeskRepositoryPort, now=None):
        self.repo = repo
        self.now = now or _utcnow

    def execute(self, token: Any) -> dict[str, Any]:
        request = _request_for_token(self.repo, token, self.now())
        portfolio_id, day = request["portfolio_id"], request["date"]
        books = {
            book: list(self.repo.book_rows(portfolio_id, day, book))
            for book in ("system", "qt_proposal", "qt")
        }
        decision = next(
            (
                c
                for c in self.repo.commands(portfolio_id, day)
                if c["kind"] == OVERRIDE_DECISION and c["parent_id"] == request["id"]
            ),
            None,
        )
        payload = request.get("payload") if isinstance(request.get("payload"), Mapping) else {}
        snapshot = payload.get("proposal") if isinstance(payload.get("proposal"), list) else None
        current = _current_sha256(self.repo, portfolio_id, day)
        published = _published_record(
            self.repo,
            portfolio_id,
            day,
            [c for c in self.repo.commands(portfolio_id, day) if c["kind"] == PUBLISH],
        )
        return {
            "request": public_command(request),
            "decision": public_command(decision),
            "books": {b: [public_position(r) for r in rows] for b, rows in books.items()},
            "table": three_books(books["system"], books["qt_proposal"], books["qt"]),
            # The book an approval books exactly, as it stood at the request.
            "snapshot": snapshot,
            "snapshotMatches": snapshot is not None
            and current is not None
            and request_matches(request, current),
            "published": published,
        }


class DecideOverride:
    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

    def execute(
        self,
        token: Any,
        approved: Any,
        approver_email: str,
        approver_role: str | None,
        reason: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(approved, bool):
            raise DeskRuleError("approved must be true or false")
        request = _request_for_token(self.repo, token, self.now())
        if approver_role is None:
            raise DeskForbidden("Only the VP or the President may decide an override")
        if _same_person(approver_email, request["requested_by"]):
            raise DeskForbidden("You cannot decide your own override request")
        if reason is not None and not isinstance(reason, str):
            raise DeskRuleError("reason must be text")
        # The repository refuses, under the day lock: a decided request, one
        # not e-mailed, a published day, and an approval of a proposal that
        # changed since the request (409).
        decision = self.repo.insert_decision(
            request["id"],
            approved,
            approver_email,
            approver_role,
            (reason or "").strip() or None,
        )
        outcome = self.agent.record_decision(decision, token.strip())
        return {"command": public_command(decision), "agent": outcome}


class PublishDesk:
    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort):
        self.repo = repo
        self.agent = agent

    def execute(self, entry: Mapping[str, Any], requested_by: str) -> dict[str, Any]:
        _require_editable(entry)
        portfolio_id = entry["portfolio_id"]
        day = _desk_day(self.repo, portfolio_id)
        # Published (C3) and publish-already-open are refused under the day lock.
        command = self.repo.insert_publish(portfolio_id, day, requested_by)
        outcome = self.agent.publish(command)
        return {"command": public_command(command), "agent": outcome}
