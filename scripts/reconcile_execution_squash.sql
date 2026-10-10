-- Run once against a database that completed the six branch-only execution
-- migrations, after deploying revision 7ad15b1d0b70 and before alembic upgrade.
-- psql -X -v ON_ERROR_STOP=1 -f scripts/reconcile_execution_squash.sql
-- No execution rows are rewritten or deleted.
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF (SELECT count(*) FROM alembic_version WHERE version_num = 'b3d5e7f9a1c2') <> 1
       OR (SELECT count(*) FROM alembic_version) <> 1 THEN
        RAISE EXCEPTION 'expected sole legacy execution revision b3d5e7f9a1c2';
    END IF;
    IF to_regclass('card_execution_generation') IS NULL
       OR to_regclass('execution_outbox') IS NULL
       OR to_regclass('execution_receipt') IS NULL
       OR to_regclass('execution_checklist_projection') IS NULL THEN
        RAISE EXCEPTION 'legacy execution schema is incomplete';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'card_execution_generation'::regclass
                   AND conname = 'pk_card_execution_readiness' AND contype = 'p')
       OR NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'card_execution_generation'::regclass
                      AND conname = 'fk_card_execution_readiness_card_id_card' AND contype = 'f') THEN
        RAISE EXCEPTION 'legacy execution constraints differ from the reviewed schema';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid IN (
        'card_execution_generation'::regclass, 'execution_outbox'::regclass)
        AND NOT tgisinternal) THEN
        RAISE EXCEPTION 'unexpected execution trigger remains';
    END IF;
END $$;

ALTER TABLE card_execution_generation
    RENAME CONSTRAINT pk_card_execution_readiness TO pk_card_execution_generation;
ALTER TABLE card_execution_generation
    RENAME CONSTRAINT fk_card_execution_readiness_card_id_card
    TO fk_card_execution_generation_card_id_card;
UPDATE alembic_version SET version_num = '7ad15b1d0b70'
WHERE version_num = 'b3d5e7f9a1c2';
COMMIT;
