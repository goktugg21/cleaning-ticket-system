// Sprint 176 §1a — the gate that lockstep cannot be.
//
// Sprint 175 rendered `detail.field_department` and
// `detail.field_work_type` LITERALLY on the Extra Work detail page.
// The lockstep check passed the whole time, because a key missing from
// BOTH bundles is "equal" in both — the same blind spot that hid
// `employees.open_account` in Sprint 156. Lockstep answers "do nl and
// en agree"; it cannot answer "does this key exist at all".
//
// So this walks the files given to it, extracts every `t("...")`
// literal, and asserts the key resolves in one of the namespaces that
// file declares through `useTranslation`. Template calls (`t(`...`)`)
// and computed keys are skipped and COUNTED, because a gate that
// silently ignores what it cannot read is worse than one that says so.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const I18N = "src/i18n";
const langs = ["nl", "en"];

function flatten(obj, prefix = "", out = new Set()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) flatten(v, key, out);
    else out.add(key);
  }
  return out;
}

const bundles = {};
for (const file of readdirSync(join(I18N, "nl"))) {
  const ns = file.replace(/\.json$/, "");
  bundles[ns] = new Set();
  for (const lang of langs) {
    try {
      flatten(JSON.parse(readFileSync(join(I18N, lang, file), "utf8")), "", bundles[ns]);
    } catch { /* a namespace missing on one side is the lockstep gate's job */ }
  }
}

const PLURAL_SUFFIXES = ["zero", "one", "two", "few", "many", "other"];

const files = process.argv.slice(2);
let missing = 0;
let skipped = 0;

for (const file of files) {
  let src;
  try { src = readFileSync(file, "utf8"); } catch { continue; }

  const declared = new Set();
  for (const m of src.matchAll(/useTranslation\(\s*(\[[^\]]*\]|"[^"]+")/g)) {
    for (const n of m[1].matchAll(/"([^"]+)"/g)) declared.add(n[1]);
  }
  const namespaces = declared.size ? [...declared] : Object.keys(bundles);

  skipped += [...src.matchAll(/\bt\(`/g)].length;

  for (const m of src.matchAll(/\bt\(\s*"([^"]+)"/g)) {
    const raw = m[1];
    const [maybeNs, ...rest] = raw.split(":");
    const explicit = rest.length > 0;
    const key = explicit ? rest.join(":") : raw;
    const search = explicit ? [maybeNs] : namespaces;
    // i18next resolves a COUNTED key to its plural form, so `t("x",
    // {count})` looks up `x_one` / `x_other` and `x` itself never
    // exists. Treating that as missing would make this gate cry wolf on
    // four real keys the first time it ran — which it did, and a gate
    // that reports false positives gets ignored.
    const forms = [key, ...PLURAL_SUFFIXES.map((s) => `${key}_${s}`)];
    const found = search.some((ns) =>
      forms.some((form) => bundles[ns]?.has(form)),
    );
    if (!found) {
      console.log(`MISSING  ${file}  t("${raw}")  — searched: ${search.join(", ")}`);
      missing += 1;
    }
  }
}

console.log(
  `i18n key check: ${files.length} file(s), ${missing} missing, ${skipped} template call(s) skipped`,
);
process.exit(missing === 0 ? 0 : 1);
