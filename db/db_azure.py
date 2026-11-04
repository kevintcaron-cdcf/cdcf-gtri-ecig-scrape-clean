import pyodbc
from dotenv import load_dotenv
import os
import traceback
import time
import hashlib


# Load environment variables from .env file
load_dotenv(os.path.join(os.getcwd(), ".env"))


# Database connection parameters for Azure SQL Database
print('AZURE DBSERVER', os.getenv('DB_HOST'))
db_params = {
    'server': os.getenv('DB_HOST'),      # your-server.database.windows.net
    'database': os.getenv('DB_NAME'),      # database name
    'username': os.getenv('DB_USER'),      # username
    'password': os.getenv('DB_PASSWORD'),  # password
    'driver': os.getenv('DB_DRIVER', '{ODBC Driver 18 for SQL Server}'),  # ODBC driver
    'encrypt': os.getenv('DB_ENCRYPT', 'yes'),
    'trust_server_certificate': 'no',  # Always 'no' for Azure SQL Database
    'connection_timeout': os.getenv('DB_CONNECTION_TIMEOUT', '30')
}
DB_CONNECT_RETRIES = 3
DB_RETRY_DELAY = 2

# Build connection string
def get_connection_string():
    return (
        f"DRIVER={db_params['driver']};"
        f"SERVER={db_params['server']};"
        f"DATABASE={db_params['database']};"
        f"UID={db_params['username']};"
        f"PWD={db_params['password']};"
        f"Encrypt={db_params['encrypt']};"
        f"TrustServerCertificate={db_params['trust_server_certificate']};"
        f"Connection Timeout={db_params['connection_timeout']};"
    )

# Function to connect to Azure SQL Database
def connect():
    """Connect with bounded retries for transient connection exhaustion."""
    connection_string = get_connection_string()
    last_error = None
    for attempt in range(DB_CONNECT_RETRIES):
        try:
            return pyodbc.connect(connection_string)
        except Exception as error:
            last_error = error
            if attempt + 1 < DB_CONNECT_RETRIES:
                delay = DB_RETRY_DELAY * (2 ** attempt)
                print(f"Azure connection failed; retrying in {delay}s ({attempt + 1}/{DB_CONNECT_RETRIES})")
                time.sleep(delay)
    print(f"Error connecting to Azure database after {DB_CONNECT_RETRIES} attempts: {last_error}")
    raise last_error

# sites
CS_VAPE = "CS_VAPE"
GETPOP = "GETPOP"
MY_VAPOR_STORE = "MY_VAPOR_STORE"
PERFECT_VAPE = "PERFECT_VAPE"
VAPE_DOT_COM = "VAPE.COM"
VAPE_SOURCING = "VAPE_SOURCING"
VAPE_WH = "VAPE_WH"
VAPING_DOT_COM = "VAPING.COM"
VAPOR_DNA = "VAPOR_DNA"
VAPORFI = "VAPORFI"
ECIGMAFIA = "ECIGMAFIA"
ELEMENT_VAPE = "ELEMENT_VAPE"
MIPOD = "MIPOD"
GOPUFF = "GOPUFF"
HUFF_AND_PUFFERS = "HUFF_AND_PUFFERS"
VAPE_JUICE_DEPOT = "VAPE_JUICE_DEPOT"
PRILLA = "PRILLA"
NICOKICK = "NICOKICK"
NORTHERNER = "NORTHERNER"
ALP_POUCH = "ALP_POUCH"
SESH_PRODUCTS = "SESH_PRODUCTS"
JUICE_HEAD = "JUICE_HEAD"
OUTLAW_DIP = "OUTLAW_DIP"
SPREE_BAR_SALES = "SPREE_BAR_SALES"
WEST_COAST_VAPE_SUPPLY = "WEST_COAST_VAPE_SUPPLY"
NIC_POUCHES_US = "NIC_POUCHES_US"


