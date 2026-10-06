-- Defense in depth: the decision submitter can never approve its own request,
-- even through direct SQL that bypasses the application service.
BEGIN;

CREATE OR REPLACE FUNCTION trading.qt_reject_submitter_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    submitter_id bigint;
BEGIN
    SELECT decision_row.created_by
      INTO submitter_id
      FROM trading.qt_override_requests AS request_row
      JOIN trading.qt_decisions AS decision_row
        ON decision_row.decision_id = request_row.decision_id
     WHERE request_row.request_id = NEW.request_id;
    IF FOUND AND NEW.user_id = submitter_id THEN
        RAISE EXCEPTION 'QT decision submitter cannot approve the same override request'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS qt_approvals_no_submitter ON trading.qt_override_approvals;
CREATE TRIGGER qt_approvals_no_submitter
    BEFORE INSERT ON trading.qt_override_approvals
    FOR EACH ROW EXECUTE FUNCTION trading.qt_reject_submitter_approval();

COMMIT;
