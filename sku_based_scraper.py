# -*- coding: utf-8 -*-
"""Tradezone - SKU search scraper with Shopify CSV output + Smart SKU validation"""
from DrissionPage import ChromiumPage, ChromiumOptions
import csv, time, re, sys, io, json, logging, os
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd
load_dotenv()

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# === LOGGING SETUP ===
# Create logs directory if not exists
import os
if not os.path.exists('logs'):
    os.makedirs('logs')

# Setup logging with timestamp
log_filename = f'logs/tradezone_scraper_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

logger.info("="*80)
logger.info("TRADEZONE SCRAPER - SESSION STARTED")
logger.info("="*80)

# === CLEANING FUNCTIONS ===
def clean_html_text(text):
    """Remove HTML tags, clean special characters, replace Tradezone with ALL LED DIRECT"""
    if not text or text == '':
        return ""
    text = str(text)
    # Unescape HTML entities
    import html as html_lib
    text = html_lib.unescape(text)
    # Remove specific Unicode issues
    text = re.sub(r'Ã[\x80-\xBF]', '', text)
    # Remove non-ASCII characters
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    # Replace Tradezone/TZ with ALL LED DIRECT
    text = re.sub(r'\b(tradezone|tz)\b', 'ALL LED DIRECT', text, flags=re.IGNORECASE)
    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove <br/> and <br> tags specifically
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
    return text.strip()

def clean_body_html(html_text):
    """Clean body HTML - keep HTML tags but replace Tradezone with ALL LED DIRECT"""
    if not html_text or html_text == '':
        return ""
    html_text = str(html_text)
    # Replace Tradezone/TZ with ALL LED DIRECT
    html_text = re.sub(r'\b(tradezone|tz)\b', 'ALL LED DIRECT', html_text, flags=re.IGNORECASE)
    # Clean up multiple spaces
    html_text = re.sub(r'\s+', ' ', html_text)
    return html_text.strip()

def clean_handle(handle):
    """Normalize Shopify handle: remove extra dashes and spaces."""
    handle = str(handle).strip().lower()
    handle = re.sub(r'-+', '-', handle)  # replace multiple dashes with single
    handle = handle.strip('-')            # remove leading/trailing dash
    return handle

# SKUS = ['108272', '94485', '88967', '76494', '87783', '24257', '18216']
# Read SKUs from CSV file (same directory)
df = pd.read_csv('sku1.csv')
SKUS = df['sku'].astype(str).str.strip().tolist()

print(f"Loaded {len(SKUS)} SKUs from CSV: {SKUS}")

co = ChromiumOptions()
co.set_argument('--start-maximized')
page = ChromiumPage(co)


# ── VPN PAUSE ─────────────────────────────────────────────────────────────────
print("\n" + "="*120)
print("  BROWSER OPENED!")
print("  Please ENABLE your VPN (Australia server) now...")
print("="*120)

for remaining in range(15, 0, -1):
    print(f"  Starting in {remaining} seconds... ", end='\r')
    time.sleep(1)

print("\n  ✓ Proceeding with script...                    ")
print("="*120 + "\n")

print("="*80)
print("TRADEZONE - SHOPIFY FORMAT SCRAPER (SMART VALIDATION)")
print("="*80)

page.get('https://www.tradezone.com.au')
time.sleep(2)
print("Homepage OK")
logger.info("Homepage loaded successfully")

# Login check
page.get('https://www.tradezone.com.au/customer/account/login')
time.sleep(2)
if '/account/login' in page.url:
    e = page.ele('#email', timeout=2)
    p = page.ele('#pass', timeout=2)
    if e and p:
        e.clear(); e.input(os.getenv('TRADEZONE_EMAIL'))
        p.clear(); p.input(os.getenv('TRADEZONE_PASSWORD'))
        b = page.ele('#send2', timeout=2)
        if b: b.click(); time.sleep(3)
        print(f"Login -> {page.url}")
        logger.info(f"Login successful - Redirected to: {page.url}")
else:
    print("Already logged in")
    logger.info("Already logged in - Session active")

# Note: We now use specific CSS selectors (h3.name a.hover_link) to get only search result product links
# This means we automatically skip cart links, navigation links, etc.
print("Using CSS selector: h3.name a.hover_link for product links")

# Original fields from old scraper + new fields
fields = ['search_sku','sku','supplier_sku','tradezone_id','title','description',
          'price_ex_tax','price_inc_tax','brand',
          'weight','dimensions','dimensions_packaging','attributes',
          'stock_status','image1','image2','image3','image4','image5','product_url',
          'part_number','supplier_part_number','sub_group','barcode',
          'length','height','width','length_packaging','height_packaging','width_packaging',
          'warranty','shipping','product_flag']
results = []

def calculate_match_score(search_sku, tradezone_id, supplier_sku, sku, title):
    """
    Calculate how well a product matches the search SKU.
    Returns score: 100 = perfect match, 50+ = good match, 0 = no match
    """
    search_sku_clean = search_sku.strip().lower()
    score = 0
    
    # Exact matches (highest priority)
    if tradezone_id and tradezone_id == search_sku:
        score = 100
    elif supplier_sku and supplier_sku.lower() == search_sku_clean:
        score = 100
    elif sku and sku.lower() == search_sku_clean:
        score = 100
    
    # Very similar matches (high priority)
    elif tradezone_id and search_sku in tradezone_id:
        score = 80
    elif tradezone_id and tradezone_id in search_sku:
        score = 80
    elif supplier_sku and search_sku_clean in supplier_sku.lower():
        score = 75
    elif sku and search_sku_clean in sku.lower():
        score = 75
    
    # Appears in title (medium priority)
    elif title and search_sku_clean in title.lower():
        score = 60
    
    # Partial match - at least 4 characters overlap (low priority)
    elif supplier_sku and len(search_sku) >= 4:
        # Check for overlap
        if any(search_sku_clean[i:i+4] in supplier_sku.lower() for i in range(len(search_sku_clean)-3)):
            score = 40
    
    return score