def get_product_id(site_name, site_tag):
    connection = None
    cursor = None
    try:
        connection = connect()  # Use our connect() function
        cursor = connection.cursor()
        
        query = """
            SELECT id
            FROM ecig_product
            WHERE site_name = ? AND site_tag = ?
        """
        
        cursor.execute(query, (site_name, site_tag))
        one = cursor.fetchone()
        if one:
            val = one[0]
        else:
            val = None
        
    except Exception as error:
        print(f"Error finding product in Azure db: {error}")
        traceback.print_exc()
        val = None
    finally:
        if cursor:
            cursor.close()
        if connection:  
            connection.close()
    return val


def update_ecig_product_metadata(product_id, sku=None, stock_status=None):
    """Fill missing parsed metadata without replacing existing values."""
    connection = None
    cursor = None
    try:
        connection = connect()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE ecig_product
            SET sku = COALESCE(NULLIF(sku, ''), ?),
                stock_status = COALESCE(NULLIF(stock_status, ''), ?),
                date_updated = GETDATE()
            WHERE id = ?
            """,
            (sku, stock_status, product_id),
        )
        connection.commit()
    except Exception as error:
        print(f"Azure metadata update Error: {error}")
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


PRODUCT_HISTORY_FIELDS = (
    'product_name',
    'description',
    'site_category',
    'package_contents',
    'ingredients',
    'eliquid_contents',
    'puffs',
    'coil',
    'battery_text',
    'power_level',
    'nicotine_level_text',
    'stock_status',
    'features',
)


def _tracked_product_values(data):
    """Map scraper output to the current product/history field names."""
    return {
        'product_name': data.get('title'),
        'description': data.get('description'),
        'site_category': data.get('site_category'),
        'package_contents': data.get('package_contents'),
        'ingredients': data.get('ingredients'),
        'eliquid_contents': data.get('eliquid_contents'),
        'puffs': data.get('puffs'),
        'coil': data.get('coil'),
        'battery_text': data.get('battery'),
        'power_level': data.get('power_level'),
        'nicotine_level_text': data.get('nicotine_strength'),
        'stock_status': data.get('stock_status'),
        'features': data.get('features'),
    }


def _comparable_product_value(value):
    """Avoid a history row for whitespace-only scraper differences."""
    return value.strip() if isinstance(value, str) else value


def sync_ecig_product_history(product_id, data, cursor=None):
    """Update tracked product fields and snapshot them when they change.

    HTML and plain text are intentionally excluded.  Empty scraper values do
    not replace an existing value, because a missing detail-page element is not
    evidence that the retailer removed previously observed product metadata.
    The caller can pass an existing cursor to keep this work in its transaction.
    """
    owns_connection = cursor is None
    connection = None
    product_tag = data.get('tag') or data.get('site_tag') or 'unknown-tag'
    log_prefix = f"\t[{product_tag}] PRODUCT HISTORY"
    try:
        if owns_connection:
            connection = connect()
            cursor = connection.cursor()

        field_list = ', '.join(PRODUCT_HISTORY_FIELDS)
        cursor.execute(
            f"SELECT {field_list} FROM ecig_product WHERE id = ?", (product_id,)
        )
        current_row = cursor.fetchone()
        if not current_row:
            return False
        current = dict(zip(PRODUCT_HISTORY_FIELDS, current_row))
        cursor.execute(
            "SELECT TOP 1 id FROM ecig_product_history WHERE product_id = ?",
            (product_id,),
        )
        has_history = cursor.fetchone() is not None
        inserted_baseline = False
        if not has_history:
            # Existing products predate this table. Seed their current state on
            # the first normal scrape so the next change has a prior snapshot.
            insert_ecig_product_history_snapshot(cursor, product_id, current)
            inserted_baseline = True
            print(f"{log_prefix} baseline inserted for product_id {product_id}")
        incoming = _tracked_product_values(data)

        # Only update values the scraper actually found; stock status is also
        # naturally handled because both In Stock and Out of Stock are nonempty.
        proposed = current.copy()
        changed_fields = []
        for field, value in incoming.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            value = _comparable_product_value(value)
            if _comparable_product_value(current[field]) != value:
                proposed[field] = value
                changed_fields.append(field)

        if not changed_fields:
            if owns_connection and inserted_baseline:
                connection.commit()
            if not inserted_baseline:
                print(f"{log_prefix} unchanged for product_id {product_id}")
            return False

        assignments = ', '.join(f"{field} = ?" for field in changed_fields)
        cursor.execute(
            f"UPDATE ecig_product SET {assignments}, date_updated = GETDATE() WHERE id = ?",
            tuple(proposed[field] for field in changed_fields) + (product_id,),
        )
        history_fields = ', '.join(PRODUCT_HISTORY_FIELDS)
        placeholders = ', '.join('?' for _ in PRODUCT_HISTORY_FIELDS)
        cursor.execute(
            f"""INSERT INTO ecig_product_history
                (product_id, changed_fields, {history_fields})
                VALUES (?, ?, {placeholders})""",
            (product_id, ','.join(changed_fields))
            + tuple(proposed[field] for field in PRODUCT_HISTORY_FIELDS),
        )
        if owns_connection:
            connection.commit()
        print(
            f"{log_prefix} change inserted for product_id {product_id}: "
            f"{', '.join(changed_fields)}"
        )
        return True
    except Exception as error:
        print(f"Azure product history sync Error: {error}")
        if owns_connection and connection:
            connection.rollback()
        return False
    finally:
        if owns_connection:
            if cursor:
                cursor.close()
            if connection:
                connection.close()


def insert_ecig_product_history_snapshot(cursor, product_id, product_data):
    """Store the initial tracked-field snapshot for a newly inserted product."""
    values = {field: product_data.get(field) for field in PRODUCT_HISTORY_FIELDS}
    fields = ', '.join(PRODUCT_HISTORY_FIELDS)
    placeholders = ', '.join('?' for _ in PRODUCT_HISTORY_FIELDS)
    cursor.execute(
        f"""INSERT INTO ecig_product_history
            (product_id, changed_fields, {fields})
            VALUES (?, ?, {placeholders})""",
        (product_id, 'initial') + tuple(values[field] for field in PRODUCT_HISTORY_FIELDS),
    )


def stable_sku(site, site_tag):
    """Return a deterministic fallback SKU when a retailer exposes no SKU."""
    digest = hashlib.sha256(f"{site}:{site_tag}".encode("utf-8")).hexdigest()[:20]
    return f"AUTO-{digest}"


def product_exists(site_name, site_tag):
    connection = None
    cursor = None
    try:
        connection = connect()  # Use our connect() function
        cursor = connection.cursor()
        
        query = """
            SELECT html
            FROM ecig_product
            WHERE site_name = ? AND site_tag = ?
        """
        
        cursor.execute(query, (site_name, site_tag))
        val = cursor.fetchone() is not None
        
    except Exception as error:
        print(f"Error finding product in Azure db: {error}")
        traceback.print_exc()
        val = False
    finally:
        if cursor:
            cursor.close()
        if connection:  
            connection.close()
    return val


def map_product_data(site, data):
    for attempt in range(DB_CONNECT_RETRIES):
        connection = None
        cursor = None
        try:

            connection = connect()
            cursor = connection.cursor()
    
            product_data = {}
    
            product_data = {
                'product_name': data.get('title', None),
                'site_name': site,
                'url': data.get('link', None),
                'site_category': data.get('site_category', None),
                'site_tag': data['tag'],
                'sku': data.get('sku') or data.get('upc') or data.get('product_id') or stable_sku(site, data['tag']),
                'brand': data.get('brand', None),
                'html': data['html'],
                'plain_text': data.get('plain_text', None),
                'price': data.get('regular_price', None),
                'price_sale': data.get('sale_price', None),
                'flavor_text': data.get('flavor_text', None),
                'description': data.get('description', None),
                'package_contents': data.get('package_contents', None),
                'features': data.get('features', None),
                'ingredients': data.get('ingredients', None),
                'warnings': data.get('warnings', None),
                'eliquid_contents': data.get('eliquid_contents', None),
                'puffs': data.get('puffs', None),
                'coil': data.get('coil', None),
                'battery_text': data.get('battery', None),
                'power_level': data.get('power_level', None),
                'nicotine_level_text': data.get('nicotine_strength', None),
                'stock_status': data.get('stock_status', None),    
            }  
            # A partial insert can survive a driver/database failure even when
            # the surrounding retry is rolled back. Avoid retrying the same
            # unique URL and turning a recoverable write failure into a second
            # unique-key error.
            cursor.execute("SELECT TOP 1 id FROM ecig_product WHERE url = ?", (product_data['url'],))
            existing_product = cursor.fetchone()
            if existing_product:
                print(f"Product URL already exists as product_id {existing_product[0]}; skipping duplicate insert")
                connection.rollback()
                return False

            # Insert into ecig_product and get the product_id
            product_id = insert_ecig_product(cursor, product_data)
    
            insert_ecig_price_to_db(cursor, product_id, product_data['price'], product_data['price_sale'])
            insert_ecig_product_history_snapshot(cursor, product_id, product_data)
    
            # Insert into other tables
            # insert_ecig_product_attributes(cursor, attributes_data)
            if len(data.get('reviews', [])) > 0:
                insert_reviews_to_db(data.get('reviews', []), product_id, cursor)
    
            if len(data.get('review_attributes', {}).keys()) > 0:
                insert_review_attributes_to_db(cursor, data.get('review_attributes', {}), product_id)
            if data.get('flavor_list'):
                for flavor in data.get('flavor_list', []):
                    if isinstance(flavor, str) and flavor.strip():
                        flavor_data = {
                            'product_id': product_id,
                            'flavor_name': flavor.replace(' (out of stock)', '').strip(),
                            'flavor_description': None,
                            'flavor_category': None,
                            'iced_bool': None,
                            'cbd_bool': None,
                        }
                        insert_ecig_flavors(cursor, flavor_data)
            if data.get('nicotine_strengths'):
                for strength in data.get('nicotine_strengths', []):
                    if isinstance(strength, str):
                        strength = {'value': strength, 'unit': None, 'level': None}
                    if not isinstance(strength, dict):
                        continue
                    nicotine_level_data = {
                        'product_id': product_id,
                        'value': strength.get('value'),
                        'unit': strength.get('unit'),
                        'level': strength.get('level'),
                    }
                    insert_ecig_nicotine_levels(cursor, nicotine_level_data)
            if len(data.get('images', [])) > 0:
                image_count = 0
                for image in data.get('images', []):
                    image_data = {
                        'product_id': product_id,
                        'url': image.get('url', None),
                        'path': image.get('path', None),
                        'title': image.get('title', None),
                        'alt_text': image.get('alt', None),
                    }
                    if insert_ecig_images(cursor, image_data):
                        image_count += 1
                print(f"Downloaded/inserted {image_count} images for product_id {product_id}")
    
            # Commit the transaction
            connection.commit()
            print("Product inserted into Azure successfully!")
            return True
        
        except Exception as error:
            print(f"Azure map_product_data Error (attempt {attempt + 1}/{DB_CONNECT_RETRIES}): {error}")
            if connection:
                connection.rollback()
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
        if attempt + 1 < DB_CONNECT_RETRIES:
            time.sleep(DB_RETRY_DELAY * (2 ** attempt))
    return False

def get_products(site_name):
    results = []
    try:
        connection = connect()  # Use our connect() function
        cursor = connection.cursor()

        # The SQL query with a parameter placeholder for site_name
        query = """
        select ep.id as product_id, ep.html, ep.site_tag from ecig_product ep 
        where ep.site_name = ?
        ORDER BY 
            CASE WHEN ep.site_category LIKE '%disposable%'
            THEN 1
            WHEN ep.site_category LIKE '%liquid%'
            THEN 2
            ELSE 3
            END, site_tag
        """

        # Execute the query with the site_name parameter
        cursor.execute(query, (site_name, ))

        # Fetch all the results
        results = cursor.fetchall()
    except Exception as error:
        print(f"Azure get_products Error: {error}")
        traceback.print_exc()
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return results

def get_products_and_descriptions(site_name):
    results = []
    try:
        connection = connect()  # Use our connect() function
        cursor = connection.cursor()

        # The SQL query with a parameter placeholder for site_name
        query = """
       select ep.id as product_id, ep.product_name, ep.description, ep.site_tag from ecig_product ep 
        where ep.site_name = ?
        """

        # Execute the query with the site_name parameter
        cursor.execute(query, (site_name, ))

        # Fetch all the results
        results = cursor.fetchall()
    except Exception as error:
        print(f"Azure get_products Error: {error}")
        traceback.print_exc()
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return results


def get_products_without_reviews(site_name):
    results = []
    try:
        connection = connect()  # Use our connect() function
        cursor = connection.cursor()

        # The SQL query with a parameter placeholder for site_name
        query = """
        select er.id as review_id, ep.id as product_id, ep.html, ep.site_tag from ecig_product ep 
        left outer join ecig_reviews er 
        on ep.id = er.product_id
        where er.id is null
        and ep.site_name = ?
        order by 
            case when ep.site_category ilike ?
            then 1
            when ep.site_category ilike ?
            then 2
            else 3
            end,
            ep.id
        """

        # Execute the query with the site_name parameter
        cursor.execute(query, (site_name, '%disposable%', '%liquid%'))

        # Fetch all the results
        results = cursor.fetchall()


    except Exception as error:
        print(f"Azure get_products_without_reviews Error: {error}")
        traceback.print_exc()
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return results


def insert_review_attributes(review_attributes_dict, product_id):
    try:
        connection = connect()  # Use our connect() function
        cursor = connection.cursor()
        rows = insert_review_attributes_to_db(cursor, review_attributes_dict, product_id)

        # Commit the transaction
        connection.commit()
        print(f"{len(rows)} Review Attributes data inserted into Azure!")

    except Exception as error:
        print(f"Azure insert_review_attributes Error: {error}")
        traceback.print_exc()
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def insert_review_attributes_to_db(cursor, review_attributes_dict, product_id):
    """
    Insert review attributes for a product into the ecig_review_attributes table.
    
    Args:
        cursor: Azure SQL Database cursor
        product_id: ID of the product the attributes belong to
        review_attributes_dict: Dictionary where keys are review_attribute_question and values are review_attribute_value
    
    Returns:
        List of IDs of the inserted records
    """
    inserted_ids = []
    
    for question, value in review_attributes_dict.items():
        # First check if the record already exists
        check_query = """
            SELECT TOP 1 id FROM ecig_review_attributes 
            WHERE product_id = ? AND review_attribute_question = ?
        """
        
        cursor.execute(check_query, (product_id, question))
        existing_row = cursor.fetchone()
        
        if existing_row:
            # Record already exists, add its ID to the list
            continue
        else:
            # Record doesn't exist, insert new one
            insert_query = """
                INSERT INTO ecig_review_attributes 
                (product_id, review_attribute_question, review_attribute_value) 
                OUTPUT INSERTED.id
                VALUES (?, ?, ?)
            """
            
            cursor.execute(insert_query, (product_id, question, value))
            
            # Get the ID of the inserted record
            inserted_row = cursor.fetchone()
            if inserted_row:        
                inserted_id = inserted_row[0]
                inserted_ids.append(inserted_id)
    
    return inserted_ids


def insert_ecig_price_to_db(cursor, product_id, price, price_sale):
    """
    Inserts a pricing record into the ecig_price table only if the 
    price or sale price has changed from the most recent entry.
    """
    
    # 1. Query the latest existing record for this product
    check_sql = """
        SELECT TOP 1 price, price_sale
        FROM ecig_price
        WHERE product_id = ?
        ORDER BY id DESC
    """
    
    try:
        cursor.execute(check_sql, (product_id,))
        latest_record = cursor.fetchone()
        
        # 2. Compare the latest record to the incoming values
        if latest_record:
            # pyodbc returns rows as tuples, e.g., ('19.99', None)
            latest_price = latest_record[0]
            latest_price_sale = latest_record[1]
            
            # If nothing has changed, skip the insert to save database space
            if latest_price == price and latest_price_sale == price_sale:
                print(f"Prices for product_id {product_id} are unchanged. Skipping insert.")
                return 0 # Exit the function early

        # 3. If we reach here, it's either a new product or a changed price
        insert_sql = """
            INSERT INTO ecig_price (product_id, price, price_sale)
            VALUES (?, ?, ?)
        """
        
        cursor.execute(insert_sql, (product_id, price, price_sale))
        cursor.connection.commit()
        
        print(f"Successfully inserted new price record for product_id: {product_id}")

        
    except Exception as e:
        cursor.connection.rollback()
        print(f"Database operation failed: {e}")
    
    return 1

def insert_ecig_price(product_id, price, price_sale): 
    for attempt in range(DB_CONNECT_RETRIES):
        cursor = None
        connection = None
        try:
            connection = connect()
            cursor = connection.cursor()
            res = insert_ecig_price_to_db(cursor, product_id, price, price_sale)
            if res == 1:
                connection.commit()
                print("Price data rows inserted into Azure!")
            return True
        except Exception as error:
            print(f"Azure insert price Error (attempt {attempt + 1}/{DB_CONNECT_RETRIES}): {error}")
            if connection:
                connection.rollback()
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
        if attempt + 1 < DB_CONNECT_RETRIES:
            time.sleep(DB_RETRY_DELAY * (2 ** attempt))
    return False


def insert_reviews(reviews, product_id): 
    cursor = None
    connection = None
    try:
        connection = connect()  # Use our connect() function
        cursor = connection.cursor()
        rows = insert_reviews_to_db(reviews, product_id, cursor)

        # Commit the transaction
        connection.commit()
        if len(rows) > 0:
            print(f"{len(rows)} Review data rows inserted into Azure!")
        else:
            print(f"No new reviews to insert for product_id {product_id}.")

    except Exception as error:
        print(f"Azure insert_review_attributes Error: {error}")
        traceback.print_exc()
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def insert_reviews_to_db(reviews, product_id, cursor) -> None:
    """
    Insert reviews and their attributes into PostgreSQL database.
    
    Args:
        reviews: List of review dictionaries from the parser
        product_id: ID of the product these reviews belong to
        connection_params: Database connection parameters
    """
    rows = list()
    unique_keys = ['review_text', 'author', 'date']

    # Use a set to track seen combinations
    seen = set()
    unique_reviews = []

    for review in reviews:
        key = tuple(review[k] for k in unique_keys)
        if key not in seen:
            seen.add(key)
            unique_reviews.append(review)

        skipped_count = 0
    for review in unique_reviews:
        content = review.get('review_text')

        if not content or content.strip() == '':
            continue

        check_query = """
            SELECT TOP 1 id FROM ecig_reviews 
            WHERE product_id = ? 
            AND (author = ?)
            AND (review_text = ?)
            """

        # Insert review data
        insert_review_query = """
            INSERT INTO ecig_reviews
            (product_id, review_date, rating, author, verified, review_text, variant, sweet_level, iced_level, image_url, reply_text, reply_from)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        
        # Convert review date string to date object if present
        review_date = review.get('date')
        author = review.get('author')
        sweet_level = review.get('sweet_level')
        iced_level = review.get('iced_level') # Default to 0 if not present
        variant = review.get('variant')
        rating = review.get('rating')

        # commit any pending transactions
           
        cursor.execute(
            check_query, 
            (
                product_id,
                author,
                content
            )
        )
        
        existing_review = cursor.fetchone()
        
        if existing_review:
            # Review already exists, skip it
            # print(f"Skipping duplicate review by {author}")
            skipped_count += 1
            continue
        
        
        cursor.execute(
            insert_review_query, 
            (
                product_id,
                review_date,
                rating,
                author,
                review.get('verified_buyer', False),
                content,
                variant,
                sweet_level,
                iced_level,
                review.get('image_url'),
                review.get('reply_text'),
                review.get('reply_from')
            )
        )
        
        # Get the ID of the newly inserted review
        review_row = cursor.fetchone()
        if review_row:
            review_id = review_row[0]
            rows.append(review_id)
        else:       
            # If no review was inserted, use a default value
            print(f"Review not inserted to Azure for {author}")  
            review_id = None
        
        # Insert review attributes if they exist
        if 'attributes' in review and review['attributes']:
            for attr_name, attr_value in review['attributes'].items():
                check_attr_query = """
                    SELECT TOP 1 id FROM ecig_review_attributes 
                    WHERE product_id = ? AND review_attribute_question = ?
                """
                
                cursor.execute(check_attr_query, (product_id, attr_name))
                existing_attr = cursor.fetchone()
                
                if not existing_attr:
                    # Record doesn't exist, insert new one
                    insert_attr_query = """
                        INSERT INTO ecig_review_attributes
                        (product_id, review_id, review_attribute_question, review_attribute_value)
                        VALUES (?, ?, ?, ?)
                    """
                    
                    # Convert attribute value to string if needed
                    attr_value_str = str(attr_value) if attr_value is not None else None
                    
                    cursor.execute(
                        insert_attr_query,
                        (
                            product_id,
                            review_id,
                            attr_name,
                            attr_value_str
                        )
                    )
    return rows



