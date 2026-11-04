// Execute on a fully rendered Element Vape category page with chrome_javascript.
// It downloads a compact URL queue; product pages are then visited one at a time.
(() => {
  const category = location.pathname;
  const ignored = new Set([
    '/new-arrivals', '/brands', '/starter-kits', '/e-liquids', '/hemp',
    '/vaporizers', '/nicotine-pouches', '/glass', '/cigars', '/accessories',
    '/tanks', '/disposable', '/50k-puff-disposables', '/nicotine-free-vape',
    '/best-disposables', '/disposables-bogo', '/usa-disposable-vapes',
    '/delta-8-disposables', '/vaporesso-promo', '/lyco-mini-box-50k-disposable',
  ]);
  const urls = [];
  for (const anchor of document.querySelectorAll('a[href]')) {
    try {
      const url = new URL(anchor.href);
      const path = url.pathname.replace(/\/$/, '');
      if (url.hostname !== 'www.elementvape.com' || ignored.has(path) ||
          path.split('/').filter(Boolean).length !== 1) continue;
      const context = (anchor.closest('article, li, div')?.innerText || '').toLowerCase();
      if (!context.includes('$') && !anchor.querySelector('img')) continue;
      if (!urls.includes(url.href)) urls.push(url.href);
    } catch (_) {}
  }
  const result = {source: 'chrome-mcp-category-dom', category, scraped_at: new Date().toISOString(), urls};
  const blob = new Blob([JSON.stringify(result, null, 2)], {type: 'application/json'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `elementvape-${category.replace(/\//g, '') || 'category'}-links.json`;
  link.click();
  return {category, urls: urls.length, download: link.download};
})();
