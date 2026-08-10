import fs from 'node:fs';
import {
  Game,
  Player,
  exportToGnuPositionId,
} from '@nodots/backgammon-core';
import {
  initializeGnubgHints,
  shutdownGnubgHints,
  configureGnubgHints,
  getMoveHints,
  buildHintContextFromGame,
  executeRobotTurnWithGNU,
  DEFAULT_HINTS_CONFIG,
} from '@nodots/backgammon-ai';

const games = Number(process.env.GNU_BATCH_GAMES || '96');
const turnsPerGame = Number(process.env.GNU_TURNS_PER_GAME || '14');
const maxHints = Number(process.env.GNU_MAX_HINTS || '5');
const seedBase = Number(process.env.GNU_SEED_BASE || '9284173');
const outPath = process.env.GNU_BATCH_OUT || 'gnu-teacher-batch-v2.jsonl';
const hardMargin = Number(process.env.GNU_HARD_MARGIN || '0.02');

function seedRandom(seed) {
  let t = seed >>> 0;
  Math.random = () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function splitForGame(gameIndex) {
  const bucket = gameIndex % 10;
  if (bucket <= 1) return 'dev';
  if (bucket <= 3) return 'tune';
  return 'train';
}

function countColor(container, color) {
  return (container?.checkers || []).filter((c) => c.color === color).length;
}

function encodeBoard(game) {
  const color = game.activePlayer.color;
  const opponent = color === 'white' ? 'black' : 'white';
  const direction = game.activePlayer.direction;
  const oppositeDirection = direction === 'clockwise' ? 'counterclockwise' : 'clockwise';
  const own = Array(24).fill(0);
  const opp = Array(24).fill(0);
  for (const point of game.board.points) {
    const pos = point.position[direction];
    own[pos - 1] = countColor(point, color);
    opp[pos - 1] = countColor(point, opponent);
  }
  return {
    own,
    opp,
    barOwn: countColor(game.board.bar[direction], color),
    barOpp: countColor(game.board.bar[oppositeDirection], opponent),
    offOwn: countColor(game.board.off[direction], color),
    offOpp: countColor(game.board.off[oppositeDirection], opponent),
    activeColor: color,
    activeDirection: direction,
  };
}

function makePlayers() {
  const white = Player.initialize('white', 'clockwise', 'rolling-for-start', true);
  const black = Player.initialize('black', 'counterclockwise', 'rolling-for-start', true);
  return [white, black];
}

await initializeGnubgHints({ config: DEFAULT_HINTS_CONFIG });
await configureGnubgHints(DEFAULT_HINTS_CONFIG);

const rows = [];
let engineFailures = 0;
let noHints = 0;
let naturalEnds = 0;
const failureMessages = [];
try {
  for (let gameIndex = 0; gameIndex < games; gameIndex++) {
    seedRandom(seedBase + gameIndex * 1009);
    let state = Game.rollForStart(Game.initialize(makePlayers()));
    const split = splitForGame(gameIndex);
    for (let turn = 0; turn < turnsPerGame; turn++) {
      try {
        const rolled = Game.roll(state);
        if (!rolled || rolled.stateKind !== 'moving') {
          naturalEnds++;
          break;
        }
        const dice = [...rolled.activePlayer.dice.currentRoll];
        const { request } = buildHintContextFromGame(rolled);
        request.dice = [dice[0], dice[1]];
        const hints = await getMoveHints(request, maxHints);
        if (!Array.isArray(hints) || hints.length === 0) {
          noHints++;
          failureMessages.push(`NO_HINTS game=${gameIndex} turn=${turn} dice=${dice.join('')}`);
          break;
        }
        let positionId = null;
        try { positionId = exportToGnuPositionId(rolled); } catch {}
        const margin = hints.length > 1
          ? Number((hints[0].equity ?? 0) - (hints[1].equity ?? 0))
          : null;
        rows.push({
          teacher: 'GNU Backgammon board-based via @nodots/gnubg-hints',
          pristine: false,
          seed: seedBase + gameIndex * 1009,
          gameIndex,
          turn,
          split,
          positionId,
          dice,
          board: encodeBoard(rolled),
          maxHints,
          teacherMargin: margin,
          hard: margin !== null && margin < hardMargin,
          hints,
        });
        state = await executeRobotTurnWithGNU(rolled, null);
      } catch (err) {
        const msg = String(err?.stack || err);
        if (/finished|game over|winner|won the game/i.test(msg)) {
          naturalEnds++;
        } else {
          engineFailures++;
          failureMessages.push(`ENGINE_FAILURE game=${gameIndex} turn=${turn}: ${msg.replace(/\s+/g, ' ').slice(0, 500)}`);
        }
        break;
      }
    }
  }
} finally {
  await shutdownGnubgHints();
}

fs.writeFileSync(outPath, rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
const counts = Object.fromEntries(['train', 'tune', 'dev'].map((s) => [s, rows.filter((r) => r.split === s).length]));
const hardCounts = Object.fromEntries(['train', 'tune', 'dev'].map((s) => [s, rows.filter((r) => r.split === s && r.hard).length]));
fs.writeFileSync('gnu-teacher-batch-v2-report.txt', [
  `GAMES_REQUESTED: ${games}`,
  `TURNS_PER_GAME: ${turnsPerGame}`,
  `SAMPLES_COMPLETED: ${rows.length}`,
  `TRAIN_SAMPLES: ${counts.train}`,
  `TUNE_SAMPLES: ${counts.tune}`,
  `DEV_SAMPLES: ${counts.dev}`,
  `TRAIN_HARD_SAMPLES: ${hardCounts.train}`,
  `TUNE_HARD_SAMPLES: ${hardCounts.tune}`,
  `DEV_HARD_SAMPLES: ${hardCounts.dev}`,
  `HARD_MARGIN: ${hardMargin}`,
  `NATURAL_GAME_ENDS: ${naturalEnds}`,
  `NO_HINTS: ${noHints}`,
  `ENGINE_FAILURES: ${engineFailures}`,
  `MAX_HINTS: ${maxHints}`,
  'BOARD_BASED_HINTS: True',
  'SPLIT_UNIT: WHOLE_GAME',
  'DEV_USED_FOR_MODEL_SELECTION: False',
  'PRISTINE_DATA_USED: False',
  ...failureMessages.slice(0, 20).map((x) => `DIAGNOSTIC: ${x}`),
].join('\n') + '\n');

if (counts.train < 400 || counts.tune < 120 || counts.dev < 120) {
  throw new Error(`Insufficient split sizes train=${counts.train} tune=${counts.tune} dev=${counts.dev}`);
}
if (engineFailures > Math.max(2, Math.floor(games * 0.03))) {
  throw new Error(`Too many GNU engine failures: ${engineFailures}`);
}
console.log(`GNU v2 batch produced ${rows.length} samples (${counts.train} train / ${counts.tune} tune / ${counts.dev} dev)`);
