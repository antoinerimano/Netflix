#!/usr/bin/env node
// npm run i18n:check - the translations are complete and consistent:
//  1. every language has every key of English (and no leftovers),
//  2. plural keys have every form the language needs (CLDR rules via Intl.PluralRules:
//     English one / other, French one / many / other, Japanese other...),
//  3. a translation keeps the {{placeholders}} and <tags> of the English text,
//  4. every literal key used in src/ (t('ns:key'), i18nKey="key") exists in English.
// Exits 1 on any problem (CI / pre-commit).
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', 'src');
const LOCALES = path.join(SRC, 'i18n', 'locales');
const BASE = 'en';
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;
const CONTEXT_FILE_NS = /useTranslation\(\s*['"](\w+)['"]/;

const problems = [];
const report = (msg) => problems.push(msg);

function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) flatten(v, key, out);
    else out[key] = v;
  }
  return out;
}

function load(lng) {
  const dir = path.join(LOCALES, lng);
  const out = {};
  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith('.json'))) {
    const ns = file.replace(/\.json$/, '');
    try {
      out[ns] = flatten(JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8')));
    } catch (e) {
      report(`${lng}/${file}: invalid JSON (${e.message})`);
      out[ns] = {};
    }
  }
  return out;
}

const tokens = (value) => {
  const text = Array.isArray(value) ? value.join('\n') : String(value ?? '');
  const vars = [...text.matchAll(/\{\{\s*([\w.]+)[^}]*\}\}/g)].map((m) => m[1]);
  const tags = [...text.matchAll(/<\/?(\w+)\s*\/?>/g)].map((m) => m[0].replace(/\s/g, ''));
  return { vars: [...new Set(vars)].sort().join(','), tags: tags.sort().join(',') };
};

// a plural form may leave the number out ("Top result" for 1): {{count}} is optional there
const withoutCount = (vars) => vars.split(',').filter((v) => v && v !== 'count').join(',');

/** "a.b_one" -> "a.b" (plural base) when English has a plural form of it */
const pluralBase = (key) => key.replace(PLURAL_SUFFIX, '');

const languages = fs.readdirSync(LOCALES).filter((d) => fs.statSync(path.join(LOCALES, d)).isDirectory());
const base = load(BASE);

// <Trans> components can't use HTML void element names: their text is dropped (an empty link)
const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
for (const [ns, table] of Object.entries(base)) {
  for (const [key, value] of Object.entries(table)) {
    for (const m of String(Array.isArray(value) ? value.join(' ') : value).matchAll(/<(\w+)>/g)) {
      if (VOID_TAGS.has(m[1].toLowerCase())) report(`en/${ns}: "${key}" uses <${m[1]}>, a void HTML tag: its text won't render - rename it`);
    }
  }
}


for (const lng of languages.filter((l) => l !== BASE)) {
  const cats = new Intl.PluralRules(lng).resolvedOptions().pluralCategories;
  const data = load(lng);
  for (const ns of Object.keys(base)) {
    const en = base[ns];
    const tr = data[ns];
    if (!tr) {
      report(`${lng}: missing namespace ${ns}.json`);
      continue;
    }
    const enPluralBases = new Set(Object.keys(en).filter((k) => PLURAL_SUFFIX.test(k)).map(pluralBase));
    // plain keys: same as English
    for (const [key, value] of Object.entries(en)) {
      if (PLURAL_SUFFIX.test(key)) continue;
      if (!(key in tr)) report(`${lng}/${ns}: missing "${key}"`);
      else if (!tr[key] || (Array.isArray(value) && (!Array.isArray(tr[key]) || tr[key].length !== value.length))) {
        report(`${lng}/${ns}: "${key}" is empty or has the wrong shape`);
      } else {
        const a = tokens(value);
        const b = tokens(tr[key]);
        if (a.vars !== b.vars) report(`${lng}/${ns}: "${key}" placeholders {${b.vars}} should be {${a.vars}}`);
        if (a.tags !== b.tags) report(`${lng}/${ns}: "${key}" tags [${b.tags}] should be [${a.tags}]`);
      }
    }
    // plural keys: every category of this language
    for (const pb of enPluralBases) {
      const enVars = tokens(en[`${pb}_other`]).vars;
      for (const cat of cats) {
        const k = `${pb}_${cat}`;
        if (!tr[k]) report(`${lng}/${ns}: missing plural form "${k}"`);
        else if (withoutCount(tokens(tr[k]).vars) !== withoutCount(enVars)) {
          report(`${lng}/${ns}: "${k}" placeholders differ from English`);
        }
      }
    }
    // leftovers
    for (const key of Object.keys(tr)) {
      const known = key in en || (PLURAL_SUFFIX.test(key) && enPluralBases.has(pluralBase(key)));
      if (!known) report(`${lng}/${ns}: unused key "${key}" (not in English)`);
    }
  }
}

// keys used in the code
function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'locales') yield* walk(p);
    } else if (/\.(js|jsx|ts|tsx)$/.test(entry.name)) yield p;
  }
}
const exists = (ns, key) => {
  const table = base[ns] || {};
  if (key in table) return true;
  if (Object.keys(table).some((k) => k.startsWith(`${key}.`) || k.startsWith(`${key}_`))) return true; // objects / plurals / contexts
  return false;
};
for (const file of walk(SRC)) {
  const code = fs.readFileSync(file, 'utf8');
  if (!/useTranslation|i18n\.t\(|i18nKey/.test(code)) continue;
  const fileNs = (code.match(CONTEXT_FILE_NS) || [])[1] || 'common';
  const uses = [
    ...[...code.matchAll(/\bt\(\s*['"]([\w.:-]+)['"]/g)].map((m) => m[1]),
    ...[...code.matchAll(/i18nKey=["']([\w.:-]+)["']/g)].map((m) => m[1]),
  ];
  for (const raw of uses) {
    const [ns, key] = raw.includes(':') ? raw.split(':') : [fileNs, raw];
    if (!exists(ns, key) && !exists('common', key)) {
      report(`${path.relative(SRC, file)}: key "${raw}" not found in ${BASE}/${ns}.json`);
    }
  }
}

if (problems.length) {
  console.error(`i18n: ${problems.length} problem(s)\n - ${problems.join('\n - ')}`);
  process.exit(1);
}
console.log(`i18n: OK - ${languages.length} languages, ${Object.values(base).reduce((n, t) => n + Object.keys(t).length, 0)} English strings`);
