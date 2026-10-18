"""QT desk use cases (contract sections 4, 6 and 7, and the daily approval
cutoff of domain/qt/cutoff.py).

AlgoLens inserts a trading.position_overrides row, then calls the engine's
desk service with its id. The call is a fast path only: if it fails the row
stays pending and the engine re-drives it, so a gRPC failure never fails the
user's action.
"""

import logging
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

from algolens.application.qt.ports import (
    DeskAgentPort,
    DeskConflict,
    DeskForbidden,
    DeskGone,
    DeskNotFound,
    DeskNotSeeded,
    DeskRepositoryPort,
    DeskRiskUnavailable,
)
from algolens.domain.portfolio.registry import desk_edit_allowed
from algolens.domain.qt.cutoff import (
    NEW_YORK,
    approval_closed,
    closed_message,
    deadlines,
    publish_source,
    rescind_closed,
    rescind_closed_message,
)
from algolens.domain.qt.desk import (
    DONE,
    OPEN_STATUSES,
    OVERRIDE_DECISION,
    OVERRIDE_REQUEST,
    PUBLISH,
    RESCIND,
    SAVE,
    DeskRuleError,
    approving_email,
    approving_flow,
    as_number,
    asked_vs_given,
    open_override_request,
    plan_desk_edit,
    proposal_snapshot,
    request_matches,
    require_email_choice,
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


def _published_record(repo: DeskRepositoryPort, portfolio_id, day):
    """C3: published_by/at from live_run_metadata, the only record of an
    approval (a done publish row is history: a rescinded approval clears
    published_at and leaves its row done). publish_source and sent_at come
    from migration 026's columns (NULL before it, or before the engine set
    them); publish_source is otherwise read from published_by."""
    published = repo.publish_state(portfolio_id, day)
    if published and published.get("published_at"):
        return {
            "published_by": published.get("published_by"),
            "published_at": _iso(published.get("published_at")),
            "publish_source": publish_source(
                published.get("publish_source"), published.get("published_by")
            ),
            "sent_at": _iso(published.get("sent_at")),
        }
    return None


def _refuse_after_cutoff(
    repo: DeskRepositoryPort, portfolio_id: str, day, now: datetime, action: str
) -> None:
    """From 10:00 New York on the book date the day is the engine's: it
    publishes and sends the model's book (fallback). Refuse (409), saying
    "already published" when it is."""
    if not approval_closed(day, now):
        return
    published = _published_record(repo, portfolio_id, day)
    if published:
        raise DeskConflict(
            f"The {day.isoformat()} book is already published"
            + (f" (by {published['published_by']})" if published.get("published_by") else "")
        )
    raise DeskConflict(closed_message(day, action))


def _run_status(agent: DeskAgentPort, portfolio_id: str, day) -> dict[str, Any]:
    """D-56: the engine's word on the model run of `day`, or {"unavailable": <reason>}."""
    try:
        return agent.get_run_status(portfolio_id, day)
    except DeskRiskUnavailable as exc:
        return {"unavailable": exc.reason}


def _desk_risk(agent: DeskAgentPort, portfolio_id: str, day) -> dict[str, Any]:
    """The engine's risk report of the day's qt book (contract C9), or
    {"unavailable": <reason>} when it cannot be read."""
    try:
        return agent.get_desk_risk(portfolio_id, day)
    except DeskRiskUnavailable as exc:
        return {"unavailable": exc.reason}


# Decision 5 (2026-10-16): the caps the VP or President may approve a book past.
# The margin cap is never among them. The engine decides what blocks
# (DeskRisk.blocks_publish, desk.proto 1.6.0); this only words the refusal.
OVERRIDABLE_CAPS = frozenset({"L_g", "L_n", "CAP"})


def blocked_message(risk: Mapping[str, Any], book: str = "The positions are") -> str:
    """The refusal for a report whose blocksPublish is set: what blocks, and
    what the desk can do about it."""
    blockers = list(risk.get("blockers") or ())
    terms = [b.get("term") for b in blockers]
    if "incomplete" in terms:
        return next(b["detail"] for b in blockers if b.get("term") == "incomplete")
    detail = "; ".join(b.get("detail") or b.get("term") or "" for b in blockers)
    text = f"{book} over a cap ({detail})"
    if "MARGIN" in terms:
        return text + ": the margin cap cannot be overridden; save positions within it"
    if risk.get("state") == "override" or not set(terms) <= OVERRIDABLE_CAPS:
        return text
    return text + ": save within the caps or ask the VP or President to approve your positions"


def _refuse_outside_risk_limits(
    repo: DeskRepositoryPort, agent: DeskAgentPort, portfolio_id: str, day
) -> None:
    """Decision 5: the desk may not approve a book the engine's publish gate
    blocks. Refuse (409) while a save is still running, while the report
    cannot be read (fail closed), while it is not yet the report of the latest
    done save, and while the engine says the book may not be published
    (blocksPublish: over a cap, an incomplete book, or an approved override
    over the margin cap). A published day is left to the repository's
    refusal (C3). The engine checks again."""
    if _published_record(repo, portfolio_id, day):
        return
    saves = [c for c in repo.commands(portfolio_id, day) if c["kind"] == SAVE]
    running = next((c for c in reversed(saves) if c["status"] in OPEN_STATUSES), None)
    if running is not None:
        raise DeskConflict(
            f"A save is still running (#{running['id']}); approve once it has finished"
        )
    risk = _desk_risk(agent, portfolio_id, day)
    if "unavailable" in risk:
        raise DeskConflict(f"The risk check is unavailable ({risk['unavailable']}); try again")
    done = [c for c in saves if c["status"] == DONE]
    if (risk.get("state") == "desk" and done
            and int(done[-1]["id"]) != int(risk.get("auditId") or 0)):
        raise DeskConflict(
            f"The risk check has not caught up with save #{done[-1]['id']}; try again"
        )
    if risk.get("blocksPublish"):
        raise DeskConflict(blocked_message(risk, f"The {day.isoformat()} positions are"))


def _refuse_c_outside_limits(
    repo: DeskRepositoryPort, agent: DeskAgentPort, portfolio_id: str, day
) -> int:
    """C10, Approve C: the QT approves the engine's book of the latest done
    save. Refuse (409) while a save is running, without a done save, while
    the risk check cannot be read or is of another save, and while the
    engine's publish gate blocks C (decision 5: C over a cap). A limit that
    bound is fine: C is the book cut to fit it. Returns the save's id. The
    engine checks again."""
    saves = [c for c in repo.commands(portfolio_id, day) if c["kind"] == SAVE]
    running = next((c for c in reversed(saves) if c["status"] in OPEN_STATUSES), None)
    if running is not None:
        raise DeskConflict(
            f"Dynamic optimisation is still running (#{running['id']}); approve once it has finished"
        )
    done = [c for c in saves if c["status"] == DONE]
    if not done:
        raise DeskConflict("There is no finished save to approve; approve your positions first")
    save_id = int(done[-1]["id"])
    risk = _desk_risk(agent, portfolio_id, day)
    if "unavailable" in risk:
        raise DeskConflict(f"The risk check is unavailable ({risk['unavailable']}); try again")
    if risk.get("state") != "desk" or int(risk.get("auditId") or 0) != save_id:
        raise DeskConflict(
            f"The day's book is not the result of save #{save_id} yet; try again"
        )
    if risk.get("blocksPublish"):
        raise DeskConflict(blocked_message(risk, "The engine's book (C) is"))
    return save_id


class GetDeskState:
    """Everything the desk page shows for one portfolio's book date."""

    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

    def execute(
        self, entry: Mapping[str, Any], viewer_is_approver: bool = False
    ) -> dict[str, Any]:
        portfolio_id = entry["portfolio_id"]
        day = self.repo.desk_date(portfolio_id)
        now = self.now()
        state: dict[str, Any] = {
            "portfolioId": portfolio_id,
            # The server's clock and the day's deadlines in New York: the
            # desk counts down from these, never from the browser's clock.
            "serverTime": now.astimezone(timezone.utc).isoformat(),
            "deadlines": deadlines(day, now),
            # Whether live_run_metadata carries 026's publish_source/sent_at.
            "sendTracked": self.repo.send_tracking(),
            "deskEditable": desk_edit_allowed(entry),
            "date": _iso(day),
            "seeded": False,
            "books": {"system": [], "qt_proposal": [], "qt": []},
            "comparison": [],
            "latestSave": None,
            "overrideRequests": [],
            "publish": None,
            # The latest rescind (C8: the desk takes back its approval), polled
            # like publish.
            "rescind": None,
            "published": None,
            # Whether the viewer is the VP or the President (QT_APPROVERS):
            # only they take back a day an override published.
            "viewerIsApprover": viewer_is_approver,
            # Why save, override request and publish are closed, or None:
            # "published" (C3) or "publishing" (a publish is pending/running).
            "locked": None,
            "openOverrideRequestId": None,
            # The engine's risk report of the day's qt book (C9), or
            # {"unavailable": reason}; None before the first book.
            "risk": None,
        }
        # D-56: today's model run as the engine reports it (running, failed, refused), so the
        # page says why there is no book yet instead of inferring it.
        today = date.fromisoformat(state["deadlines"]["today"])
        state["runStatus"] = {"date": today.isoformat(), **_run_status(self.agent, portfolio_id, today)}
        if day is None:
            return state

        books = {
            book: list(self.repo.book_rows(portfolio_id, day, book))
            for book in ("system", "qt_proposal", "qt")
        }
        commands = list(self.repo.commands(portfolio_id, day))
        saves = [c for c in commands if c["kind"] == SAVE]
        publishes = [c for c in commands if c["kind"] == PUBLISH]
        rescinds = [c for c in commands if c["kind"] == RESCIND]
        decisions = {
            c["parent_id"]: c for c in commands if c["kind"] == OVERRIDE_DECISION
        }
        requests = [
            {**public_command(c), "decision": public_command(decisions.get(c["id"]))}
            for c in commands
            if c["kind"] == OVERRIDE_REQUEST
        ]
        published = _published_record(self.repo, portfolio_id, day)
        if published:
            # The C10 flow that approved the day ("override_b" for an override).
            published["flow"] = approving_flow(commands)
            # D-66: whether that approval asked for the e-mail (False: the desk sends it).
            published["email"] = approving_email(commands)
        publishing = any(c["status"] in OPEN_STATUSES for c in publishes)
        open_request = open_override_request(
            commands, now, _current_sha256(self.repo, portfolio_id, day)
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
                "rescind": public_command(rescinds[-1]) if rescinds else None,
                "published": published,
                "locked": "published" if published else "publishing" if publishing else None,
                "openOverrideRequestId": open_request["id"] if open_request else None,
                "risk": _desk_risk(self.agent, portfolio_id, day),
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
    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

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
        _refuse_after_cutoff(self.repo, portfolio_id, day, self.now(), "Editing")
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


class ApproveDesk:
    """C10, the QT's Approve on B: save the edits (B) and approve them in one
    go. The engine runs B through dynamic optimisation and the risk system
    (the save's desk pass, which stores C); when C equals B and is within the
    limits it publishes, otherwise it refuses the publish row with the
    differences and the desk chooses: approve C, or ask the VP or President to
    approve B. The cutoffs are C7's, by the moment Approve was pressed."""

    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

    def execute(
        self, entry: Mapping[str, Any], edits: Any, reason: Any, requested_by: str,
        email: Any = None,
    ) -> dict[str, Any]:
        _require_editable(entry)
        reason = require_reason(reason)
        if not isinstance(edits, list):
            raise DeskRuleError("changes must be a list of {symbol, quantity, expected}")
        email = require_email_choice(email)
        portfolio_id = entry["portfolio_id"]
        day = _desk_day(self.repo, portfolio_id)
        _refuse_after_cutoff(self.repo, portfolio_id, day, self.now(), "Approval")
        # An Approve with no edit approves B as it stands (the model's A, or
        # the last save): the engine still runs it, so C is checked the same way.
        save, publish = self.repo.approve_proposal(
            portfolio_id,
            day,
            lambda current: plan_desk_edit(current, edits) if edits else [],
            reason,
            requested_by,
            email=email,
        )
        # RunDesk first: the publish runs on the portfolio's queue after it.
        save_outcome = self.agent.run_desk(save)
        publish_outcome = self.agent.publish(publish)
        return {
            "command": public_command(publish),
            "save": public_command(save),
            "agent": publish_outcome,
            "saveAgent": save_outcome,
        }


class GetCommand:
    def __init__(self, repo: DeskRepositoryPort):
        self.repo = repo

    def execute(self, command_id: int) -> dict[str, Any]:
        row = self.repo.get_command(command_id)
        if row is None:
            raise DeskNotFound(f"No desk command {command_id}")
        return public_command(row)


class RequestOverride:
    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

    def execute(self, entry: Mapping[str, Any], reason: Any, requested_by: str) -> dict[str, Any]:
        _require_editable(entry)
        reason = require_reason(reason)
        portfolio_id = entry["portfolio_id"]
        day = _desk_day(self.repo, portfolio_id)
        _refuse_after_cutoff(self.repo, portfolio_id, day, self.now(), "An override request")
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
    current qt book, and the engine's risk report of the day (C9) so the
    approvers see what the override waives."""

    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

    def execute(self, token: Any) -> dict[str, Any]:
        now = self.now()
        request = _request_for_token(self.repo, token, now)
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
        published = _published_record(self.repo, portfolio_id, day)
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
            "risk": _desk_risk(self.agent, portfolio_id, day),
            # The desk approves the day by 09:30 New York; from 10:00 the
            # model's book is sent and this request can no longer be decided.
            "serverTime": now.astimezone(timezone.utc).isoformat(),
            "deadlines": deadlines(day, now),
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
        now = self.now()
        request = _request_for_token(self.repo, token, now)
        if approver_role is None:
            raise DeskForbidden("Only the VP or the President may decide an override")
        if _same_person(approver_email, request["requested_by"]):
            raise DeskForbidden("You cannot decide your own override request")
        if reason is not None and not isinstance(reason, str):
            raise DeskRuleError("reason must be text")
        _refuse_after_cutoff(
            self.repo, request["portfolio_id"], request["date"], now, "Deciding an override"
        )
        # The repository refuses, under the day lock: a decided request, one
        # not e-mailed, a published day, and an approval of a proposal that
        # changed since the request (409).
        # C10: an approval also queues the publish of B (requested by the QT
        # who asked), which runs once the override has booked it.
        decision, publish = self.repo.decide_override(
            request["id"],
            approved,
            approver_email,
            approver_role,
            (reason or "").strip() or None,
        )
        outcome = self.agent.record_decision(decision, token.strip())
        result = {"command": public_command(decision), "agent": outcome}
        if publish is not None:
            result["publish"] = public_command(publish)
            result["publishAgent"] = self.agent.publish(publish)
        return result


class PublishDesk:
    """The desk's approval of the day (the UI's Approve; command kind
    'publish'). Before 09:30 New York the engine only freezes the day and
    e-mails it at 09:30; from 09:30 to 10:00 it also e-mails at once; from
    10:00 it is refused here (409) and by the engine. Positions outside the
    risk limits are refused here until an override is approved (C9)."""

    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

    def execute(
        self, entry: Mapping[str, Any], requested_by: str, flow: Any = None,
        acknowledged: Any = None, email: Any = None,
    ) -> dict[str, Any]:
        _require_editable(entry)
        email = require_email_choice(email)
        portfolio_id = entry["portfolio_id"]
        day = _desk_day(self.repo, portfolio_id)
        _refuse_after_cutoff(self.repo, portfolio_id, day, self.now(), "Approval")
        payload = None
        if flow == "accept_c":
            # C10: the QT approves the engine's book C, knowing it differs.
            if not isinstance(acknowledged, list) or not all(
                isinstance(s, str) for s in acknowledged
            ):
                raise DeskRuleError(
                    "acknowledged must list the symbols the engine changed"
                )
            save_id = _refuse_c_outside_limits(self.repo, self.agent, portfolio_id, day)
            payload = {"flow": "accept_c", "after": save_id, "acknowledged": acknowledged}
        elif flow is not None:
            raise DeskRuleError("flow must be accept_c (or absent)")
        else:
            _refuse_outside_risk_limits(self.repo, self.agent, portfolio_id, day)
        if not email:
            # D-66: approved without the e-mail; the desk sends it later with Send.
            payload = {**(payload or {}), "email": False}
        # Published (C3) and publish-already-open are refused under the day lock.
        command = self.repo.insert_publish(portfolio_id, day, requested_by, payload)
        outcome = self.agent.publish(command)
        return {"command": public_command(command), "agent": outcome}


class SendDesk:
    """D-66, the desk's Send: e-mail the day's approved book now, once, when it
    was approved without the e-mail (or its send has not happened yet). Today's
    book only: a past day's book must not reach anyone as today's (D-40).
    Refused here (409) and by the engine otherwise."""

    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

    def execute(self, entry: Mapping[str, Any], requested_by: str) -> dict[str, Any]:
        _require_editable(entry)
        portfolio_id = entry["portfolio_id"]
        day = _desk_day(self.repo, portfolio_id)
        today = self.now().astimezone(NEW_YORK).date()
        if day != today:
            raise DeskConflict(
                f"Only today's book is e-mailed: {day.isoformat()} is not today "
                f"({today.isoformat()} in New York)"
            )
        command = self.repo.insert_send(portfolio_id, day, requested_by)
        outcome = self.agent.publish(command)
        return {"command": public_command(command), "agent": outcome}


class RescindDesk:
    """The desk takes back the day's approval (the UI's "Rescind approval";
    command kind 'rescind', contract C8). Only a desk approval (publish_source
    'desk'), only while it is unsent and only before 09:30 New York on the book
    date, when the engine e-mails it; refused here (409) and by the engine
    otherwise. Anyone on QT takes back a desk approval; a day an override
    published only the VP or the President (Dom 2026-10-16). Once the engine
    clears published_at the day takes edits and a new approval again."""

    def __init__(self, repo: DeskRepositoryPort, agent: DeskAgentPort, now=None):
        self.repo = repo
        self.agent = agent
        self.now = now or _utcnow

    def execute(
        self, entry: Mapping[str, Any], requested_by: str, is_approver: bool = False
    ) -> dict[str, Any]:
        _require_editable(entry)
        portfolio_id = entry["portfolio_id"]
        day = _desk_day(self.repo, portfolio_id)
        if rescind_closed(day, self.now()):
            raise DeskConflict(rescind_closed_message(day))
        # Not a desk approval, already sent, an override's day taken back by
        # someone other than the VP or the President, and a publish or rescind
        # already open are refused under the day lock.
        command = self.repo.insert_rescind(portfolio_id, day, requested_by, is_approver)
        outcome = self.agent.rescind(command)
        return {"command": public_command(command), "agent": outcome}