def insert_ecig_product(cursor, product_data):
    query = """
        INSERT INTO ecig_product (
            product_name, site_name, url, site_category, site_tag, sku,
            brand, html, plain_text, price, price_sale, flavor_text, description,
            package_contents, ingredients, warnings, 
            eliquid_contents, puffs, coil, battery_text, power_level,
            nicotine_level_text, stock_status, features
        )
        OUTPUT INSERTED.id
        VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, 
            ?, ?, ?, ?, ?,
            ?, ?, ?
        );
    """
    
    # Convert dictionary to tuple in the correct order
    params = (
        product_data['product_name'],
        product_data['site_name'],
        product_data['url'],
        product_data['site_category'],
        product_data['site_tag'],
        product_data['sku'],
        product_data['brand'],
        product_data['html'],
        product_data['plain_text'],
        product_data['price'],
        product_data['price_sale'],
        product_data['flavor_text'],
        product_data['description'],
        product_data['package_contents'],
        product_data['ingredients'],
        product_data['warnings'],
        product_data['eliquid_contents'],
        product_data['puffs'],
        product_data['coil'],
        product_data['battery_text'],
        product_data['power_level'],
        product_data['nicotine_level_text'],
        product_data['stock_status'],
        product_data['features']
    )
    
    cursor.execute(query, params)
    new_id = cursor.fetchone()[0]
    print(f"Inserted product '{product_data['product_name']}' ({product_data['site_name']}) as product_id {new_id}")
    return new_id

