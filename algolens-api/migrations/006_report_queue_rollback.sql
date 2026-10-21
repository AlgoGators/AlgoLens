-- Rolls back 006_report_queue.sql. Destructive: unsent reports in the queue are lost.
BEGIN;
DROP TABLE IF EXISTS reports.report_queue;
COMMIT;