# === SCRAPING LOGIC WITH SMART VALIDATION ===
logger.info(f"Starting scraping for {len(SKUS)} SKUs: {', '.join(SKUS)}")

for i, search_sku in enumerate(SKUS, 1):
    print(f"\n{'='*50}")
    print(f"[{i}/{len(SKUS)}] Search: {search_sku}")
    logger.info(f"[{i}/{len(SKUS)}] Searching for SKU: {search_sku}")
    
    row = {f: '' for f in fields}
    row['search_sku'] = search_sku

    page.get(f'https://www.tradezone.com.au/catalogsearch/result/?q={search_sku}')
    time.sleep(2)

    # Get ALL non-cart product links from search results
    product_links = []
    if '/product/' in page.url:
        # Direct redirect to product page - Tradezone thinks this is the exact match!
        product_links = [page.url]
        print(f"  Direct redirect to product (exact match by Tradezone)")
        logger.info(f"  Direct redirect to product page: {page.url}")
    else:
        try:
            # Use specific selector for search result product links: h3.name a.hover_link
            js_links = page.run_js('var r=[]; document.querySelectorAll("h3.name a.hover_link").forEach(function(a){ if(a.href) r.push(a.href); }); return JSON.stringify(r);')
            for link in json.loads(js_links):
                if link not in product_links:
                    product_links.append(link)
        except: pass

    if not product_links:
        print("  NOT FOUND - No product links"); 
        results.append(row); 
        continue

    print(f"  Found {len(product_links)} product link(s)")

    # SMART LOGIC:
    # If only 1 product found, trust Tradezone's search and use it
    # If multiple products, score each and pick the best match
    
    if len(product_links) == 1:
        # Only one result - trust Tradezone, it's their best match
        print(f"  Single result found - trusting Tradezone's search")
        purl = product_links[0]
        
        row['product_url'] = purl
        page.get(purl)
        time.sleep(2)

        if '404' in page.title and 'Whoops' in page.html:
            print("  404 page"); 
            results.append(row); 
            continue

        text = page.ele('tag:body').text if page.ele('tag:body') else ''
        html = page.html

        # === FULL SCRAPING (EXACT SAME AS ORIGINAL) ===
        
        # --- TRADEZONE ID (from URL: last number before .html) ---
        m = re.search(r'-(\d+)\.html', purl)
        if m:
            row['tradezone_id'] = m.group(1)

        # --- TITLE (from <title>: "Brand-Code | Product Name - Electrical Supplies") ---
        title_tag = page.title
        if '|' in title_tag:
            row['title'] = title_tag.split('|', 1)[1].strip()
            row['title'] = re.sub(r'\s*-\s*Electrical Supplies$', '', row['title'])
        if not row['title']:
            try:
                el = page.ele('h1', timeout=2)
                if el: row['title'] = el.text.strip()
            except: pass

        # --- BRAND (from brand logo image - most reliable) ---
        try:
            for img in page.eles('tag:img', timeout=1):
                alt = img.attr('alt') or ''
                src = img.attr('src') or ''
                if 'brands' in src.lower() and alt:
                    row['brand'] = alt.strip()
                    break
        except: pass

        # --- SKU (from title tag: remove brand name to get supplier SKU) ---
        if '|' in title_tag:
            sku_part = title_tag.split('|')[0].strip()
            if row['brand']:
                brand_pattern = re.escape(row['brand']).replace(r'\ ', r'[\s-]*').replace(r'\-', r'[\s-]*')
                sku_clean = re.sub(r'^' + brand_pattern + r'[\s-]*', '', sku_part, flags=re.I).strip()
                if sku_clean:
                    row['sku'] = sku_clean
                    row['supplier_sku'] = sku_clean
            if not row['sku']:
                row['sku'] = sku_part
                row['supplier_sku'] = sku_part

        # --- PRICE (from page text AFTER the product title to avoid cart prices) ---
        title_pos = text.find(row['title'][:25]) if row['title'] else -1
        price_text = text[title_pos:] if title_pos > 0 else text[400:]

        m = re.search(r'\$\s*([\d,.]+)\s*ex', price_text)
        if m: row['price_ex_tax'] = f"${m.group(1)}"

        m = re.search(r'\$\s*([\d,.]+)\s*inc', price_text)
        if m: row['price_inc_tax'] = f"${m.group(1)}"

        # --- STOCK STATUS ---
        stock_matches = re.findall(r'(Gold Coast|Melbourne|Sydney|Perth|Brisbane|New Adelaide)\s*(\d+)\s*In Stock', price_text)
        if stock_matches:
            stock_info = []
            total = 0
            for loc, qty in stock_matches:
                stock_info.append(f"{loc}: {qty}")
                total += int(qty)
            row['stock_status'] = f"In Stock (Total: {total} | " + ', '.join(stock_info) + ')'
        elif 'In Stock' in price_text:
            row['stock_status'] = 'In Stock'
        elif 'Out of Stock' in price_text or 'Sold Out' in price_text:
            row['stock_status'] = 'Out of Stock'

        # --- DESCRIPTION (between "Product Details" sections) ---
        desc_match = re.search(r'Product Details\s*\nTech Data[^\n]*\nProduct Details\s*\n(.+?)(?:\nFrequently Asked|\nSave to Job|\nPopular Categories)', text, re.S)
        if not desc_match:
            desc_match = re.search(r'Product Details\s*\n(.+?)(?:\nTech Data|\nFrequently Asked|\nSave to Job)', text, re.S)
        if desc_match:
            desc = re.sub(r'\n+', ' | ', desc_match.group(1).strip())
            row['description'] = desc[:2000]

        # --- IMAGES (from <img> tags with media.tradezone.com.au) ---
        imgs = []
        product_id = row['tradezone_id']
        for img in page.eles('tag:img', timeout=2):
            src = img.attr('src') or img.attr('data-src') or ''
            alt = img.attr('alt') or ''
            if src and product_id and product_id in src:
                if src not in imgs:
                    imgs.append(src)
            elif src and row['title'] and row['title'][:20] in alt:
                if src not in imgs:
                    imgs.append(src)

        # Also get highest resolution version
        if product_id:
            hi_res = f'https://media.tradezone.com.au/images/still/726/726/{product_id}/30.jpg'
            if hi_res not in imgs:
                imgs.insert(0, hi_res)

        for j, src in enumerate(imgs[:5]):
            row[f'image{j+1}'] = src

        # --- ATTRIBUTES & DETAILED INFO (from product attribute tables) ---
        # Parse tables with structure: <div class="cell label"><h4>Field</h4></div><div class="cell value">Value</div>
        attrs = []
        warranty_parts = []
        shipping_parts = []
        
        try:
            # Find all attribute tables
            attribute_tables = page.eles('css:.product-attribute-table')
            
            for table in attribute_tables:
                # Get all rows in this table
                rows = table.eles('css:.row')
                
                for row_elem in rows:
                    cells = row_elem.eles('css:.cell')
                    if len(cells) >= 2:
                        # Get label and value
                        label_elem = cells[0]
                        value_elem = cells[1]
                        
                        # Extract text from h4 in label, or direct text
                        label = ''
                        h4 = label_elem.ele('tag:h4', timeout=0.1)
                        if h4:
                            label = h4.text.strip()
                        else:
                            label = label_elem.text.strip()
                        
                        # Extract value text
                        value = value_elem.text.strip()
                        
                        if not label or not value:
                            continue
                        
                        label_lower = label.lower()
                        
                        # Extract specific fields
                        if 'part number' in label_lower and not 'also' in label_lower:
                            if not row['part_number']:
                                row['part_number'] = value
                                row['supplier_part_number'] = value
                        
                        elif 'sub category' in label_lower or 'sub group' in label_lower:
                            row['sub_group'] = value
                        
                        elif label_lower == 'barcode':
                            if not row['barcode']:
                                row['barcode'] = value
                        
                        elif 'weight' in label_lower and 'kg' in label_lower:
                            if not row['weight']:
                                row['weight'] = value + ' kg'
                        
                        elif label_lower == 'length (mm)':
                            row['length'] = value
                        elif label_lower == 'height (mm)':
                            row['height'] = value
                        elif label_lower == 'width (mm)':
                            row['width'] = value
                        
                        elif label_lower == 'length packaging (mm)':
                            row['length_packaging'] = value
                        elif label_lower == 'height packaging (mm)':
                            row['height_packaging'] = value
                        elif label_lower == 'width packaging (mm)':
                            row['width_packaging'] = value
                        
                        elif 'freight' in label_lower or 'shipping' in label_lower:
                            shipping_parts.append(f"{label}: {value}")
                        
                        # Add to general attributes list (for all other fields)
                        if len(label) < 60 and len(value) < 200:
                            attrs.append(f"{label}: {value}")
        
        except Exception as e:
            print(f"    Warning: Error parsing attribute tables: {str(e)}")
        
        # Store attributes
        row['attributes'] = '; '.join(attrs[:30]) if attrs else ''
        row['shipping'] = '; '.join(shipping_parts) if shipping_parts else ''
        
        # --- WARRANTY INFO (from warranty section if exists) ---
        try:
            # Look for warranty information in the page text
            warranty_match = re.search(r'Warranty Information[:\s]*(.+?)(?:Attributes|Shipping|$)', text, re.S)
            if warranty_match:
                warranty_text = warranty_match.group(1).strip()
                # Clean up warranty text
                warranty_lines = []
                for line in warranty_text.split('\n'):
                    line = line.strip()
                    if line and len(line) < 200:
                        warranty_lines.append(line)
                if warranty_lines:
                    row['warranty'] = ' | '.join(warranty_lines[:10])
        except:
            pass

        # Weight/dimensions fallback
        if not row['weight']:
            m = re.search(r'[Ww]eight[:\s]*([0-9.,]+\s*(?:kg|g|lb|grams?))', text)
            if m: row['weight'] = m.group(1)
        if not row['dimensions']:
            m = re.search(r'[Dd]imensions?[:\s]*([0-9.,]+\s*[xX×]\s*[0-9.,]+(?:\s*[xX×]\s*[0-9.,]+)?(?:\s*(?:mm|cm|m))?)', text)
            if m: row['dimensions'] = m.group(1)

        print(f"  ✓ Scraped: TZ ID {row['tradezone_id']} | SKU {row['sku']}")
        
    else:
        # Multiple results - score each and pick best match
        print(f"  Multiple results - scoring each to find best match...")
        
        candidates = []
        for link_idx, purl in enumerate(product_links[:10], 1):  # Check max 10 products
            page.get(purl)
            time.sleep(1)

            if '404' in page.title and 'Whoops' in page.html:
                continue

            text = page.ele('tag:body').text if page.ele('tag:body') else ''
            title_tag = page.title

            # Quick extraction for scoring
            temp_id = ''
            m = re.search(r'-(\d+)\.html', purl)
            if m: temp_id = m.group(1)

            temp_title = ''
            if '|' in title_tag:
                temp_title = title_tag.split('|', 1)[1].strip()

            temp_brand = ''
            try:
                for img in page.eles('tag:img', timeout=1):
                    alt = img.attr('alt') or ''
                    src = img.attr('src') or ''
                    if 'brands' in src.lower() and alt:
                        temp_brand = alt.strip()
                        break
            except: pass

            temp_sku = ''
            if '|' in title_tag:
                sku_part = title_tag.split('|')[0].strip()
                if temp_brand:
                    brand_pattern = re.escape(temp_brand).replace(r'\ ', r'[\s-]*').replace(r'\-', r'[\s-]*')
                    sku_clean = re.sub(r'^' + brand_pattern + r'[\s-]*', '', sku_part, flags=re.I).strip()
                    if sku_clean:
                        temp_sku = sku_clean
                if not temp_sku:
                    temp_sku = sku_part

            # Calculate match score
            score = calculate_match_score(search_sku, temp_id, temp_sku, temp_sku, temp_title)
            
            print(f"    Link {link_idx}: TZ ID {temp_id} | SKU {temp_sku} | Score: {score}")
            
            if score > 0:
                candidates.append({
                    'url': purl,
                    'score': score,
                    'id': temp_id,
                    'sku': temp_sku
                })

        if not candidates:
            print(f"  ⚠️  NO MATCHING PRODUCT FOUND for SKU: {search_sku}")
            results.append(row)
            continue

        # Pick best match
        best = max(candidates, key=lambda x: x['score'])
        print(f"  ✓ Best match: TZ ID {best['id']} (score: {best['score']})")
        
        # Now do full scraping of best match
        purl = best['url']
        row['product_url'] = purl
        page.get(purl)
        time.sleep(2)

        text = page.ele('tag:body').text if page.ele('tag:body') else ''
        html = page.html

        # [REPEAT ALL THE SCRAPING LOGIC FROM ABOVE]
        # (Same as single result case)
        
        m = re.search(r'-(\d+)\.html', purl)
        if m: row['tradezone_id'] = m.group(1)

        title_tag = page.title
        if '|' in title_tag:
            row['title'] = title_tag.split('|', 1)[1].strip()
            row['title'] = re.sub(r'\s*-\s*Electrical Supplies$', '', row['title'])
        if not row['title']:
            try:
                el = page.ele('h1', timeout=2)
                if el: row['title'] = el.text.strip()
            except: pass

        try:
            for img in page.eles('tag:img', timeout=1):
                alt = img.attr('alt') or ''
                src = img.attr('src') or ''
                if 'brands' in src.lower() and alt:
                    row['brand'] = alt.strip()
                    break
        except: pass

        if '|' in title_tag:
            sku_part = title_tag.split('|')[0].strip()
            if row['brand']:
                brand_pattern = re.escape(row['brand']).replace(r'\ ', r'[\s-]*').replace(r'\-', r'[\s-]*')
                sku_clean = re.sub(r'^' + brand_pattern + r'[\s-]*', '', sku_part, flags=re.I).strip()
                if sku_clean:
                    row['sku'] = sku_clean
                    row['supplier_sku'] = sku_clean
            if not row['sku']:
                row['sku'] = sku_part
                row['supplier_sku'] = sku_part

        title_pos = text.find(row['title'][:25]) if row['title'] else -1
        price_text = text[title_pos:] if title_pos > 0 else text[400:]

        m = re.search(r'\$\s*([\d,.]+)\s*ex', price_text)
        if m: row['price_ex_tax'] = f"${m.group(1)}"

        m = re.search(r'\$\s*([\d,.]+)\s*inc', price_text)
        if m: row['price_inc_tax'] = f"${m.group(1)}"

        stock_matches = re.findall(r'(Gold Coast|Melbourne|Sydney|Perth|Brisbane|New Adelaide)\s*(\d+)\s*In Stock', price_text)
        if stock_matches:
            stock_info = []
            total = 0
            for loc, qty in stock_matches:
                stock_info.append(f"{loc}: {qty}")
                total += int(qty)
            row['stock_status'] = f"In Stock (Total: {total} | " + ', '.join(stock_info) + ')'
        elif 'In Stock' in price_text:
            row['stock_status'] = 'In Stock'
        elif 'Out of Stock' in price_text or 'Sold Out' in price_text:
            row['stock_status'] = 'Out of Stock'

        desc_match = re.search(r'Product Details\s*\nTech Data[^\n]*\nProduct Details\s*\n(.+?)(?:\nFrequently Asked|\nSave to Job|\nPopular Categories)', text, re.S)
        if not desc_match:
            desc_match = re.search(r'Product Details\s*\n(.+?)(?:\nTech Data|\nFrequently Asked|\nSave to Job)', text, re.S)
        if desc_match:
            desc = re.sub(r'\n+', ' | ', desc_match.group(1).strip())
            row['description'] = desc[:2000]

        imgs = []
        product_id = row['tradezone_id']
        for img in page.eles('tag:img', timeout=2):
            src = img.attr('src') or img.attr('data-src') or ''
            alt = img.attr('alt') or ''
            if src and product_id and product_id in src:
                if src not in imgs:
                    imgs.append(src)
            elif src and row['title'] and row['title'][:20] in alt:
                if src not in imgs:
                    imgs.append(src)

        if product_id:
            hi_res = f'https://media.tradezone.com.au/images/still/726/726/{product_id}/30.jpg'
            if hi_res not in imgs:
                imgs.insert(0, hi_res)

        for j, src in enumerate(imgs[:5]):
            row[f'image{j+1}'] = src

        # --- ATTRIBUTES & DETAILED INFO (from product attribute tables) ---
        attrs = []
        warranty_parts = []
        shipping_parts = []
        
        try:
            attribute_tables = page.eles('css:.product-attribute-table')
            
            for table in attribute_tables:
                rows = table.eles('css:.row')
                
                for row_elem in rows:
                    cells = row_elem.eles('css:.cell')
                    if len(cells) >= 2:
                        label_elem = cells[0]
                        value_elem = cells[1]
                        
                        label = ''
                        h4 = label_elem.ele('tag:h4', timeout=0.1)
                        if h4:
                            label = h4.text.strip()
                        else:
                            label = label_elem.text.strip()
                        
                        value = value_elem.text.strip()
                        
                        if not label or not value:
                            continue
                        
                        label_lower = label.lower()
                        
                        if 'part number' in label_lower and not 'also' in label_lower:
                            if not row['part_number']:
                                row['part_number'] = value
                                row['supplier_part_number'] = value
                        
                        elif 'sub category' in label_lower or 'sub group' in label_lower:
                            row['sub_group'] = value
                        
                        elif label_lower == 'barcode':
                            if not row['barcode']:
                                row['barcode'] = value
                        
                        elif 'weight' in label_lower and 'kg' in label_lower:
                            if not row['weight']:
                                row['weight'] = value + ' kg'
                        
                        elif label_lower == 'length (mm)':
                            row['length'] = value
                        elif label_lower == 'height (mm)':
                            row['height'] = value
                        elif label_lower == 'width (mm)':
                            row['width'] = value
                        
                        elif label_lower == 'length packaging (mm)':
                            row['length_packaging'] = value
                        elif label_lower == 'height packaging (mm)':
                            row['height_packaging'] = value
                        elif label_lower == 'width packaging (mm)':
                            row['width_packaging'] = value
                        
                        elif 'freight' in label_lower or 'shipping' in label_lower:
                            shipping_parts.append(f"{label}: {value}")
                        
                        if len(label) < 60 and len(value) < 200:
                            attrs.append(f"{label}: {value}")
        
        except Exception as e:
            print(f"    Warning: Error parsing attribute tables: {str(e)}")
        
        row['attributes'] = '; '.join(attrs[:30]) if attrs else ''
        row['shipping'] = '; '.join(shipping_parts) if shipping_parts else ''
        
        try:
            warranty_match = re.search(r'Warranty Information[:\s]*(.+?)(?:Attributes|Shipping|$)', text, re.S)
            if warranty_match:
                warranty_text = warranty_match.group(1).strip()
                warranty_lines = []
                for line in warranty_text.split('\n'):
                    line = line.strip()
                    if line and len(line) < 200:
                        warranty_lines.append(line)
                if warranty_lines:
                    row['warranty'] = ' | '.join(warranty_lines[:10])
        except:
            pass

        if not row['weight']:
            m = re.search(r'[Ww]eight[:\s]*([0-9.,]+\s*(?:kg|g|lb|grams?))', text)
            if m: row['weight'] = m.group(1)
        if not row['dimensions']:
            m = re.search(r'[Dd]imensions?[:\s]*([0-9.,]+\s*[xX×]\s*[0-9.,]+(?:\s*[xX×]\s*[0-9.,]+)?(?:\s*(?:mm|cm|m))?)', text)
            if m: row['dimensions'] = m.group(1)

    # Print summary
    print(f"  ✓ Scraped: TZ ID {row['tradezone_id']} | SKU {row['sku']}")
    print(f"  Title:    {row['title'][:55]}")
    print(f"  SKU:      {row['sku']}  |  TZ ID: {row['tradezone_id']}  |  Brand: {row['brand']}")
    print(f"  Part#:    {row['part_number'][:30] if row['part_number'] else '-'}")
    print(f"  Price:    {row['price_ex_tax']} ex  /  {row['price_inc_tax']} inc")
    print(f"  Stock:    {row['stock_status'][:60]}")
    print(f"  Desc:     {row['description'][:60]}..." if row['description'] else "  Desc:     -")
    print(f"  Images:   {sum(1 for x in range(1,6) if row[f'image{x}'])}")
    print(f"  Barcode:  {row['barcode'][:30] if row['barcode'] else '-'}")
    print(f"  Dims:     L:{row['length']} H:{row['height']} W:{row['width']}" if row['length'] else f"  Dims:     {row['dimensions']}")
    print(f"  Warranty: {row['warranty'][:40]}..." if row['warranty'] else "  Warranty: -")
    
    # Log product details
    logger.info(f"✓ Product scraped successfully - Search SKU: {search_sku}")
    logger.info(f"  - Tradezone ID: {row['tradezone_id']}, SKU: {row['sku']}, Title: {row['title']}")
    logger.info(f"  - Price: {row['price_ex_tax']} ex / {row['price_inc_tax']} inc")
    logger.info(f"  - Stock: {row['stock_status']}")
    logger.info(f"  - Images: {sum(1 for x in range(1,6) if row[f'image{x}'])}, Barcode: {row['barcode']}")
    
    results.append(row)

