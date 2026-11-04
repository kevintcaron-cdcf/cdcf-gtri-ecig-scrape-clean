-- DROP SCHEMA dbo;

CREATE SCHEMA dbo;
-- OnlineTobaccoScrape.dbo.ecig_product definition

-- Drop table

-- DROP TABLE OnlineTobaccoScrape.dbo.ecig_product;

CREATE TABLE OnlineTobaccoScrape.dbo.ecig_product (
	id int IDENTITY(1,1) NOT NULL,
	product_name nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	site_name nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	url nvarchar(4000) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	site_category nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	site_tag nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	sku nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	brand nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	html nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	plain_text nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	price nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	price_sale nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	flavor_text nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	description nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	package_contents nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	ingredients nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	warnings nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	eliquid_contents nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	puffs nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	coil nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	battery_text nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	power_level nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	nicotine_level_text nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	stock_status nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	date_inserted datetime2 DEFAULT getdate() NULL,
	date_updated datetime2 DEFAULT getdate() NULL,
	features nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	CONSTRAINT PK_ecig_product PRIMARY KEY (id),
	CONSTRAINT ecig_product_unique UNIQUE (url)
);

-- A compact, tracker-independent record of retailer-facing product changes.
-- HTML and plain_text are purposefully not stored here.
CREATE TABLE OnlineTobaccoScrape.dbo.ecig_product_history (
	id bigint IDENTITY(1,1) NOT NULL,
	product_id int NOT NULL,
	changed_fields nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
	product_name nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	description nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	site_category nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	package_contents nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	ingredients nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	eliquid_contents nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	puffs nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	coil nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	battery_text nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	power_level nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	nicotine_level_text nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	stock_status nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	features nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	date_inserted datetime2 NOT NULL DEFAULT getdate(),
	CONSTRAINT PK_ecig_product_history PRIMARY KEY (id),
	CONSTRAINT FK_ecig_product_history_ProductId FOREIGN KEY (product_id) REFERENCES OnlineTobaccoScrape.dbo.ecig_product(id)
);
CREATE INDEX IX_ecig_product_history_product_date
	ON OnlineTobaccoScrape.dbo.ecig_product_history (product_id, date_inserted DESC);


-- OnlineTobaccoScrape.dbo.ecig_colors definition

-- Drop table

-- DROP TABLE OnlineTobaccoScrape.dbo.ecig_colors;

CREATE TABLE OnlineTobaccoScrape.dbo.ecig_colors (
	id int IDENTITY(1,1) NOT NULL,
	product_id int NULL,
	color_name nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	color_description nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	date_inserted datetime2 DEFAULT getdate() NULL,
	date_updated datetime2 DEFAULT getdate() NULL,
	CONSTRAINT PK_ecig_colors PRIMARY KEY (id),
	CONSTRAINT FK_ecig_colors_ProductId FOREIGN KEY (product_id) REFERENCES OnlineTobaccoScrape.dbo.ecig_product(id)
);


-- OnlineTobaccoScrape.dbo.ecig_flavors definition

-- Drop table

-- DROP TABLE OnlineTobaccoScrape.dbo.ecig_flavors;

CREATE TABLE OnlineTobaccoScrape.dbo.ecig_flavors (
	id int IDENTITY(1,1) NOT NULL,
	product_id int NULL,
	flavor_name nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	flavor_description nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	flavor_category nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	iced_bool bit NULL,
	cbd_bool bit NULL,
	date_inserted datetime2 DEFAULT getdate() NULL,
	date_updated datetime2 DEFAULT getdate() NULL,
	CONSTRAINT PK_ecig_flavors PRIMARY KEY (id),
	CONSTRAINT FK_ecig_flavors_ProductId FOREIGN KEY (product_id) REFERENCES OnlineTobaccoScrape.dbo.ecig_product(id)
);


-- OnlineTobaccoScrape.dbo.ecig_images definition

-- Drop table

-- DROP TABLE OnlineTobaccoScrape.dbo.ecig_images;

CREATE TABLE OnlineTobaccoScrape.dbo.ecig_images (
	id int IDENTITY(1,1) NOT NULL,
	product_id int NULL,
	url nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	[path] nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	title nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	alt_text nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	date_inserted datetime2 DEFAULT getdate() NULL,
	date_updated datetime2 DEFAULT getdate() NULL,
	iced_bool bit NULL,
	has_screen_bool bit NULL,
	CONSTRAINT PK_ecig_images PRIMARY KEY (id),
	CONSTRAINT FK_ecig_images_ProductId FOREIGN KEY (product_id) REFERENCES OnlineTobaccoScrape.dbo.ecig_product(id)
);


-- OnlineTobaccoScrape.dbo.ecig_nicotine_levels definition

-- Drop table

-- DROP TABLE OnlineTobaccoScrape.dbo.ecig_nicotine_levels;