def insert_ecig_product_attributes(cursor, attributes_data):
    query = """
        INSERT INTO ecig_product_attributes (
            product_id, total_ounces_per_ml, product_category, screen_bool, disposable_bool,
            rechargeable_bool, battery_bool, usb_bool, adjustable_bool,
            tfn_bool, nic_free_bool
        )
        VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?
        );
    """
    
    # Convert dictionary to tuple in the correct order
    params = (
        attributes_data['product_id'],
        attributes_data['total_ounces_per_ml'],
        attributes_data['product_category'],
        attributes_data['screen_bool'],
        attributes_data['disposable_bool'],
        attributes_data['rechargeable_bool'],
        attributes_data['battery_bool'],
        attributes_data['usb_bool'],
        attributes_data['adjustable_bool'],
        attributes_data['tfn_bool'],
        attributes_data['nic_free_bool']
    )
    
    cursor.execute(query, params)


def insert_ecig_flavors(cursor, flavors_data):
    check_query = """
        SELECT TOP 1 id FROM ecig_flavors 
        WHERE product_id = ? AND flavor_name = ?
    """
    
    cursor.execute(check_query, (flavors_data['product_id'], flavors_data['flavor_name']))
    existing_row = cursor.fetchone()

    if existing_row:
        # Record already exists, add its ID to the list
        return

    query = """
        INSERT INTO ecig_flavors (
            product_id, flavor_name, flavor_description, flavor_category, iced_bool, cbd_bool
        )
        VALUES (
            ?, ?, ?, ?, ?, ?
        );
    """

    # Convert dictionary to tuple in the correct order
    params = (
        flavors_data['product_id'],
        flavors_data['flavor_name'],
        flavors_data['flavor_description'],
        flavors_data['flavor_category'],
        flavors_data['iced_bool'],
        flavors_data['cbd_bool']
    )

    cursor.execute(query, params)
    print(f"Inserted flavor '{flavors_data['flavor_name']}' for product_id {flavors_data['product_id']}")


