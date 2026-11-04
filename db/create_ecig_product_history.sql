-- Apply this migration to an existing Azure SQL database.
IF OBJECT_ID(N'dbo.ecig_product_history', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ecig_product_history (
        id bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
        product_id int NOT NULL,
        changed_fields nvarchar(MAX) NOT NULL,
        product_name nvarchar(MAX) NULL,
        description nvarchar(MAX) NULL,
        site_category nvarchar(MAX) NULL,
        package_contents nvarchar(MAX) NULL,
        ingredients nvarchar(MAX) NULL,
        eliquid_contents nvarchar(MAX) NULL,
        puffs nvarchar(MAX) NULL,
        coil nvarchar(MAX) NULL,
        battery_text nvarchar(MAX) NULL,
        power_level nvarchar(MAX) NULL,
        nicotine_level_text nvarchar(MAX) NULL,
        stock_status nvarchar(MAX) NULL,
        features nvarchar(MAX) NULL,
        date_inserted datetime2 NOT NULL DEFAULT getdate(),
        CONSTRAINT FK_ecig_product_history_ProductId
            FOREIGN KEY (product_id) REFERENCES dbo.ecig_product(id)
    );
    CREATE INDEX IX_ecig_product_history_product_date
        ON dbo.ecig_product_history (product_id, date_inserted DESC);
END;

-- Historical rows for existing products are seeded lazily by
-- sync_ecig_product_history on their next scrape. This keeps migration time
-- short and avoids touching records that are not being actively monitored.
