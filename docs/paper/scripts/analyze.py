"""Paired descriptive inference and bilingual publication figures."""
from pathlib import Path
import json,csv,collections
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
P=Path(__file__).resolve().parents[1]
H=json.loads((P/'data/protocol.json').read_text())['horizon']
N=['direct','modulation','ganglia-populatio'];C=['#347FA3','#D88A37','#53834B']
rows=[json.loads(x) for x in (P/'data/episodes.jsonl').read_text().splitlines()]
assert len(rows)==480 and len({(r['controller'],r['condition'],r['seed']) for r in rows})==480
rng=np.random.default_rng(20261021); ix=rng.integers(0,60,(20000,60))
metrics=['duration','food','food_per_minute','health','damage','distance','blocked_pct','firing_hz']
def vals(n,c,k):return np.array([r[k] for r in sorted(rows,key=lambda r:r['seed']) if r['controller']==n and r['condition']==c],float)
def ci(a):return np.quantile(a[ix].mean(axis=1),[.025,.975]).tolist()
def stat(a):return dict(mean=float(a.mean()),sd=float(a.std(ddof=1)),ci95=ci(a))
summary={}
for n,c in dict.fromkeys((r['controller'],r['condition']) for r in rows):
 d={k:stat(vals(n,c,k)) for k in metrics};a=vals(n,c,'survived');p=a.mean();z=1.95996398454;den=1+z*z/60;mid=(p+z*z/120)/den;half=z*np.sqrt(p*(1-p)/60+z*z/(4*60**2))/den
 d['survival']=dict(count=int(a.sum()),n=60,proportion=float(p),wilson95=[mid-half,mid+half]);summary[n+'/'+c]=d
