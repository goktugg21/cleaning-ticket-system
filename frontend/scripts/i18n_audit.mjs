/**
 * i18n key audit -- every literal t() key in src/, against both bundles.
 *
 * Why this exists: two waves shipped raw keys to the owner's screen
 * (`archive.show`, `archive.show_working`, `period.label`,
 * `change.moved_to`). The strings were present in both bundles the whole
 * time. What was missing was `react: { nsMode: "fallback" }` -- without it
 * react-i18next binds `useTranslation(["page", "common"])` to `page` ALONE
 * (see react-i18next/useTranslation.js), so every key living in common.json
 * rendered as its own name.
 *
 * So this script reports two different things:
 *   MISSING  -- the key is in no bound namespace, in one or both languages.
 *              A real untranslated key. Fails the run.
 *   NS-FALLBACK -- the key is absent from the FIRST bound namespace but
 *              present in a later one. These are exactly the keys that were
 *              broken before nsMode:"fallback", and that break again if
 *              anyone removes it.
 *
 * Run: node scripts/i18n_audit.mjs
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = new URL("../src/", import.meta.url).pathname;
const I18N = join(SRC, "i18n");
const LANGS = ["nl", "en"];

// i18next appends these to a key when the caller passes a `count`.
const PLURAL_SUFFIXES = ["", "_zero", "_one", "_two", "_few", "_many", "_other"];

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) { if (entry !== "i18n") walk(p, acc); }
    else if (/\.tsx?$/.test(entry)) acc.push(p);
  }
  return acc;
}

const bundles = {};
for (const lang of LANGS) {
  bundles[lang] = {};
  for (const f of readdirSync(join(I18N, lang))) {
    if (f.endsWith(".json")) {
      bundles[lang][f.replace(/\.json$/, "")] = JSON.parse(readFileSync(join(I18N, lang, f), "utf8"));
    }
  }
}

function hasExact(res, key) {
  if (Object.prototype.hasOwnProperty.call(res, key)) return true;
  let cur = res;
  for (const part of key.split(".")) {
    if (cur && typeof cur === "object" && part in cur) cur = cur[part];
    else return false;
  }
  return typeof cur === "string";
}

function resolves(lang, ns, key) {
  const res = bundles[lang][ns];
  if (!res) return false;
  return PLURAL_SUFFIXES.some((sfx) => hasExact(res, key + sfx));
}

// Callee name, key, plus an optional `{ ns: "..." }` override in the same
// call. P-18 B2: the callee is captured because a file may hold SEVERAL
// `t` aliases with different bindings (`const { t: tCred } =
// useTranslation("staff_credentials")`), and attributing every call to the
// file's FIRST binding reported 28 keys as fallback-dependent that resolve
// in their own primary namespace. See docs/testing/i18n-audit.md.
const TCALL = /\b(t[A-Za-z]*)\(\s*["'`]([a-zA-Z][a-zA-Z0-9_.]*)["'`]([^;\n]{0,160})/g;
const NS_OVERRIDE = /\bns:\s*["'`]([a-z_]+)["'`]/;

/** Blank out comments and import lines so prose examples are not scanned. */
function stripNonCode(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/(^|[^:])\/\/[^\n]*/g, (m, p1) => p1 + " ".repeat(Math.max(0, m.length - p1.length)));
}
// The destructure AND the namespace argument, so each `t` alias keeps its
// own binding: `const { t } = useTranslation("common")` binds `t`, while
// `const { t: tCred } = useTranslation("staff_credentials")` binds `tCred`.
const BIND =
  /\{([^}]*)\}\s*=\s*useTranslation\(\s*(\[[^\]]*\]|["'`][a-z_]+["'`])?\s*\)/g;
const ALIAS = /\bt\s*:\s*([A-Za-z_$][\w$]*)|\bt\b(?!\s*:)/;

/** alias -> the namespace lists it was bound to (usually exactly one). */
function aliasBindings(src) {
  const map = new Map();
  for (const m of src.matchAll(BIND)) {
    const a = ALIAS.exec(m[1] || "");
    if (!a) continue;
    const alias = a[1] || "t";
    const ns = m[2]
      ? [...m[2].matchAll(/["'`]([a-z_]+)["'`]/g)].map((x) => x[1])
      : ["common"];
    if (!ns.length) continue;
    if (!map.has(alias)) map.set(alias, []);
    const seen = map.get(alias);
    if (!seen.some((prev) => prev.join("|") === ns.join("|"))) seen.push(ns);
  }
  return map;
}

let checked = 0;
const missing = [];
const nsFallback = [];

for (const file of walk(SRC)) {
  const raw = readFileSync(file, "utf8");
  const src = stripNonCode(raw);
  const rel = relative(SRC, file);

  const aliases = aliasBindings(src);
  const allBinds = [...aliases.values()].flat();
  // A helper module that takes `t` as a PARAMETER (describeTicketChange.ts
  // is the one that put `change.moved_to` on the owner's screen) has no
  // binding of its own. We cannot know its caller's namespaces, so check
  // such keys against every namespace and only report a key that exists
  // nowhere at all.
  const injected = !allBinds.length;
  const fileNamespaces = injected
    ? Object.keys(bundles[LANGS[0]])
    : [...new Set(allBinds.flat())];
  if (!fileNamespaces.length) continue;
  if (injected && !TCALL.test(src)) continue;
  TCALL.lastIndex = 0;

  for (const m of src.matchAll(TCALL)) {
    const callee = m[1];
    const key = m[2];
    if (!key.includes(".") || /^[A-Z]/.test(key)) continue;
    const override = NS_OVERRIDE.exec(m[3] || "");
    // P-18 B2 — attribute the call to ITS OWN alias. An alias bound in more
    // than one place in the file (different components, different
    // namespaces) is checked against the union and never reported as a
    // fallback, because we cannot say which binding is in scope here.
    const bound = aliases.get(callee) || null;
    const ambiguous = !bound || bound.length !== 1;
    const scope = override
      ? [override[1]]
      : bound
        ? [...new Set(bound.flat())]
        : fileNamespaces;
    const first = override ? override[1] : ambiguous ? null : bound[0][0];
    checked += 1;
    const line = src.slice(0, m.index).split("\n").length;

    for (const lang of LANGS) {
      if (!scope.some((ns) => resolves(lang, ns, key))) {
        missing.push({ file: rel, line, key, lang, namespaces: scope });
      } else if (first && scope.length > 1 && !resolves(lang, first, key)) {
        nsFallback.push({ file: rel, line, key, lang, primary: first });
      }
    }
  }
}

console.log(`i18n audit: ${checked} t() key references checked in ${LANGS.join(" + ")}`);
console.log(`NS-FALLBACK (absent from first namespace, needs nsMode:"fallback"): ${nsFallback.length}`);
console.log(`MISSING (absent from every bound namespace): ${missing.length}`);
if (process.argv.includes("--list-fallback")) {
  const uniq = [...new Set(nsFallback.map((p) => `${p.key}  <- ${p.file}:${p.line} (first ns=${p.primary})`))];
  console.log(`\nkeys that depend on nsMode:"fallback" (${uniq.length} unique):`);
  for (const u of uniq.sort()) console.log(`  ${u}`);
}
for (const p of missing) {
  console.log(`  ${p.file}:${p.line}  [${p.lang}]  ${p.key}  (ns=${p.namespaces.join("+")})`);
}
process.exit(missing.length === 0 ? 0 : 1);
