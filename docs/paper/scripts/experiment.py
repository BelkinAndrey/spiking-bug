"""Frozen-controller comparison; run from repository root with .venv/bin/python."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import sys, json, copy, hashlib, platform, time, threading, argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
PAPER=Path(__file__).resolve().parents[1]
ROOT=PAPER.parent
sys.path.insert(0,str(PAPER/"runtime_snapshot"))
import numpy as np
from server import schema
from server.engine import Network
from server.trials import run_attempt
from server.development import expand_synapse
NAMES=['direct','modulation','ganglia-populatio']

def project(name, condition='baseline'):
    p=schema.migrate_project(json.loads((PAPER/'inputs'/f'{name}.json').read_text()))
    p['compute']={'device':'cpu'}
    if condition=='no_modulation':
        p['topology']['synapses']=[s for s in p['topology']['synapses'] if s['kind']=='direct']
    if condition=='neural_cost':p['world']['config']['neuron_fatigue_rate']=0.001
    if condition=='flat':
        t=p['topology'];nodes={n['id']:n for n in t['neurons']};groups={g['id']:g['members'] for g in t['ganglia']}
        edges=[]
        for s in t['synapses']:
            for a,b,w in expand_synapse(s,nodes,groups):
                e=copy.deepcopy(s);e.update(id=f'flat_{len(edges)}',source=a,target=b,weight=w);edges.append(e)
        t['synapses']=edges;t['ganglia']=[];t['groups']=[]
    return p

def task(args):
    name,condition,seed,horizon=args
    start=time.monotonic()
    p=project(name,condition)
    r=run_attempt(p,dict(seed=seed,duration=horizon,randomize=True),0,threading.Event(),lambda *a:None)
    r.update(controller=name,condition=condition,wall_seconds=time.monotonic()-start)
    return r

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workers',type=int,default=4);ap.add_argument('--seeds',type=int,default=60);ap.add_argument('--horizon',type=int,default=1200);args=ap.parse_args()
    seeds=list(range(21000,21000+args.seeds))
    conditions=[(n,'baseline') for n in NAMES]+[(n,'no_modulation') for n in NAMES[1:]]+[(n,'neural_cost') for n in NAMES]
    tasks=[(n,c,s,args.horizon) for n,c in conditions for s in seeds]
    manifest=dict(protocol_version=2,date='2026-10-21',revision='befd6a0d53204722ade40be96000c3898b2158e5',seed_panel=seeds,pilot_seed_excluded=9000,horizon=args.horizon,randomize=True,device='cpu',dt=schema.DT,workers=args.workers,conditions=conditions,neural_cost_rate=0.001,python=sys.version,numpy=np.__version__,platform=platform.platform(),inputs={n:hashlib.sha256((PAPER/'inputs'/f'{n}.json').read_bytes()).hexdigest() for n in NAMES})
    manifest['evaluation_amendment']=json.loads((PAPER/'data/design-provenance.json').read_text())['evaluation_amendment']
    (PAPER/'data'/'protocol.json').write_text(json.dumps(manifest,indent=2))
    stats={}
    for n in NAMES:
        p=project(n);net=Network(p['topology']);stats[n]=dict(neurons=net.n,ganglia=len(p['topology']['ganglia']),explicit_synapses=len(p['topology']['synapses']),effective_edges=len(net.sources),positive_direct=int(np.sum((net.kinds==0)&(net.weights>=0))),negative_direct=int(np.sum((net.kinds==0)&(net.weights<0))),mod_exc=int(np.sum(net.kinds==1)),mod_inh=int(np.sum(net.kinds==2)),noise_neurons=int(np.count_nonzero(net.noise_std)),world=p['world']['config'])
    (PAPER/'data'/'structure.json').write_text(json.dumps(stats,indent=2))
    with (PAPER/'data'/'episodes.jsonl').open('w') as f, ProcessPoolExecutor(max_workers=args.workers,mp_context=mp.get_context('spawn')) as pool:
        for i,r in enumerate(pool.map(task,tasks)):
            f.write(json.dumps(r)+'\n');f.flush()
            if (i+1)%20==0:print(f'{i+1}/{len(tasks)} episodes',flush=True)
    # Exact flattening control and deterministic replay, prechosen first three seeds.
    checks=[]
    for seed in seeds[:3]:
        original=task(('ganglia-populatio','baseline',seed,args.horizon));flat=task(('ganglia-populatio','flat',seed,args.horizon))
        keys=['duration','survived','food','health','damage','distance','blocked_pct','firing_hz']
        checks.append(dict(seed=seed,identical=all(original[k]==flat[k] for k in keys),original=original,flat=flat))
    (PAPER/'data'/'flattening_check.json').write_text(json.dumps(checks,indent=2));assert all(x['identical'] for x in checks)
    print('DONE; flattening controls identical',flush=True)
if __name__=='__main__':main()