def insert_ecig_nicotine_levels(cursor, nicotine_levels_data):

    check_query = """
        SELECT TOP 1 id FROM ecig_nicotine_levels 
        WHERE product_id = ? AND value = ?
    """
    
    cursor.execute(check_query, (nicotine_levels_data['product_id'], nicotine_levels_data['value']))
    existing_row = cursor.fetchone()
    
    if existing_row:
        # Record already exists, add its ID to the list
        return

    query = """
        INSERT INTO ecig_nicotine_levels (
            product_id, value, unit
        )
        VALUES (
            ?, ?, ?
        );
    """

    # Convert dictionary to tuple in the correct order
    params = (
        nicotine_levels_data['product_id'],
        nicotine_levels_data['value'],
        nicotine_levels_data['unit']
    )

    cursor.execute(query, params)
    print(f"Inserted nicotine level '{nicotine_levels_data['value']}' for product_id {nicotine_levels_data['product_id']}")


def insert_ecig_images(cursor, images_data):

    check_query = """
        SELECT TOP 1 id FROM ecig_images 
        WHERE product_id = ? AND path = ?
    """
    
    cursor.execute(check_query, (images_data['product_id'], images_data['path']))
    existing_row = cursor.fetchone()

    if existing_row:
        # Record already exists, add its ID to the list
        return False
    query = """
        INSERT INTO ecig_images (
            product_id, url, path, title, alt_text
        )
        VALUES (
            ?, ?, ?, ?, ?
        );
    """

    # Convert dictionary to tuple in the correct order
    params = (
        images_data['product_id'],
        images_data['url'],
        images_data['path'],
        images_data['title'],
        images_data['alt_text']
    )



    cursor.execute(query, params)
    print(f"Inserted image '{images_data['path']}' for product_id {images_data['product_id']}")
    return True


