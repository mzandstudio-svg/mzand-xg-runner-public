import fs from 'node:fs';

const sourcePath = new URL('./generate-xg-quarantine-diverse-v24.mjs', import.meta.url);
let source = fs.readFileSync(sourcePath, 'utf8');

const replacements = [
  [
    "const desired={contact:48,bar:24,race_like:24,bearoff_like:24,backgame_like:8};",
    "const desired={contact:8,bar:8,race_like:12,bearoff_like:12,backgame_like:24};",
  ],
  [
    "const screenCaps={contact:80,bar:48,race_like:48,bearoff_like:48,backgame_like:32};",
    "const screenCaps={contact:16,bar:16,race_like:24,bearoff_like:24,backgame_like:48};",
  ],
  [
    "if(anchors>=2&&deep>=2) return 'backgame_like';",
    "if(anchors>=2||deep>=2) return 'backgame_like';",
  ],
];

for (const [before, after] of replacements) {
  if (!source.includes(before)) throw new Error(`v25 source patch anchor missing: ${before}`);
  source = source.replace(before, after);
}

source = source.replaceAll('v24', 'v25').replaceAll('V24', 'V25');

if (!source.includes("backgame_like:24")) throw new Error('v25 backgame quota patch missing');
if (!source.includes("anchors>=2||deep>=2")) throw new Error('v25 backgame classifier patch missing');

const encoded = Buffer.from(source, 'utf8').toString('base64');
await import(`data:text/javascript;base64,${encoded}`);
