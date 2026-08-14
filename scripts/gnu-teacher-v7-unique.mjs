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

const shard = Number(process.env.GNU_V7_SHARD_INDEX || '0');
const split = String(process.env.GNU_V7_SPLIT || 'train');
const games = Number(process.env.GNU_V7_GAMES || '24');
const maxTurns = Number(process.env.GNU_V7_MAX_TURNS || '72');
const targetPositions = Number(process.env.GNU_V7_POSITIONS_TARGET || '600');
const dicePerPosition = Number(process.env.GNU_V7_DICE_PER_POSITION || '2');
const maxHints = Number(process.env.GNU_V7_MAX_HINTS || '16');
const seedBase = Number(process.env.GNU_V7_SEED_BASE || '940700001');
const gameOffset = Number(process.env.GNU_V7_GAME_OFFSET || String(shard * 1000));
const teacherConfig = {
  ...DEFAULT_HINTS_CONFIG,
  evalPlies: 3,
  moveFilter: 4,
  usePruning: true,
  noise: 0,
};
if (!['train','tune'].includes(split)) throw new Error(`invalid split ${split}`);
if (dicePerPosition < 1 || dicePerPosition > 3) throw new Error('GNU_V7_DICE_PER_POSITION must be 1..3');

const diceSet = [];
for (let a = 1; a <= 6; a += 1) for (let b = a; b <= 6; b += 1) diceSet.push([a,b]);

