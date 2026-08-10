import fs from 'node:fs';
import { Game, Player, exportToGnuPositionId } from '@nodots/backgammon-core';
import { initializeGnubgHints, shutdownGnubgHints, configureGnubgHints, getMoveHints, buildHintContextFromGame, executeRobotTurnWithGNU, DEFAULT_HINTS_CONFIG } from '@nodots/backgammon-ai';

const shard = Number(process.env.GNU_SHARD_INDEX || '0');
const games = Number(process.env.GNU_BATCH_GAMES || '24');
const offset = Number(process.env.GNU_GAME_OFFSET || String(shard * games));
const turns = Number(process.env.GNU_TURNS_PER_GAME || '12');
const maxHints = Number(process.env.GNU_MAX_HINTS || '5');
const seedBase = Number(process.env.GNU_SEED_BASE || '41007019');
const hardMargin = Number(process.env.GNU_HARD_MARGIN || '0.02');
const out = `gnu-teacher-all-dice-v4-${shard}.jsonl`;
const report = `gnu-teacher-all-dice-v4-${shard}-report.txt`;

const diceSet=[]; for(let a=1;a<=6;a++) for(let b=a;b<=6;b++) diceSet.push([a,b]);
function seedRandom(seed){let t=seed>>>0;Math.random=()=>{t+=0x6d2b79f5;let r=Math.imul(t^(t>>>15),1|t);r^=r+Math.imul(r^(r>>>7),61|r);return((r^(r>>>14))>>>0)/4294967296;};}
function splitForGame(g){const b=g%10;return b<=1?'dev':b<=3?'tune':'train';}
function countColor(c,color){return(c?.checkers||[]).filter(x=>x.color===color).length;}
function encodeBoard(game){const color=game.activePlayer.color,opponent=color==='white'?'black':'white',direction=game.activePlayer.direction,od=direction==='clockwise'?'counterclockwise':'clockwise';const own=Array(24).fill(0),opp=Array(24).fill(0);for(const p of game.board.points){const pos=p.position[direction];own[pos-1]=countColor(p,color);opp[pos-1]=countColor(p,opponent);}return{own,opp,barOwn:countColor(game.board.bar[direction],color),barOpp:countColor(game.board.bar[od],opponent),offOwn:countColor(game.board.off[direction],color),offOpp:countColor(game.board.off[od],opponent),activeColor:color,activeDirection:direction};}
function players(){return[Player.initialize('white','clockwise','rolling-for-start',true),Player.initialize('black','counterclockwise','rolling-for-start',true)];}

await initializeGnubgHints({config:DEFAULT_HINTS_CONFIG}); await configureGnubgHints(DEFAULT_HINTS_CONFIG);
const rows=[]; let failures=0,naturalEnds=0,baseStates=0;
try{
 for(let lg=0;lg<games;lg++){
  const gameIndex=offset+lg, seed=seedBase+gameIndex*1009; seedRandom(seed);
  let state=Game.rollForStart(Game.initialize(players())); const split=splitForGame(gameIndex);
  for(let turn=0;turn<turns;turn++){
   try{
    const rolled=Game.roll(state); if(!rolled||rolled.stateKind!=='moving'){naturalEnds++;break;}
    baseStates++; const board=encodeBoard(rolled); let positionId=null; try{positionId=exportToGnuPositionId(rolled);}catch{}
    const {request}=buildHintContextFromGame(rolled);
    for(const dice of diceSet){
      request.dice=[dice[0],dice[1]];
      const hints=await getMoveHints(request,maxHints); if(!Array.isArray(hints)||!hints.length) throw new Error(`NO_HINTS dice=${dice.join('')}`);
      const margin=hints.length>1?Number((hints[0].equity??0)-(hints[1].equity??0)):null;
      rows.push({teacher:'GNU Backgammon board-based all-dice',pristine:false,shard,seed,gameIndex,turn,split,positionId,dice,board,maxHints,teacherMargin:margin,hard:margin!==null&&margin<hardMargin,hints});
    }
    state=await executeRobotTurnWithGNU(rolled,null);
   }catch(err){const msg=String(err?.stack||err);if(/finished|game over|winner|won the game/i.test(msg))naturalEnds++;else{failures++;console.error(`game=${gameIndex} turn=${turn}`,msg);}break;}
  }
 }
}finally{await shutdownGnubgHints();}
fs.writeFileSync(out,rows.map(r=>JSON.stringify(r)).join('\n')+'\n');
const c=s=>rows.filter(r=>r.split===s).length,h=s=>rows.filter(r=>r.split===s&&r.hard).length;
fs.writeFileSync(report,[`SHARD: ${shard}`,`BASE_STATES: ${baseStates}`,`DICE_PER_BASE_STATE: 21`,`SAMPLES_COMPLETED: ${rows.length}`,`TRAIN_SAMPLES: ${c('train')}`,`TUNE_SAMPLES: ${c('tune')}`,`DEV_SAMPLES: ${c('dev')}`,`TRAIN_HARD: ${h('train')}`,`TUNE_HARD: ${h('tune')}`,`DEV_HARD: ${h('dev')}`,`NATURAL_ENDS: ${naturalEnds}`,`ENGINE_FAILURES: ${failures}`,'BOARD_BASED_HINTS: True','DICE_AUGMENTATION: ALL_21','SPLIT_UNIT: WHOLE_GAME','PRISTINE_DATA_USED: False'].join('\n')+'\n');
if(rows.length<baseStates*20) throw new Error(`incomplete all-dice rows ${rows.length}/${baseStates*21}`); if(failures>2) throw new Error(`too many failures ${failures}`);
console.log(`v4 shard ${shard}: ${baseStates} boards -> ${rows.length} GNU labels`);
