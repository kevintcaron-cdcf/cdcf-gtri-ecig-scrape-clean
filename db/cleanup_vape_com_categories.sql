/* Azure SQL cleanup for existing Vape.com site_category values. */
BEGIN TRANSACTION;

/* Preview the rows that will change. */
SELECT
    id,
    site_category AS old_site_category,
    LTRIM(RTRIM(
        REPLACE(
            REPLACE(
                REPLACE(
                    REPLACE(
                        REPLACE(site_category, 'https://vape.com', ''),
                        'http://vape.com', ''
                    ),
                    '/collections/', ''
                ),
                '/', '-'
            ),
            '.html', ''
        )
    )) AS new_site_category
FROM dbo.ecig_product
WHERE site_name = 'VAPE.COM'
  AND (
      site_category LIKE 'http%'
      OR site_category LIKE '/%'
      OR site_category LIKE '%/collections/%'
      OR site_category LIKE '%.html%'
      OR site_category LIKE '%?%'
  );

/* Apply the cleanup only to Vape.com products. */
UPDATE dbo.ecig_product
SET
    site_category = LTRIM(RTRIM(
        REPLACE(
            REPLACE(
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REPLACE(site_category, '?page=', '-page-'),
                            'https://vape.com', ''
                        ),
                        'http://vape.com', ''
                    ),
                    '/collections/', ''
                ),
                '/', '-'
            ),
            '.html', ''
        )
    )),
    date_updated = GETDATE()
WHERE site_name = 'VAPE.COM'
  AND (
      site_category LIKE 'http%'
      OR site_category LIKE '/%'
      OR site_category LIKE '%/collections/%'
      OR site_category LIKE '%.html%'
      OR site_category LIKE '%?%'
  );

/* Review the final Vape.com category values before committing. */
SELECT
    site_category,
    COUNT(*) AS product_count
FROM dbo.ecig_product
WHERE site_name = 'VAPE.COM'
GROUP BY site_category
ORDER BY product_count DESC, site_category;

/* Replace COMMIT with ROLLBACK if the preview is not correct. */
COMMIT;