function seedRandom(seed) {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}
function countColor(container, color) {
  return (container?.checkers || []).filter((x) => x.color === color).length;
}
function encodeBoard(game) {
  const color = game.activePlayer.color;
  const opponent = color === 'white' ? 'black' : 'white';
  const direction = game.activePlayer.direction;
  const opponentDirection = direction === 'clockwise' ? 'counterclockwise' : 'clockwise';
  const own = Array(24).fill(0), opp = Array(24).fill(0);
  for (const point of game.board.points) {
    const pos = point.position[direction];
    own[pos - 1] = countColor(point, color);
    opp[pos - 1] = countColor(point, opponent);
  }
  return {
    own, opp,
    barOwn: countColor(game.board.bar[direction], color),
    barOpp: countColor(game.board.bar[opponentDirection], opponent),
    offOwn: countColor(game.board.off[direction], color),
    offOpp: countColor(game.board.off[opponentDirection], opponent),
    activeColor: color,
    activeDirection: direction,
  };
}
function phaseBucket(b) {
  if (Number(b.barOwn || 0) > 0 || Number(b.barOpp || 0) > 0) return 'bar';
  const ownIdx = b.own.map((v,i)=>v>0?i:-1).filter(i=>i>=0);
  const oppIdx = b.opp.map((v,i)=>v>0?i:-1).filter(i=>i>=0);
  const allOwnHome = b.own.slice(6).reduce((a,x)=>a+x,0) === 0;
  const allOppHome = b.opp.slice(0,18).reduce((a,x)=>a+x,0) === 0;
  if (allOwnHome || allOppHome || Number(b.offOwn||0) >= 8 || Number(b.offOpp||0) >= 8) return 'bearoff';
  const contact = ownIdx.length && oppIdx.length && Math.max(...ownIdx) > Math.min(...oppIdx);
  return contact ? 'contact' : 'race';
}
function players() {
  return [
    Player.initialize('white','clockwise','rolling-for-start',true),
    Player.initialize('black','counterclockwise','rolling-for-start',true),
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
function normalizeDice(d) {
  if (!Array.isArray(d) || d.length !== 2) return null;
  const a=Number(d[0]), b=Number(d[1]);
  if (!(a>=1&&a<=6&&b>=1&&b<=6)) return null;
  return a<=b?[a,b]:[b,a];
}
function diceChoices(actual, seed, turn) {
  const out=[]; const seen=new Set();
  const add=(d)=>{ if(!d)return; const k=d.join('-'); if(!seen.has(k)){seen.add(k);out.push(d);} };
  add(normalizeDice(actual));
  let x=(seed*1103515245 + turn*12345 + shard*2654435761) >>> 0;
  while(out.length<dicePerPosition){ x=(1664525*x+1013904223)>>>0; add(diceSet[x%diceSet.length]); }
  return out;
}
function shouldLabel(phase, rand) {
  const p = phase === 'contact' ? 0.58 : phase === 'race' ? 0.88 : 1.0;
  return rand() < p;
}

const outPath=`gnu-v7-unique-${split}-${shard}.jsonl`;
const reportPath=`gnu-v7-unique-${split}-${shard}-report.txt`;
const rows=[]; const seenPositions=new Set(); const phaseCounts={contact:0,bar:0,race:0,bearoff:0};
let engineFailures=0, naturalEnds=0, visited=0, labeledPositions=0, rankableRows=0;

await initializeGnubgHints({config:teacherConfig});
await configureGnubgHints(teacherConfig);
try {
  outer: for(let g=0; g<games; g+=1){
    const gameIndex=gameOffset+g;
    const seed=seedBase + gameIndex*1009 + shard*7919;
    const rand=seedRandom(seed);
    const savedRandom=Math.random; Math.random=rand;
    let state=Game.rollForStart(Game.initialize(players()));
    try {
      for(let turn=0; turn<maxTurns; turn+=1){
        let rolled;
        try { rolled=Game.roll(state); }
        catch(err){ naturalEnds+=1; break; }
        if(!rolled || rolled.stateKind!=='moving'){ naturalEnds+=1; break; }
        visited+=1;
        const board=encodeBoard(rolled);
        const phase=phaseBucket(board);
        let positionId=null; try{positionId=exportToGnuPositionId(rolled);}catch{}
        if(positionId && !seenPositions.has(positionId) && shouldLabel(phase,rand)){
          const {request}=buildHintContextFromGame(rolled);
          const ds=diceChoices(request?.dice,seed,turn);
          let positionRows=0;
          for(const dice of ds){
            request.dice=[dice[0],dice[1]];
            const rawHints=await getMoveHints(request,maxHints);
            const hints=Array.isArray(rawHints)?rawHints.map(compactHint):[];
            if(hints.length<2) continue;
            const margin=Number(hints[0].equity)-Number(hints[1].equity);
            rows.push({
              schema:'mzand.gnu.teacher.v7.unique',
              teacher:'GNU Backgammon 3-ply Huge/pruning',
              teacherConfig,
              pristine:false,
              xgLabel:false,
              xgLabelUsed:false,
              devUsed:false,
              split,
              shard,
              seed,
              gameIndex,
              turn,
              positionId,
              dice,
              board,
              phase,
              maxHints,
              candidateCoverage:'GNU Huge filter up to maxHints; runtime legal generation remains exhaustive',
              teacherMargin:margin,
              hard:margin<0.03,
              rolloutCandidate:margin<0.012,
              rankable:true,
              hints,
            });
            positionRows+=1; rankableRows+=1;
          }
          if(positionRows>0){ seenPositions.add(positionId); labeledPositions+=1; phaseCounts[phase]+=1; }
        }
        try { state=await executeRobotTurnWithGNU(rolled,null); }
        catch(err){
          const msg=String(err?.stack||err);
          if(/finished|game over|winner|won the game/i.test(msg)) naturalEnds+=1;
          else { engineFailures+=1; console.error(`game=${gameIndex} turn=${turn}`,msg); }
          break;
        }
        if(labeledPositions>=targetPositions) break outer;
      }
    } finally { Math.random=savedRandom; }
  }
} finally { await shutdownGnubgHints(); }

fs.writeFileSync(outPath, rows.map(r=>JSON.stringify(r)).join('\n')+'\n');
const rep=[
  'CORPUS: GNU_V7_UNIQUE_POSITION_SHARD',
  `SPLIT: ${split}`,
  `SHARD: ${shard}`,
  `VISITED_BOARD_STATES: ${visited}`,
  `UNIQUE_POSITIONS_LABELED: ${labeledPositions}`,
  `ROWS: ${rows.length}`,
  `DICE_PER_POSITION_TARGET: ${dicePerPosition}`,
  `PHASE_CONTACT: ${phaseCounts.contact}`,
  `PHASE_BAR: ${phaseCounts.bar}`,
  `PHASE_RACE: ${phaseCounts.race}`,
  `PHASE_BEAROFF: ${phaseCounts.bearoff}`,
  `RANKABLE_ROWS: ${rankableRows}`,
  `NATURAL_ENDS: ${naturalEnds}`,
  `ENGINE_FAILURES: ${engineFailures}`,
  'GNU_EVAL_PLIES: 3',
  'GNU_MOVE_FILTER: HUGE',
  'GNU_PRUNING: True',
  'OUTCOME_TARGETS_RECORDED: True',
  'PRISTINE_DATA_USED: False',
  'XG_LABELS_USED: False',
  'DEV_USED: False',
].join('\n')+'\n';
fs.writeFileSync(reportPath,rep); console.log(rep);
if(labeledPositions < Math.floor(targetPositions*0.70)) throw new Error(`insufficient unique positions ${labeledPositions}/${targetPositions}`);
if(engineFailures>2) throw new Error(`too many engine failures ${engineFailures}`);
