import fs from 'node:fs';
import { Game, Player, exportToGnuPositionId } from '@nodots/backgammon-core';
import {
  initializeGnubgHints, shutdownGnubgHints, configureGnubgHints,
  getMoveHints, buildHintContextFromGame, executeRobotTurnWithGNU,
  DEFAULT_HINTS_CONFIG,
} from '@nodots/backgammon-ai';

const target = Number(process.env.XGQ_TARGET || '128');
const games = Number(process.env.XGQ_GAMES || '64');
const turns = Number(process.env.XGQ_TURNS || '64');
const seedBase = Number(process.env.XGQ_SEED_BASE || '931000019');
const maxHints = Number(process.env.XGQ_MAX_HINTS || '8');
const idOffset = Number(process.env.XGQ_ID_OFFSET || '0');

const teacherConfig = { ...DEFAULT_HINTS_CONFIG, evalPlies: 3, moveFilter: 4, usePruning: true, noise: 0 };
const diceSet=[]; for(let a=1;a<=6;a+=1) for(let b=a;b<=6;b+=1) diceSet.push([a,b]);
const desired={contact:48,bar:24,race_like:24,bearoff_like:24,backgame_like:8};
const screenCaps={contact:80,bar:48,race_like:48,bearoff_like:48,backgame_like:32};

function seedRandom(seed){let t=seed>>>0; Math.random=()=>{t+=0x6d2b79f5;let r=Math.imul(t^(t>>>15),1|t);r^=r+Math.imul(r^(r>>>7),61|r);return((r^(r>>>14))>>>0)/4294967296;};}
function players(){return [Player.initialize('white','clockwise','rolling-for-start',true),Player.initialize('black','counterclockwise','rolling-for-start',true)];}
function countColor(container,color){return (container?.checkers||[]).filter(x=>x.color===color).length;}
function encodeBoard(game){
  const color=game.activePlayer.color, opponent=color==='white'?'black':'white';
  const direction=game.activePlayer.direction, opponentDirection=direction==='clockwise'?'counterclockwise':'clockwise';
  const own=Array(24).fill(0),opp=Array(24).fill(0);
  for(const point of game.board.points){const pos=point.position[direction];own[pos-1]=countColor(point,color);opp[pos-1]=countColor(point,opponent);}
  return {own,opp,barOwn:countColor(game.board.bar[direction],color),barOpp:countColor(game.board.bar[opponentDirection],opponent),offOwn:countColor(game.board.off[direction],color),offOpp:countColor(game.board.off[opponentDirection],opponent),activeColor:color,activeDirection:direction};
}
function phaseOf(b){
  if(Number(b.barOwn)||Number(b.barOpp)) return 'bar';
  if(Number(b.offOwn)||Number(b.offOpp)) return 'bearoff_like';
  const op=[...b.own.entries()].filter(([,n])=>n).map(([i])=>i+1), xp=[...b.opp.entries()].filter(([,n])=>n).map(([i])=>i+1);
  if(op.length&&xp.length&&Math.max(...op)<Math.min(...xp)) return 'race_like';
  const anchors=b.own.reduce((n,x,i)=>n+(i>=18&&x>=2?1:0),0), deep=b.opp.reduce((n,x,i)=>n+(i<=5&&x>=2?1:0),0);
  if(anchors>=2&&deep>=2) return 'backgame_like';
  return 'contact';
}
function checkerChar(count,bottom){if(!count)return '-';if(count<0||count>15)throw new Error(`invalid checker count ${count}`);return String.fromCharCode((bottom?'A':'a').charCodeAt(0)+count-1);}
function validateBoard(b){const ot=b.own.reduce((a,x)=>a+x,0)+b.barOwn+b.offOwn,xt=b.opp.reduce((a,x)=>a+x,0)+b.barOpp+b.offOpp;if(ot!==15||xt!==15)throw new Error(`checker conservation ${ot}/${xt}`);for(let i=0;i<24;i+=1)if(b.own[i]>0&&b.opp[i]>0)throw new Error(`mixed point ${i+1}`);}
function toXgid(b,dice){validateBoard(b);let p=checkerChar(b.barOpp,false);for(let i=0;i<24;i+=1)p+=b.own[i]>0?checkerChar(b.own[i],true):b.opp[i]>0?checkerChar(b.opp[i],false):'-';p+=checkerChar(b.barOwn,true);if(p.length!==26)throw new Error(`bad XG position length ${p.length}`);return `XGID=${p}:0:0:1:${dice[0]}${dice[1]}:0:0:0:0:10`;}