# === END OF SCRAPING LOGIC ===

# [REST OF SHOPIFY CONVERSION CODE - SAME AS BEFORE]
# Helper functions for Shopify conversion
def create_handle(title):
    if not title: return ''
    handle = title.lower()
    handle = re.sub(r'[^a-z0-9]+', '-', handle)
    handle = clean_handle(handle)  # Use cleaning function
    return handle

def convert_weight_to_grams(weight_str):
    if not weight_str: return ''
    match = re.search(r'([\d,.]+)\s*(kg|g|grams?|lb)', weight_str.lower())
    if not match: return ''
    value = float(match.group(1).replace(',', ''))
    unit = match.group(2).lower()
    if 'kg' in unit: return str(int(value * 1000))
    elif 'lb' in unit: return str(int(value * 453.592))
    else: return str(int(value))

def parse_price(price_str):
    if not price_str: return ''
    match = re.search(r'[\d,.]+', price_str)
    if match: return match.group(0).replace(',', '')
    return ''

def extract_stock_qty(stock_status):
    if not stock_status: return '0'
    match = re.search(r'Total:\s*(\d+)', stock_status)
    if match: return match.group(1)
    elif 'In Stock' in stock_status: return '0'
    return '0'

def extract_dimensions(dim_str):
    if not dim_str: return '', '', ''
    match = re.search(r'([\d.]+)\s*[xX×]\s*([\d.]+)\s*[xX×]\s*([\d.]+)', dim_str)
    if match: return match.group(1), match.group(2), match.group(3)
    match = re.search(r'([\d.]+)\s*[xX×]\s*([\d.]+)', dim_str)
    if match: return match.group(1), match.group(2), ''
    return '', '', ''

