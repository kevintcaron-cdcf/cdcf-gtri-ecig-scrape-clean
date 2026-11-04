// Execute after elementvape_browser_extract.js on a rendered product page.
// Keeps a resumable compact record set in localStorage and downloads the full
// JSONL staging file after every product. The browser MCP response only returns
// counts, avoiding large HTML responses through the MCP channel.
(() => {
  const key = 'elementvape-browser-staging-v1';
  const raw = localStorage.getItem(key);
  const records = raw ? JSON.parse(raw) : [];
  const record = (() => {
    const blockedMarkers = ['verify you are human', 'access denied', 'just a moment', 'security check', 'checking your browser', 'captcha'];
    const plainText = document.body?.innerText || '';
    if (blockedMarkers.some(x => plainText.toLowerCase().includes(x))) {
      return {blocked: true, url: location.href, plain_text: plainText.slice(0, 5000)};
    }
    const products = [];
    for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const value = JSON.parse(node.textContent || '');
        for (const item of (Array.isArray(value) ? value : [value])) {
          if (item && (item['@type'] === 'Product' || (Array.isArray(item['@type']) && item['@type'].includes('Product')))) products.push(item);
        }
      } catch (_) {}
    }
    const product = products[0] || {};
    const offer = Array.isArray(product.offers) ? product.offers[0] : (product.offers || {});
    const canonical = new URL(product.url || location.href, location.origin);
    const brand = typeof product.brand === 'object' ? product.brand?.name : product.brand;
    const image = Array.isArray(product.image) ? product.image[0] : product.image;
    return {
      source: 'chrome-mcp-rendered-dom', scraped_at: new Date().toISOString(), blocked: false,
      url: canonical.href, site_tag: canonical.pathname.replace(/\/$/, '').split('/').pop(),
      title: product.name || document.querySelector('h1')?.innerText?.trim() || '', sku: product.sku || '',
      brand: brand || '', price: offer.price == null ? '' : String(offer.price),
      stock_status: /outofstock/i.test(String(offer.availability || '')) ? 'Out of Stock' : (/instock/i.test(String(offer.availability || '')) ? 'In Stock' : ''),
      image_url: image || '', description: String(product.description || '').replace(/\u0026nbsp;/g, ' ').trim(),
      html: document.documentElement.outerHTML, plain_text: plainText,
    };
  })();
  if (!record.blocked && record.url && record.site_tag) {
    const index = records.findIndex(item => item.url === record.url);
    if (index >= 0) records[index] = record; else records.push(record);
    localStorage.setItem(key, JSON.stringify(records));
  }
  const jsonl = records.map(item => JSON.stringify(item)).join('\n') + (records.length ? '\n' : '');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([jsonl], {type: 'application/jsonl'}));
  link.download = 'elementvape-browser-staging.jsonl';
  link.click();
  return {saved: !record.blocked, blocked: !!record.blocked, records: records.length, download: link.download, url: location.href};
})();
