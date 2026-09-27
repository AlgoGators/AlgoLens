import { useCallback, useEffect, useRef, useState } from 'react';
import {
  canConfirmQt, decodeQtBookDecision, makeQtState, normalizeQtSelectionInput, qtComponentKey, qtContextKey,
  qtDecisionMatchesPreview, qtEmptyOwnerMatches, reduceQtState,
  type QtBookDecision, type QtDecision, type QtEvent, type QtPhase, type QtSelectionRow, type QtState,
} from '../domain/portfolio/qtPreview';
import { QtApiError, QtMutationUncertainError, QtPreviewApi } from '../infrastructure/api/qtPreviewApi';
import { QtRecovery, QtRecoveryStorageError } from '../infrastructure/api/qtRecovery';
import { SessionExpiredError } from '../infrastructure/api/httpClient';
import { QtDecisionStatus } from './qt-proposal/QtDecisionStatus';
import { QtPreviewEvidence } from './qt-proposal/QtPreviewEvidence';
import { QtSelectionTable } from './qt-proposal/QtSelectionTable';

type Props = { actorId: string; bookId: string; sourceDay: string; onPublished: () => void };
function selectionRows(rows: QtSelectionRow[], selection: Readonly<Record<string, string>>) {
  return rows.filter(row => row.editable).map(row => ({
    key: row.key, quantity_exact: normalizeQtSelectionInput(selection[qtComponentKey(row.key)] ?? row.quantity_exact, row.asset_type),
  }));
}
function matchesSaved(rows: QtSelectionRow[], selection: Readonly<Record<string, string>>): boolean {
  return rows.every(row => selection[qtComponentKey(row.key)] === row.quantity_exact) &&
    Object.keys(selection).length === rows.length;
}
function decisionPhase(decision: QtDecision): QtPhase {
  return decision.status === 'pending_override' ? 'pending_override' :
    decision.receipt?.status === 'processed' ? decision.report_ready ? 'processed' : 'report_blocked' :
      decision.receipt?.status === 'failed' ? 'unavailable' : 'processing';
}
function problem(error: unknown): { message: string; revoke: boolean } {
  if (error instanceof SessionExpiredError) return { message: 'Session expired. Sign in again before QT actions.', revoke: true };
  if (error instanceof QtApiError) return { message: `QT action unavailable: ${error.code}. Refresh the current source or decision.`,
    revoke: error.status === 403 };
  if (error instanceof QtRecoveryStorageError) return { message: 'Recovery storage is unavailable. QT confirmation was not submitted.', revoke: false };
  if (error instanceof QtMutationUncertainError) return { message: 'QT action outcome is uncertain. Recover the original request or refresh status.', revoke: false };
  return { message: 'QT data is unavailable. Refresh and try again.', revoke: false };
}