comparisons={}
for n,b in [('modulation','direct'),('ganglia-populatio','modulation'),('ganglia-populatio','direct')]:comparisons[n+'-'+b]={k:stat(vals(n,'baseline',k)-vals(b,'baseline',k)) for k in ['duration','food','food_per_minute']}
for n in N[1:]:comparisons[n+'-ablation']={k:stat(vals(n,'baseline',k)-vals(n,'no_modulation',k)) for k in ['duration','food','food_per_minute']}
for n in N:comparisons[n+'-cost']={k:stat(vals(n,'neural_cost',k)-vals(n,'baseline',k)) for k in ['duration','food','food_per_minute']}
(P/'data/summary.json').write_text(json.dumps(dict(summary=summary,comparisons=comparisons,bootstrap_samples=20000,bootstrap_seed=20261021),indent=2))
with (P/'data/episodes.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'savefig.bbox':'tight'})
for lang in ['en','ru']:
 ru=lang=='ru';labels=['D: прямые','M: модуляция','G: ганглии'] if ru else ['D: direct','M: modulation','G: ganglia']
 def save(fig,name):
  fig.savefig(P/'figures'/f'{name}-{lang}.pdf');fig.savefig(P/'figures'/f'{name}-{lang}.png',dpi=180);plt.close(fig)
 fig,axs=plt.subplots(1,3,figsize=(10.2,3.5),layout='constrained')
 for ax,k,title in zip(axs,['duration','food','food_per_minute'],['Время жизни до 1200 с, с','Пища за эпизод, порции','Пища / мин жизни'] if ru else ['Restricted survival time, s','Food per episode, portions','Food per minute alive']):
  for j,n in enumerate(N):
   a=vals(n,'baseline',k);st=stat(a);jitter=np.random.default_rng(42).uniform(-.13,.13,60)
   ax.scatter(j+jitter,a,s=12,alpha=.45,color=C[j],edgecolors='none');lo,hi=st['ci95'];ax.errorbar(j+.22,st['mean'],yerr=[[st['mean']-lo],[hi-st['mean']]],fmt='o',color='#182A32',capsize=4,ms=5)
  ax.set(xticks=range(3),xticklabels=['D','M','G'],title=title);ax.grid(axis='y',alpha=.16);ax.set_ylim(bottom=0)
 fig.supxlabel('60 общих seed; точки — эпизоды; чёрные интервалы — среднее и 95% ДИ' if ru else '60 shared seeds; points = episodes; black intervals = mean and 95% CI',fontsize=10);save(fig,'performance')
 fig,axs=plt.subplots(1,2,figsize=(10.2,3.6),layout='constrained')
 for ax,condition,title in zip(axs,['baseline','neural_cost'],['Без затрат на нейроны','Затраты: 0.001 на нейрон в секунду'] if ru else ['No neuron-count fatigue cost','Cost: 0.001 per neuron per second']):
  for n,c,label in zip(N,C,labels):
   a=vals(n,condition,'duration');surv=vals(n,condition,'survived');deaths=np.sort(np.unique(a[surv==0]));ts=np.r_[0,deaths,H];ys=[1.]+[np.mean((a>t)|((a==t)&(surv==1))) for t in deaths]+[surv.mean()];ax.step(ts,ys,where='post',color=c,label=label,lw=2)
  ax.set(xlim=(0,H),ylim=(0,1.04),xlabel='Время, с' if ru else 'Time, s',ylabel='Доля живых' if ru else 'Survival probability',title=title);ax.grid(alpha=.15);ax.legend(loc='lower left',fontsize=9)
 save(fig,'survival')
 fig,axs=plt.subplots(1,2,figsize=(10.2,3.7),layout='constrained')
 for ax,k,title in zip(axs,['duration','food'],['Время жизни до 1200 с, с','Пища за эпизод, порции'] if ru else ['Restricted survival time, s','Food per episode, portions']):
  for j,n in enumerate(N[1:]):
   for off,cond,color,lab in [(-.14,'baseline',C[j+1],'Полная сеть' if ru else 'Intact'),(.14,'no_modulation','#999999','Без модуляции' if ru else 'No modulation')]:
    st=stat(vals(n,cond,k));lo,hi=st['ci95'];ax.errorbar(j+off,st['mean'],yerr=[[st['mean']-lo],[hi-st['mean']]],fmt='o',ms=8,capsize=5,color=color,label=lab if j==0 else None)
  ax.set(xticks=[0,1],xticklabels=['M','G'],title=title,xlim=(-.5,1.5));ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.15);ax.legend(fontsize=9)
 save(fig,'ablation')
 fig,axs=plt.subplots(1,2,figsize=(10.2,3.7),layout='constrained')
 structure=json.loads((P/'data/structure.json').read_text())
 for j,n in enumerate(N):
  ax=axs[0];st=stat(vals(n,'baseline','food'));lo,hi=st['ci95'];ax.errorbar(structure[n]['neurons'],st['mean'],yerr=[[st['mean']-lo],[hi-st['mean']]],fmt='o',color=C[j],capsize=5,label=labels[j],ms=8)
  ax=axs[1];a=vals(n,'baseline','food')/structure[n]['neurons'];st=stat(a);lo,hi=st['ci95'];ax.errorbar(j,st['mean'],yerr=[[st['mean']-lo],[hi-st['mean']]],fmt='o',color=C[j],capsize=5,ms=8)
 axs[0].set(xscale='log',xlabel='Число нейронов (лог. шкала)' if ru else 'Neuron count (log scale)',ylabel='Пища за эпизод' if ru else 'Food per episode');axs[0].legend(fontsize=9);axs[1].set(xticks=range(3),xticklabels=['D','M','G'],ylabel='Порции / нейрон / эпизод' if ru else 'Portions / neuron / episode');
 for ax in axs:ax.set_ylim(bottom=0);ax.grid(alpha=.15)
 save(fig,'resources')
 # Conceptual figure; explicitly a representational sequence, not historical chronology.
 fig,ax=plt.subplots(figsize=(10.2,2.7));ax.set(xlim=(0,10),ylim=(0,2.7));ax.axis('off')
 titles=['Прямое действие','Модуляция','Ганглии'] if ru else ['Direct transmission','Modulation','Ganglia']
 texts=['Ток → потенциал\nвозбуждение / торможение','Состояние чувствительности\nконтекст и временная память','Группы и проекции\nконструирование популяций'] if ru else ['Current → potential\nexcitation / inhibition','Sensitivity state\ncontext and temporal memory','Groups and projections\npopulation construction']
 for j in range(3):
  x=.1+j*3.4;ax.add_patch(FancyBboxPatch((x,.75),3,1.45,boxstyle='round,pad=.08',fc=C[j],ec='none',alpha=.12));ax.text(x+1.5,1.86,titles[j],ha='center',weight='bold',color=C[j],fontsize=12);ax.text(x+1.5,1.3,texts[j],ha='center',va='center',fontsize=10)
  if j<2:ax.annotate('',xy=(x+3.32,1.5),xytext=(x+3.07,1.5),arrowprops={'arrowstyle':'->','color':'#333333','lw':1.5})
 ax.text(5,.23,'Расширение средств проектирования; не установленная филогенетическая последовательность' if ru else 'Expansion of design tools; not an established phylogenetic sequence',ha='center',fontsize=10)
 save(fig,'concept')
print(json.dumps({'summary':summary,'comparisons':comparisons},indent=2))
