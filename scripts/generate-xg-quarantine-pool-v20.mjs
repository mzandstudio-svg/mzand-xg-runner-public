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

const target = Number(process.env.XGQ_TARGET || '4');
const games = Number(process.env.XGQ_GAMES || '3');
const turns = Number(process.env.XGQ_TURNS || '8');
const seedBase = Number(process.env.XGQ_SEED_BASE || '930260811');
const maxHints = Number(process.env.XGQ_MAX_HINTS || '8');

const teacherConfig = {
  ...DEFAULT_HINTS_CONFIG,
  evalPlies: 3,
  moveFilter: 4,
  usePruning: true,
  noise: 0,
};

const diceSet = [];
for (let a = 1; a <= 6; a += 1) {
  for (let b = a; b <= 6; b += 1) diceSet.push([a, b]);
}

function seedRandom(seed) {
  let t = seed >>> 0;
  Math.random = () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function players() {
  return [
    Player.initialize('white', 'clockwise', 'rolling-for-start', true),
    Player.initialize('black', 'counterclockwise', 'rolling-for-start', true),
  ];
}

function countColor(container, color) {
  return (container?.checkers || []).filter((x) => x.color === color).length;
}

function encodeBoard(game) {
  const color = game.activePlayer.color;
  const opponent = color === 'white' ? 'black' : 'white';
  const direction = game.activePlayer.direction;
  const opponentDirection = direction === 'clockwise' ? 'counterclockwise' : 'clockwise';
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
    barOpp: countColor(game.board.bar[opponentDirection], opponent),
    offOwn: countColor(game.board.off[direction], color),
    offOpp: countColor(game.board.off[opponentDirection], opponent),
    activeColor: color,
    activeDirection: direction,
  };
}

function checkerChar(count, bottom) {
  if (!count) return '-';
  if (count < 0 || count > 15) throw new Error(`invalid checker count ${count}`);
  const base = bottom ? 'A'.charCodeAt(0) : 'a'.charCodeAt(0);
  return String.fromCharCode(base + count - 1);
}

function validateBoard(board) {
  const ownTotal = board.own.reduce((a, b) => a + b, 0) + board.barOwn + board.offOwn;
  const oppTotal = board.opp.reduce((a, b) => a + b, 0) + board.barOpp + board.offOpp;
  if (ownTotal !== 15 || oppTotal !== 15) {
    throw new Error(`checker conservation failed own=${ownTotal} opp=${oppTotal}`);
  }
  for (let i = 0; i < 24; i += 1) {
    if (board.own[i] > 0 && board.opp[i] > 0) throw new Error(`mixed point ${i + 1}`);
  }
}

function toXgid(board, dice) {
  validateBoard(board);
  let position = checkerChar(board.barOpp, false);
  for (let i = 0; i < 24; i += 1) {
    if (board.own[i] > 0) position += checkerChar(board.own[i], true);
    else if (board.opp[i] > 0) position += checkerChar(board.opp[i], false);
    else position += '-';
  }
  position += checkerChar(board.barOwn, true);
  if (position.length !== 26) throw new Error(`bad XG position length ${position.length}`);

  // Money game, centered cube, bottom player on roll, no Jacoby/beaver.
  return `XGID=${position}:0:0:1:${dice[0]}${dice[1]}:0:0:0:0:10`;
}

await initializeGnubgHints({ config: teacherConfig });
await configureGnubgHints(teacherConfig);

const pool = [];
const seen = new Set();
let baseStates = 0;
let evaluatedDice = 0;
let failures = 0;

