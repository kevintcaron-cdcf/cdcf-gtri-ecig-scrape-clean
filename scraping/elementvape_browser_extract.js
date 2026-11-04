// Run this in the active Element Vape page through chrome_javascript.
// It extracts one rendered product page without making direct HTTP requests.
// The result is JSON-serializable and can be appended to a staging JSONL file.
(() => {
  const blockedMarkers = [
    'verify you are human', 'access denied', 'just a moment',
    'security check', 'checking your browser', 'captcha'
  ];
  const plainText = document.body?.innerText || '';
  const blocked = blockedMarkers.some(marker =>
    plainText.toLowerCase().includes(marker)
  );
  if (blocked) {
    return {blocked: true, url: location.href, plain_text: plainText.slice(0, 5000)};
  }

  const jsonLd = [];
  for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const value = JSON.parse(node.textContent || '');
      for (const item of (Array.isArray(value) ? value : [value])) {
        if (item && (item['@type'] === 'Product' ||
            (Array.isArray(item['@type']) && item['@type'].includes('Product')))) {
          jsonLd.push(item);
        }
      }
    } catch (_) {
      // Ignore malformed third-party JSON-LD blocks.
    }
  }
  const product = jsonLd[0] || {};
  const offer = Array.isArray(product.offers) ? product.offers[0] : (product.offers || {});
  const brand = typeof product.brand === 'object' ? product.brand?.name : product.brand;
  const canonical = new URL(product.url || location.href, location.origin).href;
  if (new URL(canonical).hostname !== 'www.elementvape.com') {
    return {blocked: true, reason: 'non-Element Vape product URL', url: canonical};
  }
  const tag = new URL(canonical).pathname.replace(/\/+$/, '').split('/').pop() || '';
  const image = Array.isArray(product.image) ? product.image[0] : product.image;

  return {
    source: 'chrome-mcp-rendered-dom',
    scraped_at: new Date().toISOString(),
    blocked: false,
    url: canonical,
    site_tag: tag,
    title: product.name || document.querySelector('h1')?.innerText?.trim() || '',
    sku: product.sku || '',
    brand: brand || '',
    price: offer.price == null ? '' : String(offer.price),
    stock_status: /outofstock/i.test(String(offer.availability || '')) ? 'Out of Stock' :
      (/instock/i.test(String(offer.availability || '')) ? 'In Stock' : ''),
    image_url: image || '',
    description: String(product.description || '').replace(/\u0026nbsp;/g, ' ').trim(),
    // Keep the full rendered DOM in the downloaded JSONL record. The MCP
    // response itself may sanitize or truncate large HTML values.
    html: document.documentElement.outerHTML,
    plain_text: plainText,
  };
})();
