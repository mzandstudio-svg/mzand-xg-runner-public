import fs from 'node:fs';
import { Game, Player, exportToGnuPositionId } from '@nodots/backgammon-core';
import { initializeGnubgHints, shutdownGnubgHints, configureGnubgHints, getMoveHints, buildHintContextFromGame, executeRobotTurnWithGNU, DEFAULT_HINTS_CONFIG } from '@nodots/backgammon-ai';

const shard = Number(process.env.GNU_SHARD_INDEX || '0');
const games = Number(process.env.GNU_BATCH_GAMES || '96');
const offset = Number(process.env.GNU_GAME_OFFSET || String(shard * games));
const turnsPerGame = Number(process.env.GNU_TURNS_PER_GAME || '14');
const maxHints = Number(process.env.GNU_MAX_HINTS || '5');
const seedBase = Number(process.env.GNU_SEED_BASE || '17001931');
const hardMargin = Number(process.env.GNU_HARD_MARGIN || '0.02');
const outPath = process.env.GNU_BATCH_OUT || `gnu-teacher-batch-v3-${shard}.jsonl`;
const reportPath = `gnu-teacher-batch-v3-${shard}-report.txt`;

function seedRandom(seed) {
  let t = seed >>> 0;
  Math.random = () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}
function splitForGame(g) { const b = g % 10; return b <= 1 ? 'dev' : b <= 3 ? 'tune' : 'train'; }
function countColor(c, color) { return (c?.checkers || []).filter(x => x.color === color).length; }
function encodeBoard(game) {
  const color = game.activePlayer.color;
  const opponent = color === 'white' ? 'black' : 'white';
  const direction = game.activePlayer.direction;
  const oppositeDirection = direction === 'clockwise' ? 'counterclockwise' : 'clockwise';
  const own = Array(24).fill(0), opp = Array(24).fill(0);
  for (const point of game.board.points) {
    const pos = point.position[direction];
    own[pos - 1] = countColor(point, color);
    opp[pos - 1] = countColor(point, opponent);
  }
  return { own, opp, barOwn: countColor(game.board.bar[direction], color), barOpp: countColor(game.board.bar[oppositeDirection], opponent), offOwn: countColor(game.board.off[direction], color), offOpp: countColor(game.board.off[oppositeDirection], opponent), activeColor: color, activeDirection: direction };
}
function makePlayers() {
  return [Player.initialize('white','clockwise','rolling-for-start',true), Player.initialize('black','counterclockwise','rolling-for-start',true)];
}

await initializeGnubgHints({ config: DEFAULT_HINTS_CONFIG });
await configureGnubgHints(DEFAULT_HINTS_CONFIG);
const rows = [];
let engineFailures = 0, noHints = 0, naturalEnds = 0;
const diagnostics = [];
try {
  for (let localGame = 0; localGame < games; localGame++) {
    const gameIndex = offset + localGame;
    const seed = seedBase + gameIndex * 1009;
    seedRandom(seed);
    let state = Game.rollForStart(Game.initialize(makePlayers()));
    const split = splitForGame(gameIndex);
    for (let turn = 0; turn < turnsPerGame; turn++) {
      try {
        const rolled = Game.roll(state);
        if (!rolled || rolled.stateKind !== 'moving') { naturalEnds++; break; }
        const dice = [...rolled.activePlayer.dice.currentRoll];
        const { request } = buildHintContextFromGame(rolled);
        request.dice = [dice[0], dice[1]];
        const hints = await getMoveHints(request, maxHints);
        if (!Array.isArray(hints) || hints.length === 0) { noHints++; diagnostics.push(`NO_HINTS game=${gameIndex} turn=${turn}`); break; }
        let positionId = null; try { positionId = exportToGnuPositionId(rolled); } catch {}
        const margin = hints.length > 1 ? Number((hints[0].equity ?? 0) - (hints[1].equity ?? 0)) : null;
        rows.push({ teacher:'GNU Backgammon board-based via @nodots/gnubg-hints', pristine:false, shard, seed, gameIndex, turn, split, positionId, dice, board:encodeBoard(rolled), maxHints, teacherMargin:margin, hard:margin !== null && margin < hardMargin, hints });
        state = await executeRobotTurnWithGNU(rolled, null);
      } catch (err) {
        const msg = String(err?.stack || err);
        if (/finished|game over|winner|won the game/i.test(msg)) naturalEnds++;
        else { engineFailures++; diagnostics.push(`ENGINE_FAILURE game=${gameIndex} turn=${turn}: ${msg.replace(/\s+/g,' ').slice(0,500)}`); }
        break;
      }
    }
  }
} finally { await shutdownGnubgHints(); }

fs.writeFileSync(outPath, rows.map(r => JSON.stringify(r)).join('\n') + '\n');
const count = s => rows.filter(r => r.split === s).length;
const hard = s => rows.filter(r => r.split === s && r.hard).length;
fs.writeFileSync(reportPath, [
  `SHARD: ${shard}`, `GAME_OFFSET: ${offset}`, `GAMES_REQUESTED: ${games}`, `SAMPLES_COMPLETED: ${rows.length}`,
  `TRAIN_SAMPLES: ${count('train')}`, `TUNE_SAMPLES: ${count('tune')}`, `DEV_SAMPLES: ${count('dev')}`,
  `TRAIN_HARD_SAMPLES: ${hard('train')}`, `TUNE_HARD_SAMPLES: ${hard('tune')}`, `DEV_HARD_SAMPLES: ${hard('dev')}`,
  `NATURAL_GAME_ENDS: ${naturalEnds}`, `NO_HINTS: ${noHints}`, `ENGINE_FAILURES: ${engineFailures}`, `MAX_HINTS: ${maxHints}`,
  'BOARD_BASED_HINTS: True', 'SPLIT_UNIT: WHOLE_GAME', 'PRISTINE_DATA_USED: False', ...diagnostics.slice(0,10).map(x => `DIAGNOSTIC: ${x}`)
].join('\n') + '\n');
if (rows.length < Math.floor(games * turnsPerGame * 0.72)) throw new Error(`Too few samples shard=${shard}: ${rows.length}`);
if (engineFailures > Math.max(2, Math.floor(games * 0.03))) throw new Error(`Too many GNU failures shard=${shard}: ${engineFailures}`);
console.log(`GNU v3 shard ${shard} produced ${rows.length} samples`);
