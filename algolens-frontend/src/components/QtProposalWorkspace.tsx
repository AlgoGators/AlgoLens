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
import { qtStyles, useQtDark, type QtTone } from './qt-proposal/qtStyles';

type Props = {
  actorId: string; actorLabel?: string; bookId: string; sourceDay: string; onPublished: () => void;
  /**
   * True when the workspace sits inside the QT edit dialog: the dialog draws the
   * border, rounding, padding and background, so the workspace keeps only its
   * own vertical spacing. The dialog also owns scrolling and focus.
   */
  embedded?: boolean;
  /**
   * The strategy the reader opened this window from. A book is shared by several
   * strategies but has one MODEL owner per day; when every row of this strategy
   * is a locked holding while another strategy's rows are editable, the quantity section
   * says so instead of leaving the locked boxes unexplained. Presentation only.
   */
  focusStrategyName?: string;
};
const sameName = (a: string, b: string) => {
  const flat = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, '');
  return flat(a) !== '' && flat(a) === flat(b);
};
/** Names the editable strategies when the focus strategy's own rows are all locked; otherwise null. */
function focusLockedNote(rows: QtSelectionRow[], focus: string | undefined): string | null {
  if (!focus) return null;
  const own = rows.filter(row => sameName(row.key.strategy_name, focus));
  if (own.length === 0 || own.some(row => row.editable)) return null;
  const owners = [...new Set(rows.filter(row => row.editable).map(row => row.key.strategy_name))];
  if (owners.length === 0) return null;
  const names = owners.join(' and ');
  return `${focus} cannot be changed in this window: this book's QT desk feed comes from ${names}, ` +
    `so ${focus}'s positions are shown as locked holdings. You can change ${names}'s quantities here.`;
}
function selectionRows(rows: QtSelectionRow[], selection: Readonly<Record<string, string>>) {
  return rows.filter(row => row.editable).map(row => ({
    key: row.key, quantity_exact: normalizeQtSelectionInput(selection[qtComponentKey(row.key)] ?? row.quantity_exact, row.asset_type),
  }));
}
function matchesSaved(rows: QtSelectionRow[], selection: Readonly<Record<string, string>>): boolean {
  return rows.every(row => selection[qtComponentKey(row.key)] === row.quantity_exact) &&
    Object.keys(selection).length === rows.length;
}
// Equal by value, the way the save will write it ("4.0" is 4); text that cannot be read as a quantity yet is different.
function sameQuantity(chosen: string, model: string, assetType: QtSelectionRow['asset_type']): boolean {
  try { return normalizeQtSelectionInput(chosen, assetType) === model; } catch { return false; }
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

export function QtProposalWorkspace({ actorId, actorLabel, bookId, sourceDay, onPublished, embedded = false, focusStrategyName }: Props) {
  const context = qtContextKey(actorId, bookId, sourceDay);
  const ui = qtStyles(useQtDark());
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
  const [rationale, setRationale] = useState('');
  const [savedRationale, setSavedRationale] = useState<string | null>(null);
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
    setRationale(''); setSavedRationale(null);
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
        setRationale(draft.rationale ?? '');
        setSavedRationale(draft.rationale);
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
  // A decision the server already holds for this book and day is shown in the immutable review.
  // While it is still in flight (waiting for approvals, or confirmed and being processed) the
  // choice above it can no longer change, so the boxes and the write buttons close. Once it has
  // finished (processed, report-blocked or failed) a reader may start a new choice, so nothing
  // locks; the quantity section says so. A verified empty selection has no boxes and may always start a new
  // choice, so a discovered decision does not change what it says. The backend stays the
  // authority either way: this only stops offering an edit that could not take effect.
  const reviewedPhase = reviewedDecision ? decisionPhase(reviewedDecision) : null;
  const reviewedInFlight = reviewedPhase === 'pending_override' || reviewedPhase === 'processing';
  const decisionExists = !!decision || (reviewedInFlight && !verifiedEmptySelection);
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
  const rationaleTrimmed = rationale.trim();
  const rationaleBytes = new TextEncoder().encode(rationaleTrimmed).length;
  const validRationale = rationaleBytes > 0 && rationaleBytes <= 1000;
  const rationaleMatchesSaved = savedRationale !== null && rationaleTrimmed === savedRationale;
  const sourceReady = proposal?.workflow_state === 'ready' && proposal.capability.available && !revoked;
  const editorAllowsEdit = reduceQtState(visible,
    { type: 'edited', context, selection: visible.selection }) !== visible;
  const canSave = !!sourceReady && !!draft && !!proposal.action_grants.can_save_draft && validSelection && validRationale &&
    visible.phase === 'editing' && !busy && !decisionExists;
  const canEvaluate = !!sourceReady && !!proposal?.action_grants.can_save_draft && validSelection && savedSelection &&
    rationaleMatchesSaved && visible.phase === 'editing' && !busy && !decisionExists;
  const canConfirm = !hasConfirmationRecovery && !busy && !revoked && canConfirmQt(visible);

  function edit(identity: string, value: string) {
    if (!current() || revoked || decisionExists) return;
    const before = stateRef.current;
    const after = send({ type: 'edited', context, selection: { ...before.selection, [identity]: value } });
    if (after !== before) setMessage('');
  }
  function editRationale(value: string) {
    if (!current() || revoked || decisionExists) return;
    setRationale(value);
    const trimmed = value.trim();
    if (visible.preview || (savedRationale !== null && trimmed !== savedRationale)) {
      send({ type: 'edited', context, selection: stateRef.current.selection });
    }
    setMessage('');
  }
  function save() {
    if (!canSave || !proposal) return;
    let rows: ReturnType<typeof selectionRows>;
    try { rows = selectionRows(chosenRows, stateRef.current.selection); }
    catch { setMessage('Enter a valid exact quantity for every editable component. Futures require whole contracts.'); return; }
    void runOneWrite(async stillCurrent => {
      const submittedRationale = rationaleTrimmed;
      const started = send({ type: 'save_started', context, generation: stateRef.current.generation });
      const generation = started.generation;
      try {
        const saved = await QtPreviewApi.saveDraft(bookId, {
          expected_source_digest: proposal.source_digest!, expected_provenance_digest: proposal.provenance_digest!,
          expected_draft_revision: draft?.draft_revision ?? 0, idempotency_key: crypto.randomUUID(), selection_rows: rows,
          rationale: submittedRationale,
        });
        if (stillCurrent()) {
          const accepted = send({ type: 'draft_saved', context, generation, draft: saved });
          if (accepted.draft === saved) setSavedRationale(submittedRationale);
        }
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

  const editableRows = chosenRows.filter(row => row.editable);
  const tableLocked = !sourceReady || !draft || !proposal?.action_grants.can_save_draft || !editorAllowsEdit || decisionExists;
  const modelQuantity = new Map(sourceRows.filter(row => row.origin === 'verified_model_seed')
    .map(row => [qtComponentKey({ ...row.key, portfolio_type: 'qt' }), row.quantity_exact]));
  const changedFromModel = editableRows.filter(row => {
    const chosen = visible.selection[qtComponentKey(row.key)] ?? row.quantity_exact;
    const model = modelQuantity.get(qtComponentKey({ ...row.key, portfolio_type: 'qt' }));
    return model !== undefined && !sameQuantity(chosen, model, row.asset_type);
  }).length;
  const editorNotice = decisionExists ? 'A decision already exists for this source day, so these quantities can no longer be changed. Its review and approvals are shown below.'
    : proposal && (!sourceReady || !proposal.action_grants.can_save_draft) ? 'Editing is unavailable until the current source and your permissions are ready.'
      : proposal && draft && !editorAllowsEdit ? 'Editing is paused right now. Check the messages and status on this page, or refresh the QT source.' : null;
  const previousDecisionNote = !editorNotice && reviewedDecision && !verifiedEmptySelection ?
    `A previous decision for this source day ${reviewedPhase === 'unavailable' ? 'could not be processed' : 'was processed'}. Editing starts a new choice; the previous decision stays in the audit history below.` : null;
  const focusedOwnerNote = !editorNotice ? focusLockedNote(chosenRows, focusStrategyName) : null;
  const sourceTone: QtTone = sourceReady ? 'success' : 'warning';
  const draftTone: QtTone = !draft ? 'neutral' : draft.state === 'saved' ? 'success' : draft.state === 'consumed' ? 'neutral' : 'warning';
  const savePrimary = !savedSelection;
  const hasRecoveryAction = hasConfirmationRecovery || hasApprovalRecovery;

  return <section id="qt-proposal-workspace" tabIndex={-1} aria-label="QT proposal workspace" className={embedded ? ui.panelEmbedded : ui.panel}>
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="space-y-1">
        {/* Inside the dialog its own title is the h2, so this heading drops one level. */}
        {embedded ? <h3 className={ui.panelTitle}>QT proposal for {bookId}</h3> : <h2 className={ui.panelTitle}>QT proposal for {bookId}</h2>}
        <p className={`${ui.body} ${ui.muted}`}>Source day {sourceDay}</p>
      </div>
      {(proposal || draft) && <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        {proposal && <p className={ui.badge(sourceTone)}>Source: {proposal.workflow_state}. {proposal.read_only_reason ?? ''}</p>}
        {draft && <p className={ui.badge(draftTone)}>Draft revision {draft.draft_revision} ({draft.state})</p>}
      </div>}
    </div>
    {message && <p role="alert" className={ui.callout('danger')}>{message}</p>}
    {!proposal && !message && <p role="status" className={`${ui.body} ${ui.muted}`}>Loading QT source</p>}
    {verifiedEmptySelection && <section aria-label="Verified empty selection" className={`space-y-2 ${ui.callout('info')}`}>
      <p>No positions for {proposal?.empty_owner?.configured_owner_names[0]}. Save this empty choice, then evaluate and confirm it.</p>
      {draft?.state === 'consumed' && <p>Your previous choice was processed. Save to start a new choice; the previous decision remains in the audit history.</p>}
    </section>}
    {proposal && <section aria-label="Position change request" className={ui.card}>
      <h4 className={ui.cardTitle}>Change details</h4>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><p className={ui.subTitle}>Authenticated actor</p>
          <p className={ui.body}>{actorLabel || `Account ${actorId}`}</p></div>
        <div><p className={ui.subTitle}>Numerical change</p>
          <p className={ui.body}>{changedFromModel} of {editableRows.length} editable positions differ from MODEL.</p>
          <p className={ui.note}>Exact current, proposed, and signed quantity differences are shown below.</p></div>
      </div>
      <label className="block space-y-1">
        <span className={ui.subTitle}>Why should this position change be made?</span>
        <textarea aria-label="Why should this position change be made?" value={rationale}
          disabled={tableLocked} rows={3} onChange={event => editRationale(event.target.value)}
          className={ui.textarea(tableLocked)} />
      </label>
      <div className="flex flex-wrap justify-between gap-2">
        <p className={validRationale ? ui.note : ui.callout('warning')}>
          {rationaleBytes === 0 ? 'A rationale is required before this draft can be saved.' :
            rationaleBytes > 1000 ? 'Rationale must be 1000 UTF-8 bytes or fewer.' :
              'This rationale is stored with the draft as audit evidence.'}
        </p>
        <p className={ui.note}>{rationaleBytes}/1000 bytes</p>
      </div>
    </section>}
    {proposal && <section aria-label="Position quantities" className={ui.card}>
      <div className="space-y-1">
        <h4 className={ui.cardTitle}>Position quantities</h4>
        <p className={ui.note}>Review the MODEL recommendation, your chosen quantity, and the signed difference.</p>
      </div>
      {editorNotice && <p role="status" className={ui.callout('warning')}>{editorNotice}</p>}
      {previousDecisionNote && <p className={ui.note}>{previousDecisionNote}</p>}
      {focusedOwnerNote && <p role="note" className={`${ui.note} font-medium`}>{focusedOwnerNote}</p>}
      <QtSelectionTable sourceRows={sourceRows} chosenRows={chosenRows} previousQtRows={proposal.saved_qt_rows} selection={visible.selection}
        onEdit={edit} locked={tableLocked} />
      <div className="space-y-3">
        <div className={ui.buttonRow}>
          <button type="button" className={savePrimary ? ui.btnPrimary : ui.btnSecondary} onClick={save} disabled={!canSave}>Save draft</button>
          <button type="button" className={savePrimary ? ui.btnSecondary : ui.btnPrimary} onClick={evaluate} disabled={!canEvaluate}>Evaluate my selection</button>
        </div>
        {!sourceReady && <p className={ui.callout('warning')}>QT actions are unavailable until current source and grants are ready.</p>}
        {!validSelection && <p className={ui.callout('warning')}>Enter valid exact quantities before saving.</p>}
        {!validRationale && <p className={ui.note}>Add a valid rationale before saving.</p>}
        {!savedSelection && <p className={ui.note}>Save the current selection before evaluation.</p>}
        {savedSelection && !rationaleMatchesSaved && <p className={ui.note}>Save this rationale before evaluation.</p>}
      </div>
    </section>}
    {visible.preview && <QtPreviewEvidence preview={visible.preview} />}
    {visible.preview && !decision && <div className={ui.buttonRow}><button type="button"
      className={visible.preview.requires_override ? ui.btnWarning : ui.btnPrimary} onClick={confirm} disabled={!canConfirm}>
      {visible.preview.requires_override ? 'Confirm and request two approvals' : 'Confirm these quantities'}
    </button></div>}
    {hasRecoveryAction && <div className={ui.buttonRow}>
      {hasConfirmationRecovery && <button type="button" className={ui.btnWarning} disabled={busy || revoked} onClick={recover}>Recover confirmation</button>}
      {hasConfirmationRecovery && decision?.status === 'confirmed_decision' &&
        (decision.receipt?.status === 'processed' || decision.receipt?.status === 'failed') &&
        <button type="button" className={ui.btnSecondary} disabled={busy || revoked} onClick={acknowledgeResolvedConfirmation}>
          Acknowledge resolved confirmation
        </button>}
      {hasApprovalRecovery && <button type="button" className={ui.btnWarning} disabled={busy || revoked} onClick={retryApproval}>Retry approval</button>}
    </div>}
    {review?.scope === reviewScope && review.status === 'unavailable' && <p role="alert" className={ui.callout('danger')}>Decision review unavailable. Refresh to load current server evidence.</p>}
    {reviewedDecision && reviewedPreview && <section aria-label="Immutable QT decision review" className={ui.card}>
      <h3 className={ui.cardTitle}>Immutable QT decision review</h3><p className={`${ui.body} ${ui.muted}`}>Server decision for {bookId}, source day {sourceDay}. These quantities are immutable.</p>
      <QtSelectionTable sourceRows={sourceRows} chosenRows={reviewedPreview.selection_rows}
        previousQtRows={proposal?.saved_qt_rows} selection={{}} onEdit={() => {}} locked
        tableLabel="Reviewed QT decision quantities" />
      <QtPreviewEvidence preview={reviewedPreview} />
      <QtDecisionStatus decision={reviewedDecision} phase={decisionPhase(reviewedDecision)} verifiedContext
        approvalAllowed={approvalGrant && !hasApprovalRecovery} onRefresh={() => setDecisionRefresh(index => index + 1)}
        onApprove={approveDiscovered} busy={busy || revoked} />
    </section>}
    <div className={ui.buttonRow}>
      <button type="button" className={ui.btnGhost} disabled={busy} onClick={() => setDecisionRefresh(index => index + 1)}>Refresh discovered decision</button>
    </div>
    <QtDecisionStatus decision={reviewedDecision?.decision_id === decision?.decision_id ? null : decision}
      phase={phase} verifiedContext={!!visible.decision} approvalAllowed={approvalGrant && !hasApprovalRecovery}
      onRefresh={refreshDecision} onApprove={approve} busy={busy || revoked} />
    {message && <div className={ui.buttonRow}>
      <button type="button" className={ui.btnSecondary} onClick={() => setRefreshIndex(index => index + 1)}>Refresh QT source</button>
    </div>}
  </section>;
}
