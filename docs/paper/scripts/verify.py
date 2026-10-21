"""Integrity checks for the supplied data and translated manuscripts."""
import json,hashlib,math,re
from pathlib import Path
P=Path(__file__).resolve().parents[1]
protocol=json.loads((P/'data/protocol.json').read_text())
rows=[json.loads(line) for line in (P/'data/episodes.jsonl').read_text().splitlines()]
assert protocol['horizon']==1200
assert len(rows)==480
assert len({(r['controller'],r['condition'],r['seed']) for r in rows})==480
for name,digest in protocol['inputs'].items():assert hashlib.sha256((P/'inputs'/f'{name}.json').read_bytes()).hexdigest()==digest
inputs=[json.loads((P/'inputs'/f'{name}.json').read_text()) for name in protocol['inputs']]
assert all(p['world']==inputs[0]['world'] and p['bindings']==inputs[0]['bindings'] for p in inputs)
for r in rows:
 assert 0<r['duration']<=1200
 assert all(math.isfinite(x) for x in r.values() if isinstance(x,(int,float)))
 assert r['survived']==(r['health']>0)
 assert not r['survived'] or r['duration']==1200
 assert abs(r['food_per_minute']-60*r['food']/r['duration'])<1e-10
for n,c in protocol['conditions']:
 block=[r for r in rows if (r['controller'],r['condition'])==(n,c)]
 assert sorted(r['seed'] for r in block)==protocol['seed_panel']
keys=['duration','food','food_per_minute','health','damage','distance','blocked_pct','firing_hz']
a={r['seed']:r for r in rows if r['controller']=='modulation' and r['condition']=='baseline'}
b={r['seed']:r for r in rows if r['controller']=='modulation' and r['condition']=='no_modulation'}
assert all(a[k][metric]==b[k][metric] for k in a for metric in keys)
assert all(x['identical'] for x in json.loads((P/'data/flattening_check.json').read_text()))
trace=json.loads((P/'data/modulation_trace_check.json').read_text());assert trace['ticks']==120000 and trace['spike_mismatch_ticks']==0
bib=set(re.findall(r'@\w+\{([^,]+)',(P/'references.bib').read_text()))
counts={}
for lang in ['en','ru']:
 text=(P/f'article-{lang}.tex').read_text();cites=set(k for g in re.findall(r'\\cite\w*\{([^}]+)\}',text) for k in g.split(','));assert cites<=bib and len(cites)==15
 labels=re.findall(r'\\label\{([^}]+)\}',text)
 for label in re.findall(r'\\ref\{([^}]+)\}',text):assert label in labels or label in ['tab:baseline','tab:controls','tab:cost']
 assert protocol['revision'] in text
 counts[lang]=dict(citations=len(cites),figures=len(re.findall(r'\\begin\{figure\}',text)),equations=len(re.findall(r'\\begin\{equation\}',text)))
assert counts['en']==counts['ru']
report=dict(raw_episode_count=len(rows),horizon=1200,distinct_conditions=8,seed_count=60,input_hashes_verified=True,world_and_bindings_identical=True,M_ablation_identical_all_recorded_metrics=True,flattening_identical=True,bilingual_structure=counts)
(P/'qa/data-integrity.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
