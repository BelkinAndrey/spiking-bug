from pathlib import Path
import json
P=Path(__file__).resolve().parents[1];data=json.loads((P/'data/summary.json').read_text());s=data['summary'];c=data['comparisons'];trace=json.loads((P/'data/modulation_trace_check.json').read_text());N=['direct','modulation','ganglia-populatio'];S=['D','M','G']
mac={}
for n,short in zip(N,S):
 for key,label in [('food','Food'),('duration','Time')]:mac[short+label]=f"{s[n+'/baseline'][key]['mean']:.2f}"
 mac[short+'Surv']=str(s[n+'/baseline']['survival']['count'])
 count={'D':17,'M':19,'G':783}[short];mac[short+'FoodPerNeuron']=f"{s[n+'/baseline']['food']['mean']/count:.3f}"
mac['GNoModFood']=f"{s['ganglia-populatio/no_modulation']['food']['mean']:.2f}"
for key,prefix in [('modulation-direct','MD'),('ganglia-populatio-modulation','GM'),('ganglia-populatio-ablation','GAbl')]:
 x=c[key]['food'];mac[prefix+'Diff' if prefix=='GAbl' else prefix+'diff']=f"{x['mean']:.2f}";mac[prefix+'Lo' if prefix=='GAbl' else prefix+'lo']=f"{x['ci95'][0]:.2f}";mac[prefix+'Hi' if prefix=='GAbl' else prefix+'hi']=f"{x['ci95'][1]:.2f}"
mac.update(TraceMismatch=str(trace['spike_mismatch_ticks']),TraceModTicks=str(trace['modulated_ticks']),TraceMaxSens=f"{trace['max_forward_exc_sensitivity']:.2f}")
(P/'data/results-macros.tex').write_text('\n'.join('\\newcommand{\\'+k+'}{'+v+'}' for k,v in mac.items())+'\n')
def value(d,k):
 a=d[k];return f"{a['mean']:.2f} [{a['ci95'][0]:.2f}, {a['ci95'][1]:.2f}]"
for lang in ['en','ru']:
 ru=lang=='ru'
 text=r'\begin{table}[tbp]\centering\small\setlength{\tabcolsep}{4pt}'+'\n'+r'\caption{'+(r'Основные результаты: средние и 95\% бутстреп-интервалы; $n=60$ для каждой сети. Для выживания показаны 95\%-ные интервалы Уилсона в процентах.' if ru else r'Baseline results: means and 95\% bootstrap intervals; $n=60$ per controller. Survival intervals are Wilson 95\% intervals, in percent.')+r'}\label{tab:baseline}'+'\n'+r'\begin{tabular}{lccc}\toprule'+'\n'+('Показатель' if ru else 'Endpoint')+r' & D & M & G\\\midrule'+'\n'
 for key,title in [('duration','RMST, s' if not ru else 'RMST, с'),('food','Food, portions' if not ru else 'Пища, порции'),('food_per_minute','Food/min alive' if not ru else 'Пища/мин жизни'),('health',r'Final health, \%' if not ru else r'Здоровье в конце, \%')]:text+=title+' & '+' & '.join(value(s[n+'/baseline'],key) for n in N)+r'\\'+'\n'
 text+=('Survived' if not ru else 'Дожили до 1200 с')+' & '+' & '.join(str(s[n+'/baseline']['survival']['count'])+'/60' for n in N)+r'\\'+'\n'
 text+=(r'Survival CI, \%' if not ru else r'Выживание: ДИ, \%')+' & '+' & '.join(f"[{100*s[n+'/baseline']['survival']['wilson95'][0]:.1f}, {100*s[n+'/baseline']['survival']['wilson95'][1]:.1f}]" for n in N)+r'\\'+'\n'
 text+=r'\bottomrule\end{tabular}\end{table}'+'\n';(P/f'data/baseline-{lang}.tex').write_text(text)
 text=r'\begin{table}[tbp]\centering\small\setlength{\tabcolsep}{4pt}'+'\n'+r'\caption{'+(r'Парные различия при отключении модуляции: полная сеть минус абляция; среднее [95\% ДИ].' if ru else r'Paired modulation contrasts: intact minus ablated; mean [95\% CI].')+r'}\label{tab:controls}'+'\n'+r'\begin{tabular}{lcc}\toprule'+'\n'+('Сеть & Разность RMST, с & Разность пищи, порции' if ru else 'Controller & RMST difference, s & Food difference, portions')+r'\\\midrule'+'\n'
 for n,l in zip(N[1:],S[1:]):text+=l+' & '+value(c[n+'-ablation'],'duration')+' & '+value(c[n+'-ablation'],'food')+r'\\'+'\n'
 text+=r'\bottomrule\end{tabular}\end{table}'+'\n';(P/f'data/controls-{lang}.tex').write_text(text)
 text=r'\begin{table}[tbp]\centering\small\setlength{\tabcolsep}{4pt}'+'\n'+r'\caption{'+(r'Проверка затрат на нейроны: $\rho=0.001$; среднее [95\% ДИ].' if ru else r'Neuron-count fatigue sensitivity: $\rho=0.001$; mean [95\% CI].')+r'}\label{tab:cost}'+'\n'+r'\begin{tabular}{lccc}\toprule'+'\n'+('Сеть & RMST, с & Пища, порции & Дожили' if ru else 'Controller & RMST, s & Food, portions & Survived')+r'\\\midrule'+'\n'
 for n,l in zip(N,S):
  d=s[n+'/neural_cost'];text+=l+' & '+value(d,'duration')+' & '+value(d,'food')+' & '+str(d['survival']['count'])+r'/60\\'+'\n'
 text+=r'\bottomrule\end{tabular}\end{table}'+'\n';(P/f'data/cost-{lang}.tex').write_text(text)
print(mac)
