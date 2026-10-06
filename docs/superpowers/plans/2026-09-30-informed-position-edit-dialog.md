# Informed Position Edit Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make QT position edits an informed, attributable decision by requiring an audit rationale, displaying the authenticated actor and exact size changes, and presenting evaluator-produced post-change risk before confirmation.

**Architecture:** Extend the existing strict QT draft request with a bounded `rationale`, bind it into the persisted draft payload/digest, and keep the actor sourced exclusively from JWT authentication. Add a compact change-request card to `QtProposalWorkspace`; continue using `QtSelectionTable` for exact per-position deltas and `QtPreviewEvidence` for authoritative proposed-book risk.

**Tech Stack:** React 18, TypeScript, Vitest/Testing Library, Flask, Python dataclasses, PostgreSQL JSONB.

---

## Global Constraints

- The displayed actor is derived from the authenticated user and is never editable or accepted as a client claim.
- Rationale is required, trimmed, UTF-8 bounded, persisted in `qt_drafts.selection_payload`, and covered by the draft digest.
- Risk values come only from the server evaluator response; the client must not estimate portfolio risk.
- Existing exact decimal quantity handling, authorization, idempotency, stale-write checks, and confirmation gates remain intact.
- Do not add or commit `graphify-out/`.

### Task 1: Bind rationale to the QT draft audit record

**Files:**
- Modify: `algolens-api/algolens/domain/portfolio/qt_workflow_models.py`
- Modify: `algolens-api/algolens/application/portfolio/qt_workflow.py`
- Modify: `algolens-api/tests/test_qt_workflow_canonical.py`
- Modify: focused QT workflow service tests that construct draft requests

- [x] Add failing tests proving missing/blank/oversized rationale is refused and a valid rationale is persisted in `selection_payload` and changes the idempotency/draft digest.
- [x] Run focused backend tests and observe the expected failures.
- [x] Add `rationale` to `QtDraftSaveRequest`, validate trimmed non-empty UTF-8 length (1–1000 bytes), and persist it beside `selection_rows` in the draft payload.
- [x] Update existing test request fixtures/callers to include a valid rationale.
- [x] Run focused backend QT tests to green.

### Task 2: Add the compact attributable change request UI

**Files:**
- Modify: `algolens-frontend/src/components/StrategyDetail.tsx`
- Modify: `algolens-frontend/src/components/QtProposalWorkspace.tsx`
- Modify: `algolens-frontend/src/infrastructure/api/qtPreviewApi.ts`
- Modify: `algolens-frontend/src/components/QtProposalWorkspace.test.tsx`
- Modify: `algolens-frontend/src/infrastructure/api/qtPreviewApi.test.ts`

- [x] Add failing UI/API tests proving the dialog shows the authenticated actor, requires a rationale before Save draft, sends its trimmed value, and continues to show exact per-row deltas.
- [x] Run the focused frontend tests and observe the expected failures.
- [x] Pass a display label/email from `StrategyDetail`, render a compact `Position change request` card, preserve typed rationale while the dialog stays mounted, and gate save on a valid rationale.
- [x] Send only the rationale—not a claimed actor—through `QtPreviewApi.saveDraft`.
- [x] Run focused frontend tests to green.

### Task 3: Clarify post-change risk review and verify the complete flow

**Files:**
- Modify: `algolens-frontend/src/components/qt-proposal/QtPreviewEvidence.tsx`
- Modify: `algolens-frontend/src/components/QtProposalWorkspace.test.tsx`
- Modify: relevant component tests if accessible labels change

- [x] Add a failing test proving evaluation labels the metrics as proposed/post-change risk and confirmation remains unavailable before evaluation.
- [x] Relabel the existing evaluator evidence so users can clearly distinguish proposed quantities, proposed weights, risk status/metrics, breaches, and estimated costs before confirming.
- [x] Run focused tests, the full frontend test suite, typecheck, and production build; run the relevant backend QT suite.
- [x] Review the diff for actor spoofing, rationale loss, ad-hoc risk math, or weakened confirmation gates.

## Review Focus

- Verify every save path supplies and persists rationale, including empty-owner and retry flows.
- Verify the UI never treats a display name/email as authorization evidence.
- Verify changing rationale participates in idempotency identity and immutable draft evidence.
- Verify all displayed risk is evaluator output tied to the selected-book digest.
