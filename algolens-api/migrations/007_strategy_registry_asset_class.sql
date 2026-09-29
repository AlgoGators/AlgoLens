-- Adds asset_class to trading.strategy_registry so QT can resolve an
-- instrument's asset type from the book's registered strategy when the
-- instrument catalog (metadata.contract_metadata) has no row for it --
-- production's catalog is futures-only today, so any equity book with
-- positions 409s on GET /proposal without this. See DIAGNOSIS-422-1.md.
--
-- This migration does not, and must not, guess a value from strategy_type
-- or the strategy's name: every existing row gets NULL. A NULL asset_class
-- fails closed at the resolver (draft_identity_unresolved), exactly like a
-- symbol the catalog has never heard of, so applying this migration alone
-- changes nothing about which books already work today. An operator sets
-- asset_class explicitly per strategy afterward -- see
-- PRODUCTION-PREREQUISITE.md in this revision.
--
-- Safe to run more than once (ADD COLUMN IF NOT EXISTS).

ALTER TABLE trading.strategy_registry
    ADD COLUMN IF NOT EXISTS asset_class TEXT
        CHECK (asset_class IS NULL OR asset_class IN ('EQUITY', 'FUTURE'));