try {
  for (let localGame = 0; localGame < games && pool.length < target; localGame += 1) {
    const seed = seedBase + localGame * 1009;
    seedRandom(seed);
    let state = Game.rollForStart(Game.initialize(players()));

    for (let turn = 0; turn < turns && pool.length < target; turn += 1) {
      try {
        const rolled = Game.roll(state);
        if (!rolled || rolled.stateKind !== 'moving') break;
        baseStates += 1;

        // Skip the very first move so the quarantine pool is not just opening-book material.
        if (turn > 0) {
          const board = encodeBoard(rolled);
          let positionId = null;
          try { positionId = exportToGnuPositionId(rolled); } catch {}
          const { request } = buildHintContextFromGame(rolled);
          const screened = [];

          for (const dice of diceSet) {
            request.dice = [dice[0], dice[1]];
            const hints = await getMoveHints(request, maxHints);
            evaluatedDice += 1;
            if (!Array.isArray(hints) || hints.length < 2) continue;
            const e0 = Number(hints[0]?.equity ?? hints[0]?.evaluation?.equity ?? 0);
            const e1 = Number(hints[1]?.equity ?? hints[1]?.evaluation?.equity ?? 0);
            const margin = e0 - e1;
            screened.push({ dice, margin, top1: e0, top2: e1 });
          }

          screened.sort((a, b) => a.margin - b.margin);
          const pick = screened[0];
          if (pick) {
            const xgid = toXgid(board, pick.dice);
            if (!seen.has(xgid)) {
              seen.add(xgid);
              pool.push({
                id: `q${String(pool.length + 1).padStart(4, '0')}`,
                schema: 'mzand.xg.quarantine-position.v1',
                split: 'xg_quarantine',
                quarantined: true,
                trainingEligible: false,
                pristine: false,
                sealedDev: false,
                source: 'deterministic GNU self-play position; GNU used only to screen dice for low margin',
                seedRange: 'XGQ_930260811_PLUS',
                seed,
                gameIndex: localGame,
                turn,
                positionId,
                board,
                dice: pick.dice,
                gnuScreening: {
                  evalPlies: 3,
                  moveFilter: 'Huge',
                  pruning: true,
                  top1Equity: pick.top1,
                  top2Equity: pick.top2,
                  margin: pick.margin,
                },
                xgid,
              });
            }
          }
        }

        state = await executeRobotTurnWithGNU(rolled, null);
      } catch (err) {
        failures += 1;
        console.error(`game=${localGame} turn=${turn}`, String(err?.stack || err));
        break;
      }
    }
  }
} finally {
  await shutdownGnubgHints();
}

if (pool.length < target) throw new Error(`only generated ${pool.length}/${target} quarantine positions`);

fs.writeFileSync('xg-quarantine-v20-pool.json', JSON.stringify({
  schema: 'mzand.xg.quarantine-pool.v1',
  target,
  generated: pool.length,
  baseStates,
  evaluatedDice,
  failures,
  pristineDataUsed: false,
  sealedDevUsed: false,
  xgLabelsUsedForTraining: false,
  positions: pool,
}, null, 2) + '\n');

const matrix = {
  include: pool.map((p) => ({
    id: p.id,
    xgid: p.xgid,
    gnu_margin: Number(p.gnuScreening.margin.toFixed(6)),
    seed: p.seed,
    game: p.gameIndex,
    turn: p.turn,
  })),
};
fs.writeFileSync('xg-quarantine-v20-matrix.json', JSON.stringify(matrix));
fs.writeFileSync('xg-quarantine-v20-report.txt', [
  'POOL: XG_QUARANTINE_V20',
  `POSITIONS: ${pool.length}`,
  `BASE_STATES: ${baseStates}`,
  `GNU_SCREENED_DICE: ${evaluatedDice}`,
  `GENERATOR_FAILURES: ${failures}`,
  `SEED_BASE: ${seedBase}`,
  'SPLIT: xg_quarantine',
  'QUARANTINED: True',
  'TRAINING_ELIGIBLE: False',
  'SEALED_DEV_USED: False',
  'PRISTINE_DATA_USED: False',
  'XG_LABELS_USED_FOR_TRAINING: False',
].join('\n') + '\n');

console.log(fs.readFileSync('xg-quarantine-v20-report.txt', 'utf8'));
console.log(JSON.stringify(matrix));