await initializeGnubgHints({config:teacherConfig}); await configureGnubgHints(teacherConfig);
const candidates=[], seen=new Set(); const screenedByPhase={contact:0,bar:0,race_like:0,bearoff_like:0,backgame_like:0};
const visitedByPhase={contact:0,bar:0,race_like:0,bearoff_like:0,backgame_like:0};
let baseStates=0,evaluatedDice=0,failures=0;
try{
  for(let localGame=0;localGame<games;localGame+=1){
    const seed=seedBase+localGame*1009; seedRandom(seed); let state=Game.rollForStart(Game.initialize(players()));
    for(let turn=0;turn<turns;turn+=1){
      try{
        const rolled=Game.roll(state); if(!rolled||rolled.stateKind!=='moving') break; baseStates+=1;
        if(turn>0){
          const board=encodeBoard(rolled), phase=phaseOf(board); visitedByPhase[phase]+=1;
          if(screenedByPhase[phase] < screenCaps[phase]){
            let positionId=null; try{positionId=exportToGnuPositionId(rolled);}catch{}
            const {request}=buildHintContextFromGame(rolled); const screened=[];
            for(const dice of diceSet){request.dice=[dice[0],dice[1]];const hints=await getMoveHints(request,maxHints);evaluatedDice+=1;if(!Array.isArray(hints)||hints.length<2)continue;const e0=Number(hints[0]?.equity??hints[0]?.evaluation?.equity??0),e1=Number(hints[1]?.equity??hints[1]?.evaluation?.equity??0);screened.push({dice,margin:e0-e1,top1:e0,top2:e1});}
            screened.sort((a,b)=>a.margin-b.margin); const pick=screened[0];
            if(pick){const xgid=toXgid(board,pick.dice);if(!seen.has(xgid)){seen.add(xgid);screenedByPhase[phase]+=1;candidates.push({schema:'mzand.xg.quarantine-position.v1',split:'xg_quarantine',quarantined:true,trainingEligible:false,pristine:false,sealedDev:false,source:'deterministic GNU self-play position; GNU used only for phase-aware low-margin dice screening',seedRange:`XGQ_${seedBase}_PLUS`,seed,gameIndex:localGame,turn,positionId,board,dice:pick.dice,phaseBucket:phase,gnuScreening:{evalPlies:3,moveFilter:'Huge',pruning:true,screenOnly:true,top1Equity:pick.top1,top2Equity:pick.top2,margin:pick.margin},xgid});}}
          }
        }
        state=await executeRobotTurnWithGNU(rolled,null);
      }catch(err){failures+=1;console.error(`game=${localGame} turn=${turn}`,String(err?.stack||err));break;}
    }
    const rareReady=['race_like','bearoff_like','backgame_like'].every(p=>screenedByPhase[p]>=desired[p]);
    const commonReady=screenedByPhase.contact>=desired.contact&&screenedByPhase.bar>=desired.bar;
    if(rareReady&&commonReady&&candidates.length>=target) break;
  }
}finally{await shutdownGnubgHints();}

const selected=[], selectedX=new Set();
for(const phase of ['bearoff_like','race_like','backgame_like','bar','contact']){
  const xs=candidates.filter(x=>x.phaseBucket===phase).sort((a,b)=>a.gnuScreening.margin-b.gnuScreening.margin);
  for(const x of xs.slice(0,desired[phase])){if(selected.length<target&&!selectedX.has(x.xgid)){selected.push(x);selectedX.add(x.xgid);}}
}
for(const x of [...candidates].sort((a,b)=>a.gnuScreening.margin-b.gnuScreening.margin)){
  if(selected.length>=target)break;if(!selectedX.has(x.xgid)){selected.push(x);selectedX.add(x.xgid);}
}
if(selected.length<target) throw new Error(`only selected ${selected.length}/${target}; candidates=${candidates.length}; visited=${JSON.stringify(visitedByPhase)}; screened=${JSON.stringify(screenedByPhase)}`);
selected.forEach((p,i)=>{p.id=`q${String(idOffset+i+1).padStart(4,'0')}`;});
const phaseCounts={};for(const p of selected)phaseCounts[p.phaseBucket]=(phaseCounts[p.phaseBucket]||0)+1;
const out={schema:'mzand.xg.quarantine-diverse-pool.v24',target,generated:selected.length,baseStates,evaluatedDice,failures,seedBase,idOffset,pristineDataUsed:false,sealedDevUsed:false,xgLabelsUsedForTraining:false,desiredPhaseCounts:desired,visitedPhaseCounts:visitedByPhase,screenedPhaseCounts:screenedByPhase,selectedPhaseCounts:phaseCounts,positions:selected};
fs.writeFileSync('xg-quarantine-v24-pool.json',JSON.stringify(out,null,2)+'\n');
fs.writeFileSync('xg-quarantine-v24-matrix.json',JSON.stringify({include:selected.map(p=>({id:p.id,xgid:p.xgid,gnu_margin:Number(p.gnuScreening.margin.toFixed(6)),seed:p.seed,game:p.gameIndex,turn:p.turn,phase:p.phaseBucket}))}));
fs.writeFileSync('xg-quarantine-v24-report.txt',[`POOL: XG_QUARANTINE_DIVERSE_V24`,`POSITIONS: ${selected.length}`,`UNIQUE_XGIDS: ${selectedX.size}`,`BASE_STATES: ${baseStates}`,`GNU_SCREENED_DICE: ${evaluatedDice}`,`GENERATOR_FAILURES: ${failures}`,`SEED_BASE: ${seedBase}`,`VISITED_PHASE_COUNTS: ${JSON.stringify(visitedByPhase)}`,`SCREENED_PHASE_COUNTS: ${JSON.stringify(screenedByPhase)}`,`SELECTED_PHASE_COUNTS: ${JSON.stringify(phaseCounts)}`,'SPLIT: xg_quarantine','QUARANTINED: True','TRAINING_ELIGIBLE: False','SEALED_DEV_USED: False','PRISTINE_DATA_USED: False','XG_LABELS_USED_FOR_TRAINING: False'].join('\n')+'\n');
console.log(fs.readFileSync('xg-quarantine-v24-report.txt','utf8'));
