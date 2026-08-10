import fs from 'node:fs';
import {
  initializeGnubgHints,
  shutdownGnubgHints,
  gnubgHints,
  DEFAULT_HINTS_CONFIG,
} from '@nodots/backgammon-ai';

const outPath = process.env.GNU_TEACHER_OUT || 'gnu-teacher-samples.jsonl';
const positionId = process.env.GNU_POSITION_ID || '4HPwATDgc/ABMA';
const maxHints = Number(process.env.GNU_MAX_HINTS || '5');

const dice = [];
for (let a = 1; a <= 6; a++) {
  for (let b = a; b <= 6; b++) dice.push([a, b]);
}

await initializeGnubgHints({ config: DEFAULT_HINTS_CONFIG });
let completed = 0;
const rows = [];
try {
  for (const roll of dice) {
    const hints = await gnubgHints.getHintsFromPositionId(positionId, roll, maxHints);
    if (!Array.isArray(hints) || hints.length === 0) {
      throw new Error(`GNU returned no hints for ${positionId} dice=${roll.join('')}`);
    }
    rows.push({
      teacher: 'GNU Backgammon via @nodots/gnubg-hints',
      split: 'development-smoke',
      pristine: false,
      positionId,
      dice: roll,
      maxHints,
      hints,
    });
    completed++;
  }
} finally {
  await shutdownGnubgHints();
}

fs.writeFileSync(outPath, rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
fs.writeFileSync('gnu-teacher-report.txt', [
  `POSITION_ID: ${positionId}`,
  `ROLLS_REQUESTED: ${dice.length}`,
  `ROLLS_COMPLETED: ${completed}`,
  `MAX_HINTS: ${maxHints}`,
  `OUTPUT: ${outPath}`,
  'PRISTINE_DATA_USED: False',
].join('\n') + '\n');

console.log(`GNU teacher produced ${completed} labeled development samples`);
