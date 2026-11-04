BEGIN TRANSACTION;

-- Preview changes before applying them.
SELECT
    id,
    site_name,
    site_category AS old_site_category,
    LTRIM(RTRIM(
        REPLACE(
            REPLACE(
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REPLACE(
                                REPLACE(site_category, '/collections/', ''),
                                '/product-category/', ''
                            ),
                            '/category/', ''
                        ),
                        '/brand/', ''
                    ),
                    '/pages/', ''
                ),
                '/', '-'
            ),
            '.html', ''
        )
    )) AS new_site_category
FROM ecig_product
WHERE site_category LIKE '/%'
   OR site_category LIKE '%collections/%'
   OR site_category LIKE '%product-category/%'
   OR site_category LIKE '%category/%'
   OR site_category LIKE '%brand/%'
   OR site_category LIKE '%pages/%'
   OR site_category LIKE '%.html'
   OR site_category LIKE '%/%';

-- Apply cleanup.
UPDATE ecig_product
SET
    site_category = LTRIM(RTRIM(
        REPLACE(
            REPLACE(
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REPLACE(
                                REPLACE(site_category, '/collections/', ''),
                                '/product-category/', ''
                            ),
                            '/category/', ''
                        ),
                        '/brand/', ''
                    ),
                    '/pages/', ''
                ),
                '/', '-'
            ),
            '.html', ''
        )
    )),
    date_updated = GETDATE()
WHERE site_category LIKE '/%'
   OR site_category LIKE '%collections/%'
   OR site_category LIKE '%product-category/%'
   OR site_category LIKE '%category/%'
   OR site_category LIKE '%brand/%'
   OR site_category LIKE '%pages/%'
   OR site_category LIKE '%.html'
   OR site_category LIKE '%/%';

-- Review the result before committing.
SELECT
    site_name,
    site_category,
    COUNT(*) AS product_count
FROM ecig_product
GROUP BY site_name, site_category
ORDER BY site_name, site_category;

-- Replace COMMIT with ROLLBACK if the preview is not correct.
COMMIT;
