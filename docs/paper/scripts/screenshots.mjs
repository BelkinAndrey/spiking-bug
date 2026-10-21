import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const paperPath=relative=>fileURLToPath(new URL('../'+relative,import.meta.url));
const api='http://127.0.0.1:8011';
async function command(action,data){const state=await fetch(api+'/api/state').then(r=>r.json());const r=await fetch(api+'/api/command',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,data,revision:state.revision})});if(!r.ok)throw new Error(await r.text());return r.json();}
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1600,height:1000},deviceScaleFactor:1.5});
const page=await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(String(e)));
for(const lang of ['en','ru']){
 for(const name of ['direct','modulation','ganglia-populatio']){
  const project=JSON.parse(await fs.readFile(paperPath('inputs/'+name+'.json'),'utf8'));
  await command('import',project);
  await page.goto('http://127.0.0.1:5184/?lang='+lang);await page.locator('#fit').waitFor();await page.waitForTimeout(700);await page.locator('#fit').click();await page.waitForTimeout(300);
  await page.screenshot({path:paperPath(`figures/editor-${name}-${lang}.png`)});
  if(name==='ganglia-populatio'){
   await page.goto('http://127.0.0.1:5183/?lang='+lang);await page.locator('#fit').waitFor();await page.waitForTimeout(700);await page.locator('#fit').click();await page.waitForTimeout(300);
   await page.screenshot({path:paperPath(`figures/environment-${lang}.png`)});
  }
 }
}
await fs.writeFile(paperPath('data/screenshot-capture.json'),JSON.stringify({date:'2026-10-21',viewport:{width:1600,height:1000},deviceScaleFactor:1.5,project:'original JSON snapshot; paused at t=0; seed=42; not randomized trial',pageErrors:errors},null,2));
await browser.close();console.log('Captured 8 screenshots; errors:',errors);
