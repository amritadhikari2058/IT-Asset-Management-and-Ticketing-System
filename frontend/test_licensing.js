function testMatchRoute(hash) {
  var route = hash.split('?')[0];
  // Licensing routes from App.jsx - note: routes use #/licensing/products format
  // but hash from URL is #licensing/products (with # prefix)
  // The actual App.jsx code handles both patterns
  
  // Pattern 1: route === '#licensing' (root)
  if (route === '#licensing') return 'LicensingRouter (root)';
  
  // Pattern 2: route startsWith '#/licensing/products' 
  // But route from hash is '#licensing/products' - need to check both
  if (route === '#licensing/products' || route.startsWith('#/licensing/products')) return 'LicensingRouter (products)';
  if (route === '#licensing/agreements' || route.startsWith('#/licensing/agreements')) return 'LicensingRouter (agreements)';
  if (route === '#licensing/allocations' || route.startsWith('#/licensing/allocations')) return 'LicensingRouter (allocations)';
  if (route === '#licensing/secrets' || route.startsWith('#/licensing/secrets')) return 'LicensingRouter (secrets)';
  if (route === '#licensing/installations' || route.startsWith('#/licensing/installations')) return 'LicensingRouter (installations)';
  if (route === '#licensing/renewals' || route.startsWith('#/licensing/renewals')) return 'LicensingRouter (renewals)';
  if (route === '#licensing/compliance' || route.startsWith('#/licensing/compliance')) return 'LicensingRouter (compliance)';
  if (route === '#licensing/documents' || route.startsWith('#/licensing/documents')) return 'LicensingRouter (documents)';
  if (route === '#licensing/history' || route.startsWith('#/licensing/history')) return 'LicensingRouter (history)';
  if (route === '#licensing/history/' || route.startsWith('#/licensing/history/')) return 'LicensingRouter (history detail)';
  if (route === '#licensing/products' || route.startsWith('#/licensing/products/')) return 'LicensingRouter (products detail)';
  
  return 'No match';
}

console.log('=== Licensing Route Matching Tests ===');
console.log('Test 1 - #licensing/products:', testMatchRoute('#licensing/products'));
console.log('Test 2 - #licensing/agreements:', testMatchRoute('#licensing/agreements'));
console.log('Test 3 - #licensing root:', testMatchRoute('#licensing'));
console.log('Test 4 - #licensing/products/5:', testMatchRoute('#licensing/products/5'));
console.log('Test 5 - #tickets:', testMatchRoute('#tickets'));
console.log('Test 6 - #licensing/installations:', testMatchRoute('#licensing/installations'));
console.log('Test 7 - #licensing/renewals:', testMatchRoute('#licensing/renewals'));
console.log('===============================');