def format_description_html(description):
    if not description: return ''
    desc = description.replace(' | ', '<br/>\n')
    return f'<p>{desc}</p>'

def format_attributes_html(attributes):
    if not attributes: return ''
    attrs = attributes.split('; ')
    formatted = '<br/>\n'.join(attrs)
    return formatted

def create_tags_from_title(title):
    if not title: return ''
    words = title.split()
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
    tags = [w for w in words if w.lower() not in stop_words and len(w) > 2]
    return ','.join(tags[:10])

shopify_fields = [
    'Handle', 'Title', 'Body (HTML)', 'Vendor', 'Type', 'Tags', 'Status',
    'Option1 Name', 'Option1 Value', 'Variant SKU', 'Variant Grams', 'Variant Weight Unit',
    'Variant Inventory Tracker', 'Variant Inventory Qty', 'Variant Inventory Policy',
    'Variant Fulfillment Service', 'Variant Price', 'Cost per item', 'Variant Requires Shipping',
    'Variant Taxable', 'Variant Barcode', 'Image Src', 'Image Position', 'Image Alt Text',
    'Tradezone Part Number (product.metafields.custom.part_number)',
    'Supplier Part Number (product.metafields.custom.supplier_part_number)',
    'Sub Group (product.metafields.custom.sub_group)',
    'Warranty Information (product.metafields.custom.warranty)',
    'Attributes (product.metafields.custom.attributes)',
    'Shipping Information (product.metafields.custom.shipping)',
    'Length (product.metafields.custom.length)',
    'Height (product.metafields.custom.height)',
    'Width (product.metafields.custom.width)',
    'Length Packaging (product.metafields.custom.length_packaging)',
    'Height Packaging (product.metafields.custom.height_packaging)',
    'Width Packaging (product.metafields.custom.width_packaging)',
    'Barcode (product.metafields.custom.barcode)'  # Changed from tradezone to custom
]

