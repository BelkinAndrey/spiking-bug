"""Descriptive control on the stored scene; separate from randomized episodes."""
from pathlib import Path
import sys,json,threading
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P/"runtime_snapshot"))
from server import schema
from server.trials import run_attempt
out=[]
for name in ['direct','modulation','ganglia-populatio']:
 p=schema.migrate_project(json.loads((P/'inputs'/f'{name}.json').read_text()));p['compute']={'device':'cpu'}
 r=run_attempt(p,dict(seed=42,duration=1200,randomize=False),0,threading.Event(),lambda *a:None);r['controller']=name;out.append(r)
(P/'data/saved_scene_check.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