CREATE TABLE OnlineTobaccoScrape.dbo.ecig_nicotine_levels (
	id int IDENTITY(1,1) NOT NULL,
	product_id int NULL,
	value float NULL,
	unit nvarchar(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	date_inserted datetime2 DEFAULT getdate() NULL,
	date_updated datetime2 DEFAULT getdate() NULL,
	CONSTRAINT PK_ecig_nicotine_levels PRIMARY KEY (id),
	CONSTRAINT FK_ecig_nicotine_levels_ProductId FOREIGN KEY (product_id) REFERENCES OnlineTobaccoScrape.dbo.ecig_product(id)
);


-- OnlineTobaccoScrape.dbo.ecig_product_attributes definition

-- Drop table

-- DROP TABLE OnlineTobaccoScrape.dbo.ecig_product_attributes;

CREATE TABLE OnlineTobaccoScrape.dbo.ecig_product_attributes (
	id int IDENTITY(1,1) NOT NULL,
	product_id int NULL,
	total_ounces_per_ml float NULL,
	product_category nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	screen_bool bit NULL,
	disposable_bool bit NULL,
	rechargeable_bool bit NULL,
	battery_bool bit NULL,
	usb_bool bit NULL,
	adjustable_bool bit NULL,
	tfn_bool bit NULL,
	nic_free nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	date_inserted datetime2 DEFAULT getdate() NULL,
	date_updated datetime2 DEFAULT getdate() NULL,
	eliquid_content nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	CONSTRAINT PK_ecig_product_attributes PRIMARY KEY (id),
	CONSTRAINT UQ_ecig_product_attributes_product_id UNIQUE (product_id),
	CONSTRAINT FK_ecig_product_attributes_ProductId FOREIGN KEY (product_id) REFERENCES OnlineTobaccoScrape.dbo.ecig_product(id)
);


-- OnlineTobaccoScrape.dbo.ecig_review_attributes definition

-- Drop table

-- DROP TABLE OnlineTobaccoScrape.dbo.ecig_review_attributes;

CREATE TABLE OnlineTobaccoScrape.dbo.ecig_review_attributes (
	id int IDENTITY(1,1) NOT NULL,
	product_id int NULL,
	review_attribute_question nvarchar(4000) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	review_attribute_value nvarchar(4000) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	date_inserted datetime2 DEFAULT getdate() NULL,
	date_updated datetime2 DEFAULT getdate() NULL,
	CONSTRAINT PK_ecig_review_attributes PRIMARY KEY (id),
	CONSTRAINT FK_ecig_review_attributes_ProductId FOREIGN KEY (product_id) REFERENCES OnlineTobaccoScrape.dbo.ecig_product(id)
);
 CREATE UNIQUE NONCLUSTERED INDEX UQ_ecig_review_attributes_product_id_question ON OnlineTobaccoScrape.dbo.ecig_review_attributes (  product_id ASC  , review_attribute_question ASC  )  
	 WITH (  PAD_INDEX = OFF ,FILLFACTOR = 100  ,SORT_IN_TEMPDB = OFF , IGNORE_DUP_KEY = OFF , STATISTICS_NORECOMPUTE = OFF , ONLINE = OFF , ALLOW_ROW_LOCKS = ON , ALLOW_PAGE_LOCKS = ON  )
	 ON [PRIMARY ] ;


-- OnlineTobaccoScrape.dbo.ecig_reviews definition

-- Drop table

-- DROP TABLE OnlineTobaccoScrape.dbo.ecig_reviews;

CREATE TABLE OnlineTobaccoScrape.dbo.ecig_reviews (
	id int IDENTITY(1,1) NOT NULL,
	product_id int NULL,
	review_date date NULL,
	rating float NULL,
	author nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	verified bit NULL,
	review_text nvarchar(MAX) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	date_inserted datetime2 DEFAULT getdate() NULL,
	date_updated datetime2 DEFAULT getdate() NULL,
	variant nvarchar(255) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
	sweet_level int NULL,
	iced_level int NULL,
	CONSTRAINT PK_ecig_reviews PRIMARY KEY (id),
	CONSTRAINT FK_ecig_reviews_ProductId FOREIGN KEY (product_id) REFERENCES OnlineTobaccoScrape.dbo.ecig_product(id)
);
 CREATE UNIQUE NONCLUSTERED INDEX UQ_ecig_reviews_KeyColumns ON OnlineTobaccoScrape.dbo.ecig_reviews (  review_date ASC  , author ASC  , variant ASC  , rating ASC  )  
	 WITH (  PAD_INDEX = OFF ,FILLFACTOR = 100  ,SORT_IN_TEMPDB = OFF , IGNORE_DUP_KEY = OFF , STATISTICS_NORECOMPUTE = OFF , ONLINE = OFF , ALLOW_ROW_LOCKS = ON , ALLOW_PAGE_LOCKS = ON  )
	 ON [PRIMARY ] ;


-- dbo.product_attributes_view source

ALTER   VIEW dbo.product_attributes_view
AS
SELECT
    er.product_id,
    ep.product_name,
    ep.site_name,
    ep.url,
    ep.site_category,
    ep.site_tag,
    ep.price,
    ep.description,
    ep.package_contents,
    ep.eliquid_contents,
    ep.puffs,
    ep.battery_text,
    ep.nicotine_level_text,
    q2.flavors,
    er.total_ounces_per_ml,
    er.product_category,
    er.screen_bool,
    er.disposable_bool,
    er.battery_bool,
    er.usb_bool,
    er.adjustable_bool,
    er.tfn_bool,
    er.nic_free,
    er.eliquid_content
FROM
    dbo.ecig_product_attributes AS er
INNER JOIN
    dbo.ecig_product AS ep ON ep.id = er.product_id
LEFT JOIN
    (
        SELECT
            f.product_id,
            STRING_AGG(CAST(f.flavor_name AS NVARCHAR(MAX)), N', ') AS flavors
        FROM
            dbo.ecig_flavors AS f
        GROUP BY
            f.product_id
    ) AS q2 ON q2.product_id = ep.id;


-- Note: The ORDER BY ep.product_name clause was removed as it's generally not supported
-- or is ignored in SQL Server view definitions without TOP/OFFSET.
-- Apply ordering when selecting from the view, e.g.:
-- SELECT * FROM dbo.product_attributes_view ORDER BY product_name;


-- dbo.review_attributes_view source

ALTER   VIEW dbo.review_attributes_view
AS
SELECT
    ep.product_name,
    ep.site_name,
    ep.url,
    ep.site_category,
    ep.site_tag,
    ep.price,
    ep.description,
    ep.package_contents,
    ep.eliquid_contents,
    ep.puffs,
    ep.battery_text,
    ep.nicotine_level_text,
    q2.flavors,
    TRY_CAST(q1.sweet_level AS FLOAT) / 4.0 * 100.0 AS sweet_percentage,
    TRY_CAST(q1.iced_level AS FLOAT) / 4.0 * 100.0 AS iced_percentage
FROM
    dbo.ecig_product AS ep
LEFT JOIN
    (
        SELECT
            era.product_id,
            MAX(
                CASE
                    WHEN CAST(era.review_attribute_question AS NVARCHAR(MAX)) = N'Ice Level' THEN era.review_attribute_value
                    ELSE NULL
                END
            ) AS iced_level,
            MAX(
                CASE
                    WHEN CAST(era.review_attribute_question AS NVARCHAR(MAX)) = N'Sweet Level' THEN era.review_attribute_value
                    ELSE NULL
                END
            ) AS sweet_level
        FROM
            dbo.ecig_review_attributes AS era
        GROUP BY
            era.product_id
    ) AS q1 ON q1.product_id = ep.id
LEFT JOIN
    (
        SELECT
            f.product_id,
            STRING_AGG(CAST(f.flavor_name AS NVARCHAR(MAX)), N', ') AS flavors
        FROM
            dbo.ecig_flavors AS f
        GROUP BY
            f.product_id
    ) AS q2 ON q2.product_id = ep.id;


-- Note: The ORDER BY ep.product_name clause was removed.
-- Apply ordering when selecting from the view, e.g.:
-- SELECT * FROM dbo.review_attributes_view ORDER BY product_name;


-- dbo.reviews_view source

ALTER   VIEW dbo.reviews_view
AS
SELECT
    er.review_date,
    er.sweet_level,
    er.iced_level,
    (CAST(er.sweet_level AS FLOAT) / 4.0) * 100.0 AS sweet_percentage,
    (CAST(er.iced_level AS FLOAT) / 4.0) * 100.0 AS iced_percentage,
    er.rating,
    er.author,
    er.verified,
    er.review_text,
    ep.product_name,
    ep.site_name,
    ep.url,
    ep.site_category,
    ep.site_tag,
    ep.price,
    ep.description,
    ep.package_contents,
    ep.eliquid_contents,
    ep.puffs,
    ep.battery_text,
    ep.nicotine_level_text,
    q2.flavors
FROM
    dbo.ecig_reviews AS er
INNER JOIN
    dbo.ecig_product AS ep ON ep.id = er.product_id
LEFT JOIN
    (
        SELECT
            f.product_id,
            STRING_AGG(CAST(f.flavor_name AS NVARCHAR(MAX)), N', ') AS flavors
        FROM
            dbo.ecig_flavors AS f
        GROUP BY
            f.product_id
    ) AS q2 ON q2.product_id = ep.id;

-- Note: The ORDER BY ep.product_name, er.review_date clause was removed.
-- Apply ordering when selecting from the view, e.g.:
-- SELECT * FROM dbo.reviews_view ORDER BY product_name, review_date;