print(f"\n{'='*60}")
print("Converting to Shopify CSV format...")
print(f"{'='*60}")

shopify_rows = []

for row in results:
    if not row['title']: continue
    
    handle = create_handle(row['title'])
    weight_grams = convert_weight_to_grams(row['weight'])
    price = parse_price(row['price_inc_tax'])
    cost = parse_price(row['price_ex_tax'])
    tags = create_tags_from_title(row['title'])
    stock_qty = extract_stock_qty(row['stock_status'])
    # Extract dimensions - use the scraped values first, fallback to parsing if empty
    if row['length'] and row['height'] and row['width']:
        length, height, width = row['length'], row['height'], row['width']
    else:
        length, height, width = extract_dimensions(row['dimensions'])
    
    if row['length_packaging'] and row['height_packaging'] and row['width_packaging']:
        length_pkg, height_pkg, width_pkg = row['length_packaging'], row['height_packaging'], row['width_packaging']
    else:
        length_pkg, height_pkg, width_pkg = extract_dimensions(row['dimensions_packaging'])
    
    # Format warranty as HTML-free text
    warranty_text = ''
    if row['warranty']:
        warranty_text = clean_html_text(row['warranty'])
    
    # Format shipping as HTML-free text
    shipping_text = ''
    if row['shipping']:
        shipping_text = clean_html_text(row['shipping'])
    
    # Format attributes as HTML-free text
    attrs_text = ''
    if row['attributes']:
        attrs_text = clean_html_text(row['attributes'])
    
    # Format description and attributes as HTML
    body_html = format_description_html(row['description'])
    attrs_html = format_attributes_html(row['attributes'])
    
    # Build complete body HTML with description, attributes, warranty, and shipping
    body_parts = []
    if body_html:
        body_parts.append(body_html)
    
    if attrs_html:
        body_parts.append('<p>Attributes:</p>\n<p>' + attrs_html + '</p>')
    
    if row['warranty']:
        warranty_html = row['warranty'].replace(' | ', '<br/>\n')
        body_parts.append('<p>Warranty Information:</p>\n<p>' + warranty_html + '</p>')
    
    if row['shipping']:
        shipping_html = row['shipping'].replace('; ', '<br/>\n')
        body_parts.append('<p>Shipping Information:</p>\n<p>' + shipping_html + '</p>')
    
    body_html = '\n'.join(body_parts) if body_parts else ''
    
    # Clean Body HTML - remove Tradezone references but keep HTML tags
    body_html = clean_body_html(body_html) if body_html else ''
    
    main_row = {
        'Handle': handle,
        'Title': row['title'],
        'Body (HTML)': body_html,
        'Vendor': row['brand'],
        'Type': '',
        'Tags': tags,
        'Status': 'active',
        'Option1 Name': 'Title',
        'Option1 Value': 'Default Title',
        'Variant SKU': row['sku'],
        'Variant Grams': weight_grams,
        'Variant Weight Unit': 'kg' if weight_grams else '',
        'Variant Inventory Tracker': 'shopify',
        'Variant Inventory Qty': stock_qty,
        'Variant Inventory Policy': 'deny',
        'Variant Fulfillment Service': 'manual',
        'Variant Price': price,
        'Cost per item': cost,
        'Variant Requires Shipping': 'TRUE',
        'Variant Taxable': 'TRUE',
        'Variant Barcode': row['barcode'],
        'Image Src': row['image1'],
        'Image Position': '1' if row['image1'] else '',
        'Image Alt Text': '',
        'Tradezone Part Number (product.metafields.custom.part_number)': str(row['search_sku']).strip() if row['search_sku'] else '',  # Use search SKU
        'Supplier Part Number (product.metafields.custom.supplier_part_number)': row['supplier_part_number'] or row['sku'],
        'Sub Group (product.metafields.custom.sub_group)': row['sub_group'],
        'Warranty Information (product.metafields.custom.warranty)': warranty_text,  # Cleaned text
        'Attributes (product.metafields.custom.attributes)': attrs_text,  # Cleaned text
        'Shipping Information (product.metafields.custom.shipping)': shipping_text,  # Cleaned text
        'Length (product.metafields.custom.length)': length,
        'Height (product.metafields.custom.height)': height,
        'Width (product.metafields.custom.width)': width,
        'Length Packaging (product.metafields.custom.length_packaging)': length_pkg,
        'Height Packaging (product.metafields.custom.height_packaging)': height_pkg,
        'Width Packaging (product.metafields.custom.width_packaging)': width_pkg,
        'Barcode (product.metafields.custom.barcode)': row['barcode']  # Changed from tradezone to custom
    }
    
    shopify_rows.append(main_row)
    
    for img_num in range(2, 6):
        img_key = f'image{img_num}'
        if row[img_key]:
            img_row = {field: '' for field in shopify_fields}
            img_row['Handle'] = handle
            img_row['Image Src'] = row[img_key]
            img_row['Image Position'] = str(img_num)
            shopify_rows.append(img_row)

