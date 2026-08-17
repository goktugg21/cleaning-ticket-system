// Sprint 181 §7/§9 — the undefined-CSS-class sweep, as a SCRIPT.
//
// Why this file exists at all. Until now the sweep was something run by
// hand during review, which means it had no coverage guarantee and no
// record of what it looked at. `active-filter-chip` and
// `active-filter-clear` were introduced by Sprint 180 Batch 2
// (060a3ad) and defined in no CSS file; Sprint 180 Batch 5 (adf9e4e)
// ran a sweep in the SAME round and fixed ten other dead class names
// without catching these two.
//
// That is not carelessness, it is arithmetic: five agents worked five
// branches cut from one base, and Batch 5 swept the tree IT could see.
// Batch 2's chips did not exist on that branch. A check that runs
// per-branch before integration cannot see what another branch added in
// the same round — so the check has to live in the repo and run on the
// integrated tree, which is what this is.
//
// The symptom is worth stating because it is not cosmetic: an undefined
// class does not render "unstyled but fine". The Dashboard chip's
// wrapper stayed a plain block and its <span> and <Link> stayed inline,
// so the ticket list read "Finished extra work is hiddenShow all" —
// two sentences welded together with the clear control invisible inside
// them. Same family as `Draft0` and the run-together ticket numbers.
//
// Usage:
//   node scripts/check-css-classes.mjs            # sweep src/
//   node scripts/check-css-classes.mjs a.tsx b.tsx # sweep named files
//
// Exit code 1 when a class name is used and never defined.
//
// What it deliberately does NOT do: template literals and computed
// class names are skipped and COUNTED, exactly like the i18n gate.
// A gate that silently ignores what it cannot read is worse than one
// that says so.
//
// READ THE OUTPUT AS A LIST OF SUSPECTS, NOT A LIST OF BUGS. An
// undefined class only renders WRONG when nothing else supplies the
// layout. Checked while writing this: `.customer-contacts-filter-bar`
// and `.customer-users-filter-bar` are also undefined and both look
// perfect on screen, because each element carries an inline
// `style={{display:"flex", flexWrap:"wrap"}}` and uses the class purely
// as a test hook. The Dashboard chips were the real defect precisely
// because they had NEITHER a rule nor an inline style. This script
// cannot tell those two cases apart — a human has to look — so it
// reports and does not presume.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const SRC = "src";

// Class names that are legitimately defined outside this repo's CSS:
// third-party component classes and the handful of globals the index
// HTML or a library owns. Kept SHORT and explicit — an allowlist that
// grows without argument is how a gate stops finding anything.
const EXTERNAL = new Set([
  // lucide-react injects its own icon class on every <svg>.
  "lucide",
]);

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
    } else if ([".tsx", ".ts"].includes(extname(full))) {
      out.push(full);
    }
  }
  return out;
}

function collectDefinedClasses() {
  const defined = new Set();
  const cssFiles = walk(SRC, []).length >= 0 ? [] : [];
  // Gather every .css under src/ (there is normally one, index.css).
  (function collectCss(dir) {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) collectCss(full);
      else if (extname(full) === ".css") cssFiles.push(full);
    }
  })(SRC);

  for (const file of cssFiles) {
    const css = readFileSync(file, "utf8")
      // Strip comments so a class named only inside a /* ... */ note is
      // not counted as defined — the exact inverse of the i18n gate's
      // "comments are not calls" rule.
      .replace(/\/\*[\s\S]*?\*\//g, " ");
    for (const match of css.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) {
      defined.add(match[1]);
    }
  }
  return { defined, cssFiles };
}

const { defined, cssFiles } = collectDefinedClasses();

const files = process.argv.slice(2);
const targets = files.length ? files : walk(SRC, []);

let missing = 0;
let skipped = 0;
const seen = new Map(); // class -> first "file:line"

for (const file of targets) {
  let raw;
  try {
    raw = readFileSync(file, "utf8");
  } catch {
    continue;
  }
  // Blank comments rather than deleting them, so line numbers survive.
  const src = raw
    .replace(/\/\*[\s\S]*?\*\//g, (b) => b.replace(/[^\n]/g, " "))
    .replace(/^([^\n"'`]*?)\/\/[^\n]*/gm, (line, before) =>
      before + " ".repeat(line.length - before.length),
    );

  // className="a b c" only. A template literal or an expression is
  // counted as skipped, never guessed at.
  for (const match of src.matchAll(/className=(\{`|\{|")([^"`}]*)/g)) {
    const [, opener, body] = match;
    if (opener !== '"') {
      skipped += 1;
      continue;
    }
    const line = src.slice(0, match.index).split("\n").length;
    for (const cls of body.split(/\s+/).filter(Boolean)) {
      if (defined.has(cls) || EXTERNAL.has(cls)) continue;
      if (!seen.has(cls)) seen.set(cls, `${file}:${line}`);
    }
  }
}

for (const [cls, where] of [...seen].sort()) {
  missing += 1;
  console.error(`  undefined CSS class ".${cls}" used at ${where}`);
}

console.log(
  `css class check: ${targets.length} file(s), ${cssFiles.length} stylesheet(s), ` +
    `${missing} undefined, ${skipped} dynamic className(s) skipped`,
);

process.exit(missing > 0 ? 1 : 0);
