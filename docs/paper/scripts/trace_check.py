"""One fixed-seed mechanistic diagnostic; no controller tuning."""
import sys, json, copy, math
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P/"runtime_snapshot"))
from server import schema
from server.engine import Network
from server.world import World
p=schema.migrate_project(json.loads((P/'inputs/modulation.json').read_text()))
w=copy.deepcopy(p['world']);w['config']['seed']=21000;w['objects']=[o for o in w['objects'] if o['kind']=='obstacle'];world=World(w)
for kind,radius in [('food',7),('threat',16)]:
 for _ in range(world.config[kind+'_target']):
  xy=world.random_point(radius,kind=='food')
  if xy and (kind=='food' or math.hypot(xy[0]-world.agent['x'],xy[1]-world.agent['y'])>world.config['threat_radius']):world.add_object(dict(kind=kind,x=xy[0],y=xy[1]))
world.sense();a=Network(p['topology'],21000);t=copy.deepcopy(p['topology']);t['synapses']=[s for s in t['synapses'] if s['kind']=='direct'];b=Network(t,21000)
sensors=[(k,a.index[v]) for k,v in p['bindings'].items() if k in schema.SENSORS and v in a.index];motors=[(k,a.index[v]) for k,v in p['bindings'].items() if k in schema.MOTORS and v in a.index]
u=np.zeros(a.n,np.float32);different=0;mod_ticks=0;maxsens=1.;j=a.index['motor_forward']
for tick in range(120000):
 u.fill(0)
 for key,i in sensors:u[i]+=world.sensors[key]
 sa=a.step(u);sb=b.step(u);different+=int(np.any(sa!=sb));mod_ticks+=int(a.sensitivity[j,0]!=1);maxsens=max(maxsens,float(a.sensitivity[j,0]));world.step({k:bool(sa[i]) for k,i in motors},neuron_count=a.n)
 if world.agent['health']<=0:break
result=dict(seed=21000,ticks=tick+1,forward_spikes=int(a.total[j]),forward_firing_hz=float(a.total[j])/((tick+1)*schema.DT),forward_refractory_ceiling_hz=1/(schema.DT*(int(a.refractory[j])+1)),spike_mismatch_ticks=different,modulated_ticks=mod_ticks,max_forward_exc_sensitivity=maxsens,note='Both networks receive the intact closed-loop input stream; zero spike mismatch implies the ablated trajectory would be identical on this seed.')
(P/'data/modulation_trace_check.json').write_text(json.dumps(result,indent=2));print(result)