fname = f'tradezone_shopify_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
with open(fname, 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=shopify_fields)
    w.writeheader()
    for srow in shopify_rows:
        w.writerow(srow)

print(f"\n{'='*60}")
print(f"SAVED: {fname}")
print(f"Total Products Scraped: {len(results)}")
print(f"Total Shopify Rows (with images): {len(shopify_rows)}")

logger.info("="*80)
logger.info(f"CSV SAVED: {fname}")
logger.info(f"Total Products Scraped: {len(results)}")
logger.info(f"Total Shopify Rows (with images): {len(shopify_rows)}")
logger.info("="*80)


# ==============================
# SHOPIFY API CONFIG
# ==============================
import requests
from collections import defaultdict
import base64

# ==============================
# IMAGE DOWNLOAD FUNCTION
# ==============================
def download_image_as_base64(url):
    """Download image from Tradezone with proper headers and convert to base64"""
    try:
        # Use headers to mimic browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.tradezone.com.au/',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            # Convert to base64
            image_base64 = base64.b64encode(response.content).decode('utf-8')
            
            # Determine image type from URL
            if url.lower().endswith('.png'):
                mime_type = 'image/png'
            elif url.lower().endswith('.gif'):
                mime_type = 'image/gif'
            elif url.lower().endswith('.webp'):
                mime_type = 'image/webp'
            else:
                mime_type = 'image/jpeg'  # Default to JPEG
            
            return f"data:{mime_type};base64,{image_base64}"
        else:
            print(f"    ⚠️  Failed to download image: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        print(f"    ⚠️  Error downloading image: {str(e)}")
        return None

SHOP_NAME = os.getenv('SHOPIFY_SHOP_NAME')
ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
API_VERSION = os.getenv('SHOPIFY_API_VERSION')

BASE_URL = f"https://{SHOP_NAME}.myshopify.com/admin/api/{API_VERSION}"

headers = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

def create_product(product_data):
    url = f"{BASE_URL}/products.json"
    response = requests.post(url, json=product_data, headers=headers)
    if response.status_code == 201:
        product = response.json()['product']
        print(f"✓ Created: {product['title']} (ID: {product['id']})")
        logger.info(f"✓ SHOPIFY UPLOAD SUCCESS - Product ID: {product['id']}")
        logger.info(f"  - Title: {product['title']}")
        logger.info(f"  - Handle: {product['handle']}")
        logger.info(f"  - Variants: {len(product.get('variants', []))}")
        
        # Show image upload status
        if 'images' in product and product['images']:
            print(f"  ✓ Images uploaded successfully: {len(product['images'])} image(s)")
            logger.info(f"  - Images uploaded: {len(product['images'])} image(s)")
        elif product_data['product'].get('images'):
            print(f"  ⚠️  Images sent but not all confirmed")
            logger.warning(f"  - Images sent but not all confirmed")
        else:
            print(f"  ⚠️  No images were uploaded")
            logger.warning(f"  - No images were uploaded")
        
        print(f"  ✓ Product created successfully!")
        logger.info(f"  - Metafields: {len(product.get('metafields', []))} created")
        return product
    else:
        print(f"✗ Failed: {response.status_code} - {response.text}")
        print(f"  ✗ Failed to create product")
        logger.error(f"✗ SHOPIFY UPLOAD FAILED - Status: {response.status_code}")
        logger.error(f"  - Error: {response.text}")
        return None


# ==============================
# GROUP ROWS BY HANDLE
# ==============================
products_grouped = defaultdict(list)

for row in shopify_rows:
    if row.get('Handle'):
        products_grouped[row['Handle']].append(row)


print("\n" + "="*60)
print("UPLOADING PRODUCTS TO SHOPIFY WITH METAFIELDS")
print("="*60 + "\n")

logger.info("="*80)
logger.info("STARTING SHOPIFY API UPLOAD")
logger.info(f"Total products to upload: {len(products_grouped)}")
logger.info("="*80)

upload_success_count = 0
upload_fail_count = 0

for handle, rows in products_grouped.items():
    main = rows[0]

    # Images - Download and convert to base64
    images = []
    image_urls_to_download = []
    
    # Collect all image URLs from rows
    for r in rows:
        if r.get('Image Src'):
            image_urls_to_download.append(r['Image Src'])
    
    # Debug: Show images being downloaded
    if image_urls_to_download:
        print(f"  Downloading images: {len(image_urls_to_download)}")
        
        for idx, img_url in enumerate(image_urls_to_download, 1):
            print(f"    {idx}. {img_url[:70]}...")
            
            # Download and convert to base64
            base64_image = download_image_as_base64(img_url)
            
            if base64_image:
                images.append({"attachment": base64_image})
                print(f"       ✓ Downloaded successfully")
            else:
                print(f"       ✗ Failed to download")
    else:
        print(f"  ⚠️  WARNING: No images found for this product!")

    # Variant
    # Get barcode value and ensure it's properly formatted
    barcode_value = main.get('Variant Barcode', '').strip()
    
    variant = {
        "option1": main.get('Option1 Value', 'Default Title'),
        "price": main.get('Variant Price', '0'),
        "sku": main.get('Variant SKU', ''),
        "inventory_management": "shopify",
        "inventory_policy": main.get('Variant Inventory Policy', 'deny'),
        "fulfillment_service": main.get('Variant Fulfillment Service', 'manual'),
        "requires_shipping": True,
        "taxable": True,
        "weight": float(main.get('Variant Grams') or 0),
        "weight_unit": main.get('Variant Weight Unit') or 'kg'
    }
    
    # Add barcode to variant ONLY if it exists (Shopify doesn't like empty barcode strings)
    if barcode_value:
        variant["barcode"] = barcode_value
        print(f"  Variant Barcode: {barcode_value}")
    else:
        print(f"  ⚠️  WARNING: No barcode found in CSV for this product!")

    # ========================================
    # EXTRACT AND FORMAT METAFIELDS
    # ========================================
    metafields = []
    
    # Helper function to add metafield if value exists
    def add_metafield(namespace, key, value, field_type):
        """Add metafield only if value is not empty"""
        if value and str(value).strip():
            metafields.append({
                "namespace": namespace,
                "key": key,
                "value": str(value).strip(),
                "type": field_type
            })
    
    # Get search_sku for part_number (from CSV column)
    part_number_value = main.get('Tradezone Part Number (product.metafields.custom.part_number)', '').strip()
    
    # Custom namespace metafields (text fields)
    add_metafield("custom", "part_number", 
                 part_number_value,  # Using search_sku from CSV
                 "single_line_text_field")
    
    add_metafield("custom", "supplier_part_number", 
                 main.get('Supplier Part Number (product.metafields.custom.supplier_part_number)'), 
                 "single_line_text_field")
    
    add_metafield("custom", "sub_group", 
                 main.get('Sub Group (product.metafields.custom.sub_group)'), 
                 "single_line_text_field")
    
    add_metafield("custom", "warranty", 
                 main.get('Warranty Information (product.metafields.custom.warranty)'), 
                 "multi_line_text_field")
    
    add_metafield("custom", "attributes", 
                 main.get('Attributes (product.metafields.custom.attributes)'), 
                 "multi_line_text_field")
    
    add_metafield("custom", "shipping", 
                 main.get('Shipping Information (product.metafields.custom.shipping)'), 
                 "multi_line_text_field")
    
    # Dimension metafields (as TEXT to match Shopify definitions)
    add_metafield("custom", "length", 
                 main.get('Length (product.metafields.custom.length)'), 
                 "single_line_text_field")
    
    add_metafield("custom", "height", 
                 main.get('Height (product.metafields.custom.height)'), 
                 "single_line_text_field")
    
    add_metafield("custom", "width", 
                 main.get('Width (product.metafields.custom.width)'), 
                 "single_line_text_field")
    
    add_metafield("custom", "length_packaging", 
                 main.get('Length Packaging (product.metafields.custom.length_packaging)'), 
                 "single_line_text_field")
    
    add_metafield("custom", "height_packaging", 
                 main.get('Height Packaging (product.metafields.custom.height_packaging)'), 
                 "single_line_text_field")
    
    add_metafield("custom", "width_packaging", 
                 main.get('Width Packaging (product.metafields.custom.width_packaging)'), 
                 "single_line_text_field")
    
    # Barcode metafield - use CUSTOM namespace (not tradezone)
    add_metafield("custom", "barcode",  # Changed from "tradezone" to "custom"
                 main.get('Barcode (product.metafields.custom.barcode)', '').strip(),  # Get from correct CSV column
                 "single_line_text_field")

    # Build product payload with metafields
    product_payload = {
        "product": {
            "title": main['Title'],
            "body_html": main.get('Body (HTML)', ''),
            "vendor": main.get('Vendor', ''),
            "tags": main.get('Tags', ''),
            "status": main.get('Status', 'active'),
            "variants": [variant],
            "images": images,
            "metafields": metafields  # <-- METAFIELDS ADDED HERE
        }
    }

    # Debug: Show what we're sending
    barcode_metafield = main.get('Barcode (product.metafields.custom.barcode)', '').strip()
    print(f"\nProcessing: {main['Title'][:60]}")
    print(f"  Search SKU (for part_number): {part_number_value}")
    print(f"  Variant Barcode: {barcode_value}")
    print(f"  Barcode Metafield (custom.barcode): {barcode_metafield}")
    print(f"  Metafields to create: {len(metafields)}")
    for mf in metafields:
        print(f"    - {mf['namespace']}.{mf['key']}: {mf['value'][:40]}...")
    
    # Create product
    logger.info(f"Attempting to upload: {main['Title'][:60]}")
    created_product = create_product(product_payload)
    
    if created_product:
        print(f"  ✓ Product created successfully!")
        upload_success_count += 1
    else:
        print(f"  ✗ Failed to create product")
        upload_fail_count += 1

print("\n" + "="*60)
print("All products processed.")
print("="*60)

# Log upload summary
logger.info("="*80)
logger.info("SHOPIFY UPLOAD SUMMARY")
logger.info(f"Total products attempted: {len(products_grouped)}")
logger.info(f"Successfully uploaded: {upload_success_count}")
logger.info(f"Failed uploads: {upload_fail_count}")
logger.info("="*80)


print(f"\n{'Search':<9} {'SKU':<8} {'PriceEx':<9} {'PriceInc':<9} {'Imgs':<5} {'Stock':<12} Title")
print("-"*75)
for r in results:
    t = r['title'][:25] + '..' if len(r['title']) > 25 else r['title']
    s = r['stock_status'][:10] if r['stock_status'] else '-'
    print(f"{r['search_sku']:<9} {r['sku']:<8} {r['price_ex_tax']:<9} {r['price_inc_tax']:<9} {sum(1 for x in range(1,6) if r[f'image{x}']):<5} {s:<12} {t or 'NOT FOUND'}")

page.quit()
print("\nDONE!")

logger.info("="*80)
logger.info("SESSION COMPLETED SUCCESSFULLY")
logger.info(f"Total SKUs searched: {len(SKUS)}")
logger.info(f"Total products scraped: {len(results)}")
logger.info(f"CSV file saved: {fname}")
logger.info(f"Shopify uploads - Success: {upload_success_count}, Failed: {upload_fail_count}")
logger.info(f"Log file saved: {log_filename}")
logger.info("="*80)