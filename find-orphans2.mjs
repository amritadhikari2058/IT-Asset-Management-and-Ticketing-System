import fs from 'fs';
import path from 'path';

const SRC = path.resolve('D:/IT-Asset-Management-and-Ticketing-System/frontend/src');
const files = [];

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!['node_modules', '.git', 'dist'].includes(entry.name)) walk(full);
    } else if (/\.(js|jsx|ts|tsx)$/.test(entry.name)) {
      files.push(full);
    }
  }
}
walk(SRC);

const imported = new Set();
const importRegex = /(?:from|import)\s+['"](\.[^'"]+)['"]/g;

for (const f of files) {
  const content = fs.readFileSync(f, 'utf8');
  let m;
  while ((m = importRegex.exec(content)) !== null) {
    const mod = m[1];
    if (!mod.startsWith('.')) continue;
    const base = path.dirname(f);
    const candidates = [
      path.resolve(base, mod + '.js'),
      path.resolve(base, mod + '.jsx'),
      path.resolve(base, mod + '.ts'),
      path.resolve(base, mod + '.tsx'),
      path.resolve(base, mod, 'index.js'),
      path.resolve(base, mod, 'index.jsx'),
      path.resolve(base, mod, 'index.ts'),
      path.resolve(base, mod, 'index.tsx'),
    ];
    for (const c of candidates) {
      if (fs.existsSync(c)) imported.add(c);
    }
  }
}

// Check index.html for entry
const html = fs.readFileSync('D:/IT-Asset-Management-and-Ticketing-System/frontend/index.html', 'utf8');
const scriptMatch = html.match(/<script[^>]*src=["']([^"']+)["']/);
if (scriptMatch) {
  const entry = scriptMatch[1].replace('./', '');
  const entryPath = path.resolve('D:/IT-Asset-Management-and-Ticketing-System/frontend', entry);
  imported.add(entryPath);
}

// Also add main.jsx as it's the Vite entry
imported.add(path.resolve(SRC, 'main.jsx'));

const orphaned = files.filter(f => !imported.has(f) && !path.basename(f).startsWith('index.'));
console.log('=== ORPHANED SOURCE FILES (never imported) ===');
for (const o of orphaned.sort()) {
  console.log(path.relative(SRC, o));
}
console.log(`Total: ${orphaned.length}`);