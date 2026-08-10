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

const shard = Number(process.env.GNU_V6_SHARD_INDEX || '0');
const games = Number(process.env.GNU_V6_GAMES || '4');
const offset = Number(process.env.GNU_V6_GAME_OFFSET || String(shard * games));
const turns = Number(process.env.GNU_V6_TURNS || '8');
const maxHints = Number(process.env.GNU_V6_MAX_HINTS || '16');
const seedBase = Number(process.env.GNU_V6_SEED_BASE || '620260810');
const hardMargin = Number(process.env.GNU_V6_HARD_MARGIN || '0.03');
const rolloutMargin = Number(process.env.GNU_V6_ROLLOUT_MARGIN || '0.012');
const teacherConfig = {
  ...DEFAULT_HINTS_CONFIG,
  evalPlies: 3,
  moveFilter: 4, // MoveFilterSetting.Huge
  usePruning: true,
  noise: 0,
};

const out = `gnu-teacher-v6-${shard}.jsonl`;
const report = `gnu-teacher-v6-${shard}-report.txt`;
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

function splitForGame(gameIndex) {
  const bucket = gameIndex % 20;
  if (bucket <= 2) return 'dev';
  if (bucket <= 5) return 'tune';
  return 'train';
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

function players() {
  return [
    Player.initialize('white', 'clockwise', 'rolling-for-start', true),
    Player.initialize('black', 'counterclockwise', 'rolling-for-start', true),
  ];
}

function compactHint(hint) {
  const e = hint?.evaluation || {};
  return {
    moves: hint?.moves || [],
    rank: Number(hint?.rank ?? 999),
    equity: Number(hint?.equity ?? e.equity ?? 0),
    difference: Number(hint?.difference ?? 0),
    evaluation: {
      win: Number(e.win ?? 0),
      winGammon: Number(e.winGammon ?? 0),
      winBackgammon: Number(e.winBackgammon ?? 0),
      loseGammon: Number(e.loseGammon ?? 0),
      loseBackgammon: Number(e.loseBackgammon ?? 0),
      equity: Number(e.equity ?? hint?.equity ?? 0),
      cubefulEquity: e.cubefulEquity == null ? null : Number(e.cubefulEquity),
    },
  };
}

await initializeGnubgHints({ config: teacherConfig });
await configureGnubgHints(teacherConfig);

const rows = [];
let failures = 0;
let naturalEnds = 0;
let baseStates = 0;
let nonRankable = 0;
let hardCount = 0;
let rolloutQueueCount = 0;

try {
  for (let localGame = 0; localGame < games; localGame += 1) {
    const gameIndex = offset + localGame;
    const seed = seedBase + gameIndex * 1009;
    seedRandom(seed);
    let state = Game.rollForStart(Game.initialize(players()));
    const split = splitForGame(gameIndex);

    for (let turn = 0; turn < turns; turn += 1) {
      try {
        const rolled = Game.roll(state);
        if (!rolled || rolled.stateKind !== 'moving') {
          naturalEnds += 1;
          break;
        }
        baseStates += 1;
        const board = encodeBoard(rolled);
        let positionId = null;
        try { positionId = exportToGnuPositionId(rolled); } catch {}
        const { request } = buildHintContextFromGame(rolled);

        for (const dice of diceSet) {
          request.dice = [dice[0], dice[1]];
          const rawHints = await getMoveHints(request, maxHints);
          const hints = Array.isArray(rawHints) ? rawHints.map(compactHint) : [];
          if (!hints.length) {
            nonRankable += 1;
            rows.push({
              schema: 'mzand.gnu.teacher.v6',
              teacher: 'GNU Backgammon 3-ply Huge/pruning',
              teacherConfig,
              pristine: false,
              xgLabel: false,
              shard,
              seed,
              gameIndex,
              turn,
              split,
              positionId,
              dice,
              board,
              maxHints,
              teacherMargin: null,
              hard: false,
              rolloutCandidate: false,
              rankable: false,
              forcedOrPass: true,
              hints: [],
            });
            continue;
          }

          const margin = hints.length > 1 ? hints[0].equity - hints[1].equity : null;
          const hard = margin !== null && margin < hardMargin;
          const rolloutCandidate = margin !== null && margin < rolloutMargin;
          if (hard) hardCount += 1;
          if (rolloutCandidate) rolloutQueueCount += 1;
          rows.push({
            schema: 'mzand.gnu.teacher.v6',
            teacher: 'GNU Backgammon 3-ply Huge/pruning',
            teacherConfig,
            pristine: false,
            xgLabel: false,
            shard,
            seed,
            gameIndex,
            turn,
            split,
            positionId,
            dice,
            board,
            maxHints,
            candidateCoverage: 'GNU Huge filter up to maxHints; not yet exhaustive legal enumeration',
            teacherMargin: margin,
            hard,
            rolloutCandidate,
            rankable: hints.length > 1,
            forcedOrPass: hints.length === 1,
            hints,
          });
        }

        state = await executeRobotTurnWithGNU(rolled, null);
      } catch (err) {
        const msg = String(err?.stack || err);
        if (/finished|game over|winner|won the game/i.test(msg)) naturalEnds += 1;
        else {
          failures += 1;
          console.error(`game=${gameIndex} turn=${turn}`, msg);
        }
        break;
      }
    }
  }
} finally {
  await shutdownGnubgHints();
}

fs.writeFileSync(out, `${rows.map((r) => JSON.stringify(r)).join('\n')}\n`);
const count = (split) => rows.filter((r) => r.split === split).length;
const rankable = (split) => rows.filter((r) => r.split === split && r.rankable).length;
fs.writeFileSync(report, [
  `SHARD: ${shard}`,
  `BASE_STATES: ${baseStates}`,
  'DICE_PER_BASE_STATE: 21',
  `SAMPLES_COMPLETED: ${rows.length}`,
  `TRAIN_SAMPLES: ${count('train')}`,
  `TUNE_SAMPLES: ${count('tune')}`,
  `DEV_SAMPLES: ${count('dev')}`,
  `TRAIN_RANKABLE: ${rankable('train')}`,
  `TUNE_RANKABLE: ${rankable('tune')}`,
  `DEV_RANKABLE: ${rankable('dev')}`,
  `HARD_SAMPLES: ${hardCount}`,
  `ROLLOUT_QUEUE_SAMPLES: ${rolloutQueueCount}`,
  `NON_RANKABLE_FORCED_OR_PASS: ${nonRankable}`,
  `NATURAL_ENDS: ${naturalEnds}`,
  `ENGINE_FAILURES: ${failures}`,
  'GNU_EVAL_PLIES: 3',
  'GNU_MOVE_FILTER: HUGE',
  'GNU_PRUNING: True',
  `GNU_MAX_HINTS: ${maxHints}`,
  'OUTCOME_TARGETS_RECORDED: True',
  'CUBEFUL_TARGET_RECORDED_WHEN_AVAILABLE: True',
  'ROLL_OUT_EXECUTED: False',
  'ROLL_OUT_QUEUE_ONLY: True',
  'PRISTINE_DATA_USED: False',
  'XG_LABELS_USED: False',
  'SPLIT_UNIT: WHOLE_GAME',
].join('\n') + '\n');

if (rows.length !== baseStates * 21) {
  throw new Error(`incomplete all-dice rows ${rows.length}/${baseStates * 21}`);
}
if (failures > 2) throw new Error(`too many failures ${failures}`);
console.log(`v6 shard ${shard}: ${baseStates} boards -> ${rows.length} GNU 3-ply labels; rollout queue=${rolloutQueueCount}`);
