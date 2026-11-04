BEGIN TRANSACTION;

-- Preview the affected Vape.com rows.
SELECT
    id,
    site_category AS old_site_category,
    CASE
        WHEN site_category LIKE 'https:--vape.com-collections-%'
            THEN SUBSTRING(site_category, LEN('https:--vape.com-collections-') + 1, 255)
        WHEN site_category LIKE 'https:--www.vape.com-collections-%'
            THEN SUBSTRING(site_category, LEN('https:--www.vape.com-collections-') + 1, 255)
        ELSE site_category
    END AS new_site_category
FROM dbo.ecig_product
WHERE site_name = 'VAPE.COM'
  AND (
      site_category LIKE 'https:--vape.com-collections-%'
      OR site_category LIKE 'https:--www.vape.com-collections-%'
  );

-- Apply the cleanup only to Vape.com products.
UPDATE dbo.ecig_product
SET
    site_category = CASE
        WHEN site_category LIKE 'https:--vape.com-collections-%'
            THEN SUBSTRING(site_category, LEN('https:--vape.com-collections-') + 1, 255)
        WHEN site_category LIKE 'https:--www.vape.com-collections-%'
            THEN SUBSTRING(site_category, LEN('https:--www.vape.com-collections-') + 1, 255)
        ELSE site_category
    END,
    date_updated = GETDATE()
WHERE site_name = 'VAPE.COM'
  AND (
      site_category LIKE 'https:--vape.com-collections-%'
      OR site_category LIKE 'https:--www.vape.com-collections-%'
  );

-- Verify the resulting Vape.com categories.
SELECT
    site_category,
    COUNT(*) AS product_count
FROM dbo.ecig_product
WHERE site_name = 'VAPE.COM'
GROUP BY site_category
ORDER BY product_count DESC, site_category;

-- Replace COMMIT with ROLLBACK if the preview is not correct.
COMMIT;