export function QtProposalWorkspace({ actorId, bookId, sourceDay, onPublished }: Props) {
  const context = qtContextKey(actorId, bookId, sourceDay);
  const [state, setState] = useState<QtState>(() => makeQtState(context));
  const stateRef = useRef(state);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [message, setMessage] = useState('');
  const [revoked, setRevoked] = useState(false);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [recoveredDecision, setRecoveredDecision] = useState<QtDecision | null>(null);
  const [hasConfirmationRecovery, setHasConfirmationRecovery] = useState(false);
  const [hasApprovalRecovery, setHasApprovalRecovery] = useState(false);
  const [decisionRefresh, setDecisionRefresh] = useState(0);
  const renderEpoch = useRef({ context, epoch: 0 });
  if (renderEpoch.current.context !== context) renderEpoch.current = { context, epoch: renderEpoch.current.epoch + 1 };
  const reviewScope = JSON.stringify([context, renderEpoch.current.epoch, refreshIndex, decisionRefresh]);
  const activeReviewScope = useRef(reviewScope); activeReviewScope.current = reviewScope;
  const [review, setReview] = useState<{ scope: string; status: 'ready' | 'unavailable'; value: QtBookDecision | null } | null>(null);
  const reviewRef = useRef(review); reviewRef.current = review;
  const activeContext = useRef(context);
  activeContext.current = context;
  const lifecycle = useRef(0);
  const published = useRef(new Set<string>());
  const send = useCallback((event: QtEvent): QtState => {
    const next = reduceQtState(stateRef.current, event);
    stateRef.current = next;
    setState(next);
    return next;
  }, []);

  useEffect(() => {
    const token = ++lifecycle.current;
    let live = true;
    const controller = new AbortController();
    send({ type: 'context_changed', context });
    setMessage(''); setRevoked(false); setRecoveredDecision(null);
    busyRef.current = false; setBusy(false);
    try {
      QtRecovery.activateActor(sessionStorage, actorId);
      setHasConfirmationRecovery(!!QtRecovery.loadConfirmation(sessionStorage, actorId, bookId));
      setHasApprovalRecovery(!!QtRecovery.loadApproval(sessionStorage, actorId, bookId));
    } catch { setHasConfirmationRecovery(false); setHasApprovalRecovery(false); }
    void (async () => {
      try {
        const proposalGeneration = stateRef.current.generation;
        const proposal = await QtPreviewApi.getProposal(bookId, controller.signal);
        if (!live || lifecycle.current !== token) return;
        if (proposal.source_day !== sourceDay) throw new Error('wrong_source_day');
        send({ type: 'proposal_loaded', context, generation: proposalGeneration, proposal });
        const draftGeneration = stateRef.current.generation;
        const draft = await QtPreviewApi.getDraft(bookId, controller.signal);
        if (!live || lifecycle.current !== token) return;
        if (draft.source_day !== sourceDay) throw new Error('wrong_source_day');
        send({ type: 'draft_loaded', context, generation: draftGeneration, draft });
      } catch (error) {
        if (!live || lifecycle.current !== token || (error instanceof DOMException && error.name === 'AbortError')) return;
        const failure = problem(error); setMessage(failure.message); setRevoked(failure.revoke);
        send({ type: 'unavailable', context, generation: stateRef.current.generation });
      }
    })();
    return () => { live = false; controller.abort(); lifecycle.current++; busyRef.current = false; };
  }, [actorId, bookId, context, refreshIndex, send, sourceDay]);

  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const value = decodeQtBookDecision(await QtPreviewApi.getBookDecision(bookId, sourceDay, controller.signal));
        if (value.book_id !== bookId || value.source_day !== sourceDay) throw new Error('wrong_review_scope');
        if (!live || activeReviewScope.current !== reviewScope) return;
        setReview({ scope: reviewScope, status: 'ready', value });
      } catch (error) {
        if (!live || activeReviewScope.current !== reviewScope || (error instanceof DOMException && error.name === 'AbortError')) return;
        setReview({ scope: reviewScope, status: 'unavailable', value: null });
        const failure = problem(error); if (failure.revoke) setRevoked(true);
      }
    })();
    return () => { live = false; controller.abort(); };
  }, [bookId, sourceDay, reviewScope]);

  const current = () => activeContext.current === context;
  async function runOneWrite(operation: (stillCurrent: () => boolean) => Promise<void>) {
    if (busyRef.current || revoked || !current()) return;
    busyRef.current = true; setBusy(true);
    const token = lifecycle.current;
    const stillCurrent = () => lifecycle.current === token && current();
    try { await operation(stillCurrent); }
    finally { if (stillCurrent()) { busyRef.current = false; setBusy(false); } }
  }
  function showFailure(error: unknown, stillCurrent: () => boolean, generation: number) {
    if (!stillCurrent()) return;
    const failure = problem(error);
    setMessage(failure.message); if (failure.revoke) setRevoked(true);
    if (error instanceof QtMutationUncertainError && stateRef.current.generation === generation)
      send({ type: 'uncertain', context, generation });
  }
  function notifyPublished(decision: QtDecision) {
    if (!current() || decision.book_id !== bookId || decision.status !== 'confirmed_decision' ||
      decision.receipt?.status !== 'processed' || !decision.report_ready) return;
    const identity = `${context}:${decision.decision_id}`;
    if (!published.current.has(identity)) { published.current.add(identity); onPublished(); }
  }
  function applyDecision(decision: QtDecision) {
    const currentState = stateRef.current;
    if (decision.book_id !== bookId) return;
    const discovered = reviewRef.current;
    if (discovered?.scope === activeReviewScope.current && discovered.value?.decision?.decision_id === decision.decision_id &&
        discovered.value.preview && qtDecisionMatchesPreview(decision, discovered.value.preview) &&
        discovered.value.decision.request_id === decision.request_id) {
      setReview({ ...discovered, value: { ...discovered.value, decision } });
      notifyPublished(decision);
      return;
    }
    if (currentState.preview?.preview_id === decision.preview_id) {
      const accepted = send({ type: 'decision_loaded', context, generation: currentState.generation, decision });
      if (accepted.decision !== decision) {
        setMessage('Decision evidence does not match the current QT preview. Refresh QT source.');
        return;
      }
    } else {
      const record = QtRecovery.loadConfirmation(sessionStorage, actorId, bookId);
      if (record?.preview_id !== decision.preview_id) return;
      setRecoveredDecision(decision);
      return;
    }
    notifyPublished(decision);
  }

  const visible = state.context === context ? state : makeQtState(context);
  const proposal = visible.proposal;
  const draft = visible.draft;
  const verifiedEmptySelection = qtEmptyOwnerMatches(proposal, draft);
  const sourceRows = proposal?.seed_rows ?? [];
  const chosenRows = draft?.selection_rows ?? sourceRows;
  const decision = visible.decision ?? recoveredDecision;
  const phase = visible.decision ? visible.phase : recoveredDecision ? decisionPhase(recoveredDecision) : visible.phase;
  const discovered = review?.scope === reviewScope && review.status === 'ready' ? review.value : null;
  const reviewedDecision = discovered?.decision ?? null;
  const reviewedPreview = discovered?.preview ?? null;
  const approvalGrant = !!proposal && proposal.book_id === bookId && proposal.source_day === sourceDay &&
    proposal.capability.required && proposal.capability.available && proposal.action_grants.can_approve && !revoked &&
    !(review?.scope === reviewScope && review.status === 'unavailable');
  let validSelection = false;
  try {
    selectionRows(chosenRows, visible.selection);
    validSelection = chosenRows.length > 0 || (verifiedEmptySelection && Object.keys(visible.selection).length === 0);
  }
  catch { validSelection = false; }
  const savedSelection = !!draft && draft.state === 'saved' && matchesSaved(draft.selection_rows, visible.selection);
  const sourceReady = proposal?.workflow_state === 'ready' && proposal.capability.available && !revoked;
  const editorAllowsEdit = reduceQtState(visible,
    { type: 'edited', context, selection: visible.selection }) !== visible;
  const canSave = !!sourceReady && !!draft && !!proposal.action_grants.can_save_draft && validSelection &&
    visible.phase === 'editing' && !busy;
  const canEvaluate = !!sourceReady && !!proposal?.action_grants.can_save_draft && validSelection && savedSelection && visible.phase === 'editing' && !busy;
  const canConfirm = !hasConfirmationRecovery && !busy && !revoked && canConfirmQt(visible);

  function edit(identity: string, value: string) {
    if (!current() || revoked) return;
    const before = stateRef.current;
    const after = send({ type: 'edited', context, selection: { ...before.selection, [identity]: value } });
    if (after !== before) setMessage('');
  }
  function save() {
    if (!canSave || !proposal) return;
    let rows: ReturnType<typeof selectionRows>;
    try { rows = selectionRows(chosenRows, stateRef.current.selection); }
    catch { setMessage('Enter a valid exact quantity for every editable component. Futures require whole contracts.'); return; }
    void runOneWrite(async stillCurrent => {
      const started = send({ type: 'save_started', context, generation: stateRef.current.generation });
      const generation = started.generation;
      try {
        const saved = await QtPreviewApi.saveDraft(bookId, {
          expected_source_digest: proposal.source_digest!, expected_provenance_digest: proposal.provenance_digest!,
          expected_draft_revision: draft?.draft_revision ?? 0, idempotency_key: crypto.randomUUID(), selection_rows: rows,
        });
        if (stillCurrent()) send({ type: 'draft_saved', context, generation, draft: saved });
      } catch (error) { showFailure(error, stillCurrent, generation); }
    });
  }
  function evaluate() {
    if (!canEvaluate || !draft || !proposal?.source_digest || !proposal.provenance_digest || !draft.draft_id || !draft.draft_digest) return;
    void runOneWrite(async stillCurrent => {
      const started = send({ type: 'evaluation_started', context, generation: stateRef.current.generation });
      const generation = started.generation;
      try {
        const preview = await QtPreviewApi.createPreview({ book_id: bookId, draft_id: draft.draft_id!,
          draft_revision: draft.draft_revision, draft_digest: draft.draft_digest!,
          expected_source_digest: proposal.source_digest!, expected_provenance_digest: proposal.provenance_digest!,
          idempotency_key: crypto.randomUUID() });
        if (stillCurrent()) send({ type: 'preview_loaded', context, generation, preview });
      } catch (error) { showFailure(error, stillCurrent, generation); }
    });
  }
  function confirm() {
    if (!canConfirm || !visible.preview) return;
    const preview = visible.preview;
    void runOneWrite(async stillCurrent => {
      const started = send({ type: 'confirmation_started', context, generation: stateRef.current.generation });
      const generation = started.generation;
      try {
        const decision = await QtRecovery.submitConfirmation(sessionStorage, { actor_id: actorId, book_id: bookId,
          preview_id: preview.preview_id, expected_digest: preview.payload_digest, idempotency_key: crypto.randomUUID(),
          acknowledge_warnings: preview.requires_override }, stillCurrent);
        if (!stillCurrent()) return;
        setHasConfirmationRecovery(true);
        const accepted = send({ type: 'decision_loaded', context, generation, decision });
        if (accepted.decision === decision) notifyPublished(decision);
        else setMessage('Decision evidence does not match the current QT preview. Refresh QT source.');
      } catch (error) {
        let failure = error;
        if (stillCurrent()) {
          try {
            if (error instanceof QtApiError && error.status === 409 &&
                ['preview_stale', 'preview_mismatch', 'preview_unavailable'].includes(error.code)) {
              QtRecovery.clearConfirmation(sessionStorage, actorId, bookId);
            }
            setHasConfirmationRecovery(!!QtRecovery.loadConfirmation(sessionStorage, actorId, bookId));
          } catch (storageError) { failure = storageError; }
        }
        showFailure(failure, stillCurrent, generation);
      }
    });
  }
  function recover() {
    if (!hasConfirmationRecovery) return;
    void runOneWrite(async stillCurrent => {
      try {
        const decision = await QtRecovery.recoverConfirmation(sessionStorage, actorId, bookId, stillCurrent);
        if (stillCurrent() && decision) applyDecision(decision);
      } catch (error) {
        let failure = error;
        if (stillCurrent() && error instanceof QtApiError && error.status === 409 &&
            ['preview_stale', 'preview_mismatch', 'preview_unavailable'].includes(error.code)) {
          try { QtRecovery.clearConfirmation(sessionStorage, actorId, bookId); setHasConfirmationRecovery(false); }
          catch (storageError) { failure = storageError; }
        }
        showFailure(failure, stillCurrent, stateRef.current.generation);
      }
    });
  }
  function acknowledgeResolvedConfirmation() {
    if (!current() || busyRef.current || !decision || decision.status !== 'confirmed_decision' ||
        !['processed', 'failed'].includes(decision.receipt?.status ?? '')) return;
    try {
      const record = QtRecovery.loadConfirmation(sessionStorage, actorId, bookId);
      if (!record || record.preview_id !== decision.preview_id ||
          (record.decision_id && record.decision_id !== decision.decision_id)) return;
      if (!QtRecovery.clearConfirmation(sessionStorage, actorId, bookId)) return;
      // Acknowledgment starts a fresh local review epoch; old async results cannot regain authority.
      const next = { ...makeQtState(context), generation: stateRef.current.generation + 1 };
      stateRef.current = next; setState(next);
      setHasConfirmationRecovery(false); setRecoveredDecision(null); setMessage('');
      setRefreshIndex(index => index + 1);
    } catch (error) { setMessage(problem(error).message); }
  }
  function refreshDecision() {
    if (!decision) return;
    const expectedId = decision.decision_id;
    void runOneWrite(async stillCurrent => {
      try {
        const latest = await QtPreviewApi.getDecision(expectedId);
        if (stillCurrent() && latest.decision_id === expectedId && latest.book_id === bookId) applyDecision(latest);
      } catch (error) { showFailure(error, stillCurrent, stateRef.current.generation); }
    });
  }
  function approve() {
    if (!approvalGrant || hasApprovalRecovery || !visible.decision?.can_approve ||
        visible.decision.status !== 'pending_override' || !visible.decision.request_id || !visible.preview) return;
    const expected = visible.decision; const preview = visible.preview; const generation = visible.generation;
    const requestId = expected.request_id!;
    const linked = (value: QtDecision) => value.decision_id === expected.decision_id &&
      value.request_id === requestId && qtDecisionMatchesPreview(value, preview);
    void runOneWrite(async stillCurrent => {
      const localCurrent = () => stillCurrent() && stateRef.current.generation === generation &&
        stateRef.current.preview === preview;
      try {
        const updated = await QtRecovery.submitApproval(sessionStorage, { actor_id: actorId, book_id: bookId,
          request_id: requestId, idempotency_key: crypto.randomUUID() }, localCurrent, linked);
        if (localCurrent()) {
          applyDecision(updated);
          setHasApprovalRecovery(!!QtRecovery.loadApproval(sessionStorage, actorId, bookId));
        }
      } catch (error) {
        if (localCurrent()) {
          try { setHasApprovalRecovery(!!QtRecovery.loadApproval(sessionStorage, actorId, bookId)); } catch { /* shown below */ }
        }
        showFailure(error, localCurrent, generation);
      }
    });
  }
  function approveDiscovered() {
    if (!approvalGrant || !reviewedDecision?.can_approve || reviewedDecision.status !== 'pending_override' ||
        !reviewedDecision.request_id || !reviewedPreview || hasApprovalRecovery) return;
    const expected = reviewedDecision; const preview = reviewedPreview;
    const linked = (value: QtDecision) => value.decision_id === expected.decision_id &&
      value.request_id === expected.request_id && qtDecisionMatchesPreview(value, preview);
    void runOneWrite(async stillCurrent => {
      const reviewCurrent = () => stillCurrent() && activeReviewScope.current === reviewScope;
      try {
        const updated = await QtRecovery.submitApproval(sessionStorage, { actor_id: actorId, book_id: bookId,
          request_id: expected.request_id!, idempotency_key: crypto.randomUUID() }, reviewCurrent, linked);
        if (!reviewCurrent()) return;
        if (!linked(updated)) throw new QtMutationUncertainError();
        applyDecision(updated);
        setHasApprovalRecovery(!!QtRecovery.loadApproval(sessionStorage, actorId, bookId));
      } catch (error) {
        if (reviewCurrent()) {
          try { setHasApprovalRecovery(!!QtRecovery.loadApproval(sessionStorage, actorId, bookId)); } catch { /* failure shown below */ }
        }
        showFailure(error, reviewCurrent, stateRef.current.generation);
      }
    });
  }
  function retryApproval() {
    if (!hasApprovalRecovery) return;
    let original: ReturnType<typeof QtRecovery.loadApproval>;
    try { original = QtRecovery.loadApproval(sessionStorage, actorId, bookId); }
    catch (error) { setMessage(problem(error).message); return; }
    if (!original) return;
    // A newer discovered request cannot replace the identity being explicitly recovered.
    const expected = reviewedDecision?.request_id === original.request_id ? reviewedDecision :
      visible.decision?.request_id === original.request_id ? visible.decision : null;
    const preview = expected === reviewedDecision ? reviewedPreview : expected ? visible.preview : null;
    const linked = (value: QtDecision) => value.book_id === bookId && value.request_id === original.request_id &&
      (!original.decision_id || value.decision_id === original.decision_id) &&
      (!preview || (!!expected && value.decision_id === expected.decision_id && qtDecisionMatchesPreview(value, preview)));
    void runOneWrite(async stillCurrent => {
      const reviewCurrent = () => stillCurrent() && activeReviewScope.current === reviewScope;
      try {
        const updated = await QtRecovery.retryApproval(sessionStorage, actorId, bookId, reviewCurrent, linked);
        if (reviewCurrent() && updated) {
          applyDecision(updated);
          setHasApprovalRecovery(!!QtRecovery.loadApproval(sessionStorage, actorId, bookId));
          if (updated.approvals.some(approval => approval.user_id === actorId))
            setMessage(`Approval request ${original.request_id} acknowledged by the server. Refresh QT source to resume editing.`);
        }
      } catch (error) { showFailure(error, reviewCurrent, stateRef.current.generation); }
    });
  }

  return <section aria-label="QT proposal workspace">
    <h2>QT proposal for {bookId}</h2><p>Source day {sourceDay}</p>
    {message && <p role="alert">{message}</p>}
    {proposal && <p>Source: {proposal.workflow_state}. {proposal.read_only_reason ?? ''}</p>}
    {draft && <p>Draft revision {draft.draft_revision} ({draft.state})</p>}
    {!proposal && !message && <p role="status">Loading QT source</p>}
    {verifiedEmptySelection && <section aria-label="Verified empty selection">
      <p>No positions for {proposal?.empty_owner?.configured_owner_names[0]}. Save this empty choice, then evaluate and confirm it.</p>
      {draft?.state === 'consumed' && <p>Your previous choice was processed. Save to start a new choice; the previous decision remains in the audit history.</p>}
    </section>}
    {proposal && <QtSelectionTable sourceRows={sourceRows} chosenRows={chosenRows} previousQtRows={proposal.saved_qt_rows} selection={visible.selection}
      onEdit={edit} locked={!sourceReady || !draft || !proposal.action_grants.can_save_draft || !editorAllowsEdit || !!decision} />}
    {proposal && <div>
      <button type="button" onClick={save} disabled={!canSave}>Save draft</button>
      <button type="button" onClick={evaluate} disabled={!canEvaluate}>Evaluate my selection</button>
      {!sourceReady && <p>QT actions are unavailable until current source and grants are ready.</p>}
      {!validSelection && <p>Enter valid exact quantities before saving.</p>}
      {!savedSelection && <p>Save the current selection before evaluation.</p>}
    </div>}
    {visible.preview && <QtPreviewEvidence preview={visible.preview} />}
    {visible.preview && !decision && <button type="button" onClick={confirm} disabled={!canConfirm}>
      {visible.preview.requires_override ? 'Confirm and request two approvals' : 'Confirm these quantities'}
    </button>}
    {hasConfirmationRecovery && <button type="button" disabled={busy || revoked} onClick={recover}>Recover confirmation</button>}
    {hasConfirmationRecovery && decision?.status === 'confirmed_decision' &&
      (decision.receipt?.status === 'processed' || decision.receipt?.status === 'failed') &&
      <button type="button" disabled={busy || revoked} onClick={acknowledgeResolvedConfirmation}>
        Acknowledge resolved confirmation
      </button>}
    {hasApprovalRecovery && <button type="button" disabled={busy || revoked} onClick={retryApproval}>Retry approval</button>}
    {review?.scope === reviewScope && review.status === 'unavailable' && <p role="alert">Decision review unavailable. Refresh to load current server evidence.</p>}
    {reviewedDecision && reviewedPreview && <section aria-label="Immutable QT decision review">
      <h3>Immutable QT decision review</h3><p>Server decision for {bookId}, source day {sourceDay}. These quantities are immutable.</p>
      <QtSelectionTable sourceRows={sourceRows} chosenRows={reviewedPreview.selection_rows}
        previousQtRows={proposal?.saved_qt_rows} selection={{}} onEdit={() => {}} locked
        tableLabel="Reviewed QT decision quantities" />
      <QtPreviewEvidence preview={reviewedPreview} />
      <QtDecisionStatus decision={reviewedDecision} phase={decisionPhase(reviewedDecision)} verifiedContext
        approvalAllowed={approvalGrant && !hasApprovalRecovery} onRefresh={() => setDecisionRefresh(index => index + 1)}
        onApprove={approveDiscovered} busy={busy || revoked} />
    </section>}
    <button type="button" disabled={busy} onClick={() => setDecisionRefresh(index => index + 1)}>Refresh discovered decision</button>
    <QtDecisionStatus decision={reviewedDecision?.decision_id === decision?.decision_id ? null : decision}
      phase={phase} verifiedContext={!!visible.decision} approvalAllowed={approvalGrant && !hasApprovalRecovery}
      onRefresh={refreshDecision} onApprove={approve} busy={busy || revoked} />
    {message && <button type="button" onClick={() => setRefreshIndex(index => index + 1)}>Refresh QT source</button>}
  </section>;
}