def insert_product_images(product_id, images):
    """Persist downloaded image records for an existing product."""
    connection = None
    cursor = None
    try:
        connection = connect()
        cursor = connection.cursor()
        inserted = 0
        for image in images or []:
            if insert_ecig_images(cursor, {
                'product_id': product_id,
                'url': image.get('url'),
                'path': image.get('path'),
                'title': image.get('title'),
                'alt_text': image.get('alt'),
            }):
                inserted += 1
        connection.commit()
        return inserted
    except Exception as error:
        print(f"Azure image update Error: {error}")
        if connection:
            connection.rollback()
        return 0
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def product_has_images(product_id):
    connection = None
    cursor = None
    try:
        connection = connect()
        cursor = connection.cursor()
        cursor.execute("SELECT TOP 1 id FROM ecig_images WHERE product_id = ?", (product_id,))
        return cursor.fetchone() is not None
    except Exception as error:
        print(f"Azure image lookup Error for product_id {product_id}: {error}")
        return False
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_product_reviews():
    results = []
    try:
        connection = connect()  # Use our connect() function
        cursor = connection.cursor()

        # The SQL query with a parameter placeholder for site_name
        query = """select p.site_tag, p.site_name,
r.id, r.product_id, r.review_date , r.review_text, r.sweet_level, r.iced_level, 
r.rating, r.verified, r.date_inserted
from 
ecig_reviews r
inner join ecig_product p on
p.id = r.product_id;
        """

        # Execute the query with the site_name parameter
        cursor.execute(query, )

        # Fetch all the results
        results = cursor.fetchall()


    except Exception as error:
        print(f"Azure get_products_without_reviews Error: {error}")
        traceback.print_exc()
        if connection:
            connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    return results
