CREATE OR ALTER VIEW dbo.vw_ecig_product_summary
AS
WITH image_counts AS
(
    SELECT product_id, COUNT(*) AS image_count
    FROM dbo.ecig_images
    GROUP BY product_id
),
review_counts AS
(
    SELECT product_id, COUNT(*) AS review_count
    FROM dbo.ecig_reviews
    GROUP BY product_id
),
flavor_counts AS
(
    SELECT product_id, COUNT(*) AS flavor_count
    FROM dbo.ecig_flavors
    GROUP BY product_id
),
color_counts AS
(
    SELECT product_id, COUNT(*) AS color_count
    FROM dbo.ecig_colors
    GROUP BY product_id
),
nicotine_counts AS
(
    SELECT product_id, COUNT(*) AS nicotine_level_count
    FROM dbo.ecig_nicotine_levels
    GROUP BY product_id
),
review_attribute_counts AS
(
    SELECT product_id, COUNT(*) AS review_attribute_count
    FROM dbo.ecig_review_attributes
    GROUP BY product_id
),
product_attribute_counts AS
(
    SELECT product_id, COUNT(*) AS product_attribute_count
    FROM dbo.ecig_product_attributes
    GROUP BY product_id
),
product_metrics AS
(
    SELECT
        p.id AS product_id,
        p.site_name,
        p.date_inserted,
        COALESCE(i.image_count, 0) AS image_count,
        COALESCE(r.review_count, 0) AS review_count,
        COALESCE(f.flavor_count, 0) AS flavor_count,
        COALESCE(c.color_count, 0) AS color_count,
        COALESCE(n.nicotine_level_count, 0) AS nicotine_level_count,
        COALESCE(a.review_attribute_count, 0) AS review_attribute_count,
        COALESCE(pa.product_attribute_count, 0) AS product_attribute_count
    FROM dbo.ecig_product AS p
    LEFT JOIN image_counts AS i ON i.product_id = p.id
    LEFT JOIN review_counts AS r ON r.product_id = p.id
    LEFT JOIN flavor_counts AS f ON f.product_id = p.id
    LEFT JOIN color_counts AS c ON c.product_id = p.id
    LEFT JOIN nicotine_counts AS n ON n.product_id = p.id
    LEFT JOIN review_attribute_counts AS a ON a.product_id = p.id
    LEFT JOIN product_attribute_counts AS pa ON pa.product_id = p.id
),
summary AS
(
    SELECT
        COUNT(*) AS product_count,
        CAST(site_name AS nvarchar(255)) AS site,
        SUM(image_count) AS image_count,
        SUM(review_count) AS review_count,
        SUM(flavor_count) AS flavor_count,
        SUM(color_count) AS color_count,
        SUM(nicotine_level_count) AS nicotine_level_count,
        SUM(review_attribute_count) AS review_attribute_count,
        SUM(product_attribute_count) AS product_attribute_count,
        SUM(CASE WHEN image_count > 0 THEN 1 ELSE 0 END) AS products_with_images,
        SUM(CASE WHEN review_count > 0 THEN 1 ELSE 0 END) AS products_with_reviews,
        SUM(CASE WHEN flavor_count > 0 THEN 1 ELSE 0 END) AS products_with_flavors,
        SUM(CASE WHEN color_count > 0 THEN 1 ELSE 0 END) AS products_with_colors,
        SUM(CASE WHEN nicotine_level_count > 0 THEN 1 ELSE 0 END) AS products_with_nicotine_levels,
        SUM(CASE WHEN product_attribute_count > 0 THEN 1 ELSE 0 END) AS products_with_attributes,
        MAX(date_inserted) AS max_date,
        MIN(date_inserted) AS min_date,
        0 AS sort_order
    FROM product_metrics
    GROUP BY site_name

    UNION ALL

    SELECT
        CAST(NULL AS int),
        CAST(N'--------------------' AS nvarchar(255)),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS int),
        CAST(NULL AS datetime2),
        CAST(NULL AS datetime2),
        1

    UNION ALL

    SELECT
        COUNT(*),
        CAST(N'TOTAL' AS nvarchar(255)),
        SUM(image_count),
        SUM(review_count),
        SUM(flavor_count),
        SUM(color_count),
        SUM(nicotine_level_count),
        SUM(review_attribute_count),
        SUM(product_attribute_count),
        SUM(CASE WHEN image_count > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN review_count > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN flavor_count > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN color_count > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN nicotine_level_count > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN product_attribute_count > 0 THEN 1 ELSE 0 END),
        MAX(date_inserted),
        MIN(date_inserted),
        2
    FROM product_metrics
)
SELECT
    product_count,
    site,
    image_count,
    review_count,
    flavor_count,
    color_count,
    nicotine_level_count,
    review_attribute_count,
    product_attribute_count,
    products_with_images,
    products_with_reviews,
    products_with_flavors,
    products_with_colors,
    products_with_nicotine_levels,
    products_with_attributes,
    max_date,
    min_date,
    sort_order
FROM summary;

-- Views do not guarantee row order. Use this query for the intended visual order:
-- sites by product count descending, then the separator, then TOTAL.
-- SELECT *
-- FROM dbo.vw_ecig_product_summary
-- ORDER BY sort_order, product_count DESC, site;
