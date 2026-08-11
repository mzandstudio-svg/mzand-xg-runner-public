#!/usr/bin/env python3
"""Train the first afterstate-native MZand equity + ranking engine.

This replaces move-classification semantics with a Markov afterstate value model:

    legal moves -> afterstate equity evaluator + pairwise ranker -> search/rollout

Training/model selection uses only train/tune GNU labels. Sealed dev is opened
once after depth/blend are frozen. XG labels and pristine data are rejected.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import joblib
import numpy as np
from xgboost import XGBRanker, XGBRegressor


HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('GNU_V27_BATCH_OUT', 'gnu-teacher-v27-refined.jsonl'))
MODEL = Path(os.environ.get('MZAND_V27_MODEL_OUT', 'mzand-gnu-v27.joblib'))
REPORT_JSON = Path(os.environ.get('MZAND_V27_REPORT_JSON', 'mzand-gnu-v27-report.json'))
REPORT_TXT = Path(os.environ.get('MZAND_V27_REPORT_TXT', 'mzand-gnu-v27-report.txt'))
SEARCH_DEV_LIMIT = int(os.environ.get('MZAND_V27_SEARCH_DEV_LIMIT', '96'))
FULL_LEGAL_DEV_LIMIT = int(os.environ.get('MZAND_V27_FULL_LEGAL_DEV_LIMIT', '512'))
REQUIRE_ROLLOUT_ROWS = int(os.environ.get('MZAND_V27_REQUIRE_ROLLOUT_ROWS', '2'))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot import {path}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


enc = load_module('mzand_afterstate_v27_train', HERE / 'mzand-afterstate-v27.py')
engine_mod = load_module('mzand_engine_v27_train', HERE / 'mzand-engine-v27.py')


def load_rows() -> List[Dict]:
    rows = [json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
    if not rows:
        raise SystemExit('empty GNU v27 corpus')
    for i, row in enumerate(rows):
        if row.get('pristine') is not False:
            raise SystemExit(f'forbidden pristine/unknown provenance row {i}')
        if row.get('xgLabel') not in (False, None) or row.get('xgLabelUsed') is True:
            raise SystemExit(f'forbidden XG label row {i}')
        if row.get('teacherRolloutExecuted') and row.get('split') == 'dev':
            raise SystemExit(f'dev rollout refinement forbidden row {i}')
    return rows


def zscore(a: Sequence[float]) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    if len(a) <= 1:
        return np.zeros_like(a)
    s = float(np.std(a))
    return a - float(np.mean(a)) if s < 1e-9 else (a - float(np.mean(a))) / s


def base_weight(row: Dict) -> float:
    if row.get('teacherRolloutExecuted'):
        trials = int(row.get('rolloutTrials') or 1296)
        return 24.0 if trials >= 5184 else 18.0
    margin = row.get('teacherMargin')
    if isinstance(margin, (int, float)) and margin < 0.012:
        return 8.0
    if row.get('hard') or (isinstance(margin, (int, float)) and margin < 0.03):
        return 5.0
    return 1.0


def rank_dataset(rows: Sequence[Dict], splits: Iterable[str], mined: set[int] | None = None):
    wanted = set(splits); mined = mined or set()
    X=[]; y=[]; qid=[]; group_w=[]; gid=0
    for i,row in enumerate(rows):
        if row.get('split') not in wanted:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        w = max(base_weight(row), 12.0 if i in mined else 0.0)
        group_w.append(w)
        n = len(hints)
        eqs = [float(h.get('equity', 0.0)) for h in hints]
        lo = min(eqs)
        for h,eq in zip(hints,eqs):
            X.append(enc.afterstate_features(row,h))
            rank = int(h.get('rank', n))
            # Relevance is primarily rank/top-1, with a small equity-gap signal.
            gap_bucket = min(20, max(0, int(round((eq-lo) * 50.0))))
            y.append(float((n-rank+1) + (8 if rank == 1 else 0) + gap_bucket))
            qid.append(gid)
        gid += 1
    if not X:
        raise RuntimeError('empty ranking dataset')
    return np.stack(X), np.asarray(y,np.float32), np.asarray(qid,np.int32), np.asarray(group_w,np.float32)


def equity_dataset(rows: Sequence[Dict], splits: Iterable[str], mined: set[int] | None = None):
    wanted=set(splits); mined=mined or set(); X=[]; y=[]; w=[]
    for i,row in enumerate(rows):
        if row.get('split') not in wanted:
            continue
        hints=row.get('hints') or []
        ww=max(base_weight(row), 12.0 if i in mined else 0.0)
        for h in hints:
            X.append(enc.afterstate_features(row,h))
            y.append(float(h.get('equity',0.0)))
            w.append(ww)
    if not X:
        raise RuntimeError('empty equity dataset')
    return np.stack(X),np.asarray(y,np.float32),np.asarray(w,np.float32)


def models(depth: int, seed: int):
    ranker=XGBRanker(
        objective='rank:pairwise', eval_metric='ndcg@1', n_estimators=2400,
        max_depth=depth, learning_rate=.016, min_child_weight=3,
        subsample=.95, colsample_bytree=.95, reg_alpha=.02, reg_lambda=3.5,
        tree_method='hist', n_jobs=-1, random_state=seed,
    )
    reg=XGBRegressor(
        objective='reg:squarederror', n_estimators=2400,
        max_depth=depth, learning_rate=.016, min_child_weight=3,
        subsample=.95, colsample_bytree=.95, reg_alpha=.02, reg_lambda=3.5,
        tree_method='hist', n_jobs=-1, random_state=seed+1,
    )
    return ranker,reg


def train(rows, splits, depth, seed, mined=None):
    X,y,q,w=rank_dataset(rows,splits,mined)
    ranker,reg=models(depth,seed)
    ranker.fit(X,y,qid=q,sample_weight=w)
    Xe,ye,we=equity_dataset(rows,splits,mined)
    reg.fit(Xe,ye,sample_weight=we)
    return ranker,reg


def score_row(ranker, reg, alpha: float, row: Dict):
    hints=row.get('hints') or []
    X=np.stack([enc.afterstate_features(row,h) for h in hints])
    rs=np.asarray(ranker.predict(X),float)
    eq=np.asarray(reg.predict(X),float)
    blend=alpha*zscore(rs)+(1-alpha)*zscore(eq)
    return blend,eq,rs


def evaluate(ranker, reg, alpha: float, rows: Sequence[Dict], split: str, details=False):
    total=strict=top2=top3=hardn=hards=0; losses=[]; out=[]; sq=[]; ae=[]; cand_n=0
    for row in rows:
        if row.get('split') != split:
            continue
        hints=row.get('hints') or []
        if len(hints)<2:
            continue
        blend,eq,_=score_row(ranker,reg,alpha,row)
        p=int(np.argmax(blend)); rank=int(hints[p].get('rank',999))
        top=float(hints[0].get('equity',0.0)); got=float(hints[p].get('equity',0.0)); loss=max(0.0,top-got)
        targets=np.asarray([float(h.get('equity',0.0)) for h in hints],float)
        sq.extend(((eq-targets)**2).tolist()); ae.extend(np.abs(eq-targets).tolist()); cand_n += len(hints)
        total+=1; strict+=rank==1; top2+=rank<=2; top3+=rank<=3; losses.append(loss)
        if row.get('hard'):
            hardn+=1; hards+=rank==1
        if details:
            out.append({'gameIndex':row.get('gameIndex'),'turn':row.get('turn'),'dice':row.get('dice'),'teacherMargin':row.get('teacherMargin'),'hard':bool(row.get('hard')),'pickedRank':rank,'equityLoss':loss})
    a=np.asarray(losses,float)
    return {
        'samples':total,
        'strictTop1':strict/total if total else 0.0,
        'top2':top2/total if total else 0.0,
        'top3':top3/total if total else 0.0,
        'meanEquityLoss':float(np.mean(a)) if total else None,
        'p95EquityLoss':float(np.quantile(a,.95)) if total else None,
        'hardSamples':hardn,
        'hardStrictTop1':hards/hardn if hardn else None,
        'equityCandidateSamples':cand_n,
        'equityRMSE':math.sqrt(float(np.mean(sq))) if sq else None,
        'equityMAE':float(np.mean(ae)) if ae else None,
        'details':out,
    }


def metric_key(m: Dict):
    return (m['strictTop1'],-m['meanEquityLoss'],m['top2'],m['hardStrictTop1'] or 0.0,-m['equityRMSE'])


def mine_disagreements(rows, ranker, reg, alpha: float):
    mined=set(); wrong=low=0; eligible=0
    for i,row in enumerate(rows):
        if row.get('split') not in ('train','tune'):
            continue
        hints=row.get('hints') or []
        if len(hints)<2:
            continue
        eligible += 1
        blend,_,_=score_row(ranker,reg,alpha,row)
        picked=int(np.argmax(blend)); bad=int(hints[picked].get('rank',999)) != 1
        margin=row.get('teacherMargin'); lm=isinstance(margin,(int,float)) and margin<0.03
        wrong += int(bad); low += int(lm)
        if bad or lm:
            mined.add(i)
    return mined, {'eligible':eligible,'disagreementRows':wrong,'lowMarginRows':low,'minedRows':len(mined)}


def board_key(board: Dict):
    return (
        tuple(int(x) for x in board['own']), tuple(int(x) for x in board['opp']),
        int(board.get('barOwn',0)), int(board.get('barOpp',0)),
        int(board.get('offOwn',0)), int(board.get('offOpp',0)),
    )


def teacher_afterstate_key(row: Dict, hint: Dict):
    return board_key(enc.afterstate_from_hint(row['board'],hint))


def generated_coverage(rows: Sequence[Dict], split='dev', limit=FULL_LEGAL_DEV_LIMIT):
    n=top_cov=all_hints=all_cov=0; legal_counts=[]; failures=[]
    for row in rows:
        if row.get('split')!=split:
            continue
        hints=row.get('hints') or []
        if len(hints)<2:
            continue
        try:
            cands=engine_mod.generate_legal_candidates(row['board'],row['dice'])
            keys={board_key(engine_mod.apply_candidate(row['board'],c)) for c in cands}
        except Exception as exc:
            failures.append({'gameIndex':row.get('gameIndex'),'turn':row.get('turn'),'dice':row.get('dice'),'error':str(exc)})
            continue
        n+=1; legal_counts.append(len(cands))
        top_cov += int(teacher_afterstate_key(row,hints[0]) in keys)
        for h in hints:
            all_hints += 1; all_cov += int(teacher_afterstate_key(row,h) in keys)
        if n>=limit:
            break
    return {
        'samples':n,
        'teacherTopGeneratedCoverage':top_cov/n if n else None,
        'teacherHintGeneratedCoverage':all_cov/all_hints if all_hints else None,
        'teacherHintSamples':all_hints,
        'meanLegalCandidates':float(np.mean(legal_counts)) if legal_counts else None,
        'maxLegalCandidates':max(legal_counts) if legal_counts else None,
        'failures':failures[:20],
    }


def full_legal_eval(artifact: Dict, rows: Sequence[Dict], limit=FULL_LEGAL_DEV_LIMIT, search_depth=1, beam=8):
    # Save/load through an in-memory-like temp artifact path is unnecessary; build a
    # light object without touching dev for any tuning.
    engine=engine_mod.MZandEngine.__new__(engine_mod.MZandEngine)
    engine.artifact=artifact; engine.equity=artifact['equityRegressor']; engine.ranker=artifact['ranker']; engine.alpha=float(artifact['rankBlendAlpha']); engine.beam_width=beam
    n=top1=matched_hint=0; legal_counts=[]; errors=[]
    for row in rows:
        if row.get('split')!='dev': continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        try:
            scored=engine.search(row['board'],row['dice'],depth=search_depth)
            if not scored: continue
            pick=scored[0].candidate
            pk=board_key(engine_mod.apply_candidate(row['board'],pick))
            tk=teacher_afterstate_key(row,hints[0])
            top1 += int(pk==tk)
            hkeys={teacher_afterstate_key(row,h) for h in hints}
            matched_hint += int(pk in hkeys)
            legal_counts.append(len(engine_mod.generate_legal_candidates(row['board'],row['dice'])))
            n += 1
        except Exception as exc:
            errors.append({'gameIndex':row.get('gameIndex'),'turn':row.get('turn'),'dice':row.get('dice'),'error':str(exc)})
        if n>=limit: break
    return {
        'samples':n,'searchDepth':search_depth,'beamWidth':beam,
        'strictTop1VsGNUTeacher':top1/n if n else None,
        'pickedMovePresentInGNUHints':matched_hint/n if n else None,
        'meanLegalCandidates':float(np.mean(legal_counts)) if legal_counts else None,
        'errors':errors[:20],
    }


def export_train_tune_errors(ranker,reg,alpha,rows):
    out=[]
    for i,row in enumerate(rows):
        if row.get('split') not in ('train','tune'): continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        blend,_,_=score_row(ranker,reg,alpha,row); p=int(np.argmax(blend)); rank=int(hints[p].get('rank',999))
        if rank==1: continue
        top=float(hints[0].get('equity',0)); got=float(hints[p].get('equity',0))
        out.append({'sourceRowIndex':i,'sourceSplit':row.get('split'),'gameIndex':row.get('gameIndex'),'turn':row.get('turn'),'positionId':row.get('positionId'),'dice':row.get('dice'),'teacherMargin':row.get('teacherMargin'),'pickedRank':rank,'equityLoss':max(0.,top-got),'rolloutCandidate':True,'pristine':False,'xgLabelUsed':False,'devUsed':False,'trainingEligible':True})
    return sorted(out,key=lambda r:(r['equityLoss'],-(r['teacherMargin'] or 0)),reverse=True)


def main():
    rows=load_rows()
    counts={s:sum(1 for r in rows if r.get('split')==s and len(r.get('hints') or [])>=2) for s in ('train','tune','dev')}
    if min(counts.values())<100:
        raise SystemExit(f'insufficient independent split sizes {counts}')
    rollout_rows=sum(bool(r.get('teacherRolloutExecuted')) for r in rows)
    if rollout_rows != REQUIRE_ROLLOUT_ROWS:
        raise SystemExit(f'expected exactly {REQUIRE_ROLLOUT_ROWS} verified rollout-refined rows, got {rollout_rows}')

    # Preliminary train-only pass; tune selects initial blend for mining.
    pr,pg=train(rows,['train'],8,20262701)
    preliminary_alpha=max((.35,.50,.65,.80,1.0),key=lambda a:metric_key(evaluate(pr,pg,a,rows,'tune')))
    mined,mining=mine_disagreements(rows,pr,pg,preliminary_alpha)

    trials=[]; best=None
    for depth in (7,9,11):
        r,g=train(rows,['train'],depth,20262720+depth,mined)
        for alpha in (.35,.50,.65,.80,1.0):
            tune=evaluate(r,g,alpha,rows,'tune')
            compact={k:v for k,v in tune.items() if k!='details'}
            trials.append({'depth':depth,'rankBlendAlpha':alpha,'tune':compact})
            k=metric_key(tune)
            if best is None or k>best[0]: best=(k,depth,alpha)
    _,depth,alpha=best

    # Frozen configuration; only now include tune in fitting and open dev once.
    ranker,reg=train(rows,['train','tune'],depth,20262770,mined)
    dev=evaluate(ranker,reg,alpha,rows,'dev',True)
    tune_after=evaluate(ranker,reg,alpha,rows,'tune')

    artifact={
        'version':'mzand-gnu-v27',
        'architecture':'AFTERSTATE_EQUITY_PLUS_PAIRWISE_RANK_SEARCH',
        'featureSchema':'mzand.afterstate.v27',
        'featureCount':enc.feature_count(),
        'ranker':ranker,
        'equityRegressor':reg,
        'rankBlendAlpha':alpha,
        'depth':depth,
        'teacher':'GNU Backgammon + verified true GNU rollout refinements',
        'rolloutRefinedRows':rollout_rows,
        'candidateGeneration':'MZAND_EXHAUSTIVE_LEGAL_RUNTIME',
        'classifierUsed':False,
        'devUsedForModelSelection':False,
        'xgLabelsUsed':False,
        'pristineDataUsed':False,
    }
    joblib.dump(artifact,MODEL)

    coverage=generated_coverage(rows)
    full_legal=full_legal_eval(artifact,rows,limit=FULL_LEGAL_DEV_LIMIT,search_depth=1,beam=8)
    search2=full_legal_eval(artifact,rows,limit=SEARCH_DEV_LIMIT,search_depth=2,beam=4)
    errors=export_train_tune_errors(ranker,reg,alpha,rows)
    Path('mzand-gnu-v27-rollout-queue.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in errors))

    report={
        'model':'mzand-gnu-v27',
        'phase':'AFTERSTATE_EQUITY_RANK_EXHAUSTIVE_SEARCH',
        'selectedBy':'tune only; dev untouched until frozen final evaluation',
        'classifierUsed':False,
        'splitCounts':counts,
        'rolloutRefinedRows':rollout_rows,
        'preliminaryAlpha':preliminary_alpha,
        'mining':mining,
        'selectedDepth':depth,
        'rankBlendAlpha':alpha,
        'trials':trials,
        'tuneAfterRefit':{k:v for k,v in tune_after.items() if k!='details'},
        'dev':{k:v for k,v in dev.items() if k!='details'},
        'devDetails':dev['details'],
        'generatorCoverageDev':coverage,
        'fullLegalDev':full_legal,
        'searchDepth2Dev':search2,
        'trainTuneRolloutQueueRows':len(errors),
        'devUsedForModelSelection':False,
        'devRowsMined':0,
        'pristineDataUsed':False,
        'xgLabelsUsed':False,
    }
    REPORT_JSON.write_text(json.dumps(report,indent=2)+'\n')

    def f(v): return 'NA' if v is None else f'{v:.6f}'
    REPORT_TXT.write_text('\n'.join([
        'MODEL: mzand-gnu-v27',
        'ARCHITECTURE: AFTERSTATE_EQUITY_PLUS_PAIRWISE_RANK_SEARCH',
        'CLASSIFIER_USED: False',
        f'FEATURE_COUNT: {enc.feature_count()}',
        f'ROLLOUT_REFINED_ROWS: {rollout_rows}',
        f'MINED_ROWS: {mining["minedRows"]}',
        f'SELECTED_DEPTH: {depth}',
        f'RANK_BLEND_ALPHA: {alpha:.2f}',
        f'TRAIN_POSITION_SAMPLES: {counts["train"]}',
        f'TUNE_POSITION_SAMPLES: {counts["tune"]}',
        f'DEV_POSITION_SAMPLES: {counts["dev"]}',
        f'DEV_STRICT_TOP1: {dev["strictTop1"]:.6f}',
        f'DEV_TOP2: {dev["top2"]:.6f}',
        f'DEV_TOP3: {dev["top3"]:.6f}',
        f'DEV_MEAN_EQUITY_LOSS: {dev["meanEquityLoss"]:.6f}',
        f'DEV_P95_EQUITY_LOSS: {dev["p95EquityLoss"]:.6f}',
        f'DEV_HARD_SAMPLES: {dev["hardSamples"]}',
        f'DEV_HARD_STRICT_TOP1: {f(dev["hardStrictTop1"])}',
        f'DEV_EQUITY_CANDIDATE_SAMPLES: {dev["equityCandidateSamples"]}',
        f'DEV_EQUITY_RMSE: {f(dev["equityRMSE"])}',
        f'DEV_EQUITY_MAE: {f(dev["equityMAE"])}',
        f'GENERATOR_DEV_SAMPLES: {coverage["samples"]}',
        f'GENERATOR_TEACHER_TOP_COVERAGE: {f(coverage["teacherTopGeneratedCoverage"])}',
        f'GENERATOR_TEACHER_HINT_COVERAGE: {f(coverage["teacherHintGeneratedCoverage"])}',
        f'FULL_LEGAL_DEV_SAMPLES: {full_legal["samples"]}',
        f'FULL_LEGAL_TOP1_VS_GNU: {f(full_legal["strictTop1VsGNUTeacher"])}',
        f'SEARCH_DEPTH2_DEV_SAMPLES: {search2["samples"]}',
        f'SEARCH_DEPTH2_TOP1_VS_GNU: {f(search2["strictTop1VsGNUTeacher"])}',
        f'TRAIN_TUNE_ROLLOUT_QUEUE_ROWS: {len(errors)}',
        'SELF_PLAY_ROLLOUT_LABELS_TRAINING_ELIGIBLE: False',
        'DEV_USED_FOR_MODEL_SELECTION: False',
        'DEV_ROWS_MINED: 0',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
    ])+'\n')
    print(REPORT_TXT.read_text())


if __name__=='__main__':
    main()
