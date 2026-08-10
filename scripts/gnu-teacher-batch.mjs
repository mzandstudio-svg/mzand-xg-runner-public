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

const games = Number(process.env.GNU_BATCH_GAMES || '12');
const turnsPerGame = Number(process.env.GNU_TURNS_PER_GAME || '10');
const maxHints = Number(process.env.GNU_MAX_HINTS || '5');
const seedBase = Number(process.env.GNU_SEED_BASE || '731991');
const outPath = process.env.GNU_BATCH_OUT || 'gnu-teacher-batch.jsonl';

function seedRandom(seed) {
  let t = seed >>> 0;
  Math.random = () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
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
let failures = 0;
try {
  for (let gameIndex = 0; gameIndex < games; gameIndex++) {
    seedRandom(seedBase + gameIndex * 1009);
    let state = Game.rollForStart(Game.initialize(makePlayers()));
    const split = gameIndex % 4 === 0 ? 'dev' : 'train';
    for (let turn = 0; turn < turnsPerGame; turn++) {
      let rolled;
      try {
        rolled = Game.roll(state);
        if (!rolled || rolled.stateKind !== 'moving') {
          failures++;
          break;
        }
        const dice = [...rolled.activePlayer.dice.currentRoll];
        const { request } = buildHintContextFromGame(rolled);
        request.dice = [dice[0], dice[1]];
        const hints = await getMoveHints(request, maxHints);
        if (!Array.isArray(hints) || hints.length === 0) {
          failures++;
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
          gameIndex,
          turn,
          split,
          positionId,
          dice,
          board: encodeBoard(rolled),
          maxHints,
          teacherMargin: margin,
          hard: margin !== null && margin < 0.02,
          hints,
        });
        state = await executeRobotTurnWithGNU(rolled, null);
      } catch (err) {
        failures++;
        console.error(`game=${gameIndex} turn=${turn} failed`, err);
        break;
      }
    }
  }
} finally {
  await shutdownGnubgHints();
}

fs.writeFileSync(outPath, rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
const trainCount = rows.filter((r) => r.split === 'train').length;
const devCount = rows.filter((r) => r.split === 'dev').length;
const hardCount = rows.filter((r) => r.hard).length;
fs.writeFileSync('gnu-teacher-batch-report.txt', [
  `GAMES_REQUESTED: ${games}`,
  `TURNS_PER_GAME: ${turnsPerGame}`,
  `SAMPLES_COMPLETED: ${rows.length}`,
  `TRAIN_SAMPLES: ${trainCount}`,
  `DEV_SAMPLES: ${devCount}`,
  `HARD_SAMPLES_MARGIN_LT_0.02: ${hardCount}`,
  `FAILURES: ${failures}`,
  `MAX_HINTS: ${maxHints}`,
  'BOARD_BASED_HINTS: True',
  'PRISTINE_DATA_USED: False',
].join('\n') + '\n');

if (rows.length < Math.floor(games * turnsPerGame * 0.8)) {
  throw new Error(`Too few GNU samples: ${rows.length}`);
}
console.log(`GNU batch produced ${rows.length} samples (${trainCount} train / ${devCount} dev)`);
