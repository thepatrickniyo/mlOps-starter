-- Step 1 (metadata-only): add nullable column first to avoid table rewrite and long lock.
ALTER TABLE visit_invoices
ADD COLUMN IF NOT EXISTS billing_status VARCHAR(20);

-- Step 2 (data migration): backfill existing rows in small chunks.
-- This avoids a single huge UPDATE that can bloat WAL and block vacuum.
DO $$
DECLARE
    rows_updated INTEGER := 1;
BEGIN
    WHILE rows_updated > 0 LOOP
        WITH batch AS (
            SELECT ctid
            FROM visit_invoices
            WHERE billing_status IS NULL
            LIMIT 10000
        )
        UPDATE visit_invoices v
        SET billing_status = 'pending'
        FROM batch
        WHERE v.ctid = batch.ctid;

        GET DIAGNOSTICS rows_updated = ROW_COUNT;
        PERFORM pg_sleep(0.05);
    END LOOP;
END $$;

-- Step 3 (enforcement): do not assume backfill was perfect.
-- Add/validate constraint first; set default for new writes; then enforce NOT NULL.
ALTER TABLE visit_invoices
ADD CONSTRAINT visit_invoices_billing_status_nn CHECK (billing_status IS NOT NULL) NOT VALID;

ALTER TABLE visit_invoices
VALIDATE CONSTRAINT visit_invoices_billing_status_nn;

ALTER TABLE visit_invoices
ALTER COLUMN billing_status SET DEFAULT 'pending',
ALTER COLUMN billing_status SET NOT NULL;
