// node i18n/validate.js <code>  – checks i18n/<code>.js and i18n/<code>.json against the English source
const fs=require('fs'), path=require('path'), D=__dirname;
const load=f=>{ const g={}; new Function('window','I18N',fs.readFileSync(f,'utf8').replace(/^window\.I18N=window\.I18N\|\|\{\};?/,''))(g,g.I18N=g.I18N||{}); return g; };
eval(fs.readFileSync(path.join(D,'src/ui_en.js'),'utf8').replace('UI_EN=','globalThis.UI_EN='));
eval(fs.readFileSync(path.join(D,'src/acc_en.js'),'utf8').replace('ACC_EN=','globalThis.ACC_EN='));
const EN=JSON.parse(fs.readFileSync(path.join(D,'en.json'),'utf8'));
const SKIP=new Set(['adm','G','reportS','watch','report','admin']);
let bad=0; const err=m=>{ bad++; console.log('  ✗',m); };
const SAMPLE=[3,7,'12%','45.000','Gigatron','x@y.rs',5];
function cmp(a,b,p,top){ for(const k of Object.keys(a)){ if(top&&SKIP.has(k)) continue; const pk=p+k; if(!(k in b)){ err('missing '+pk); continue; }
  const x=a[k], y=b[k];
  if(typeof x==='function'){ if(typeof y!=='function'){ err('not a function '+pk); continue; } if(y.length!==x.length) err(`arity ${pk}: ${y.length} vs ${x.length}`);
    try{ const r=y(...SAMPLE.slice(0,x.length)); if(typeof r!=='string'||!r.trim()) err('empty result '+pk); const ex=x(...SAMPLE.slice(0,x.length)); for(const s of SAMPLE.slice(0,x.length)) if(String(ex).includes(String(s))&&!String(r).includes(String(s))) err(`${pk} drops argument ${s}`); }catch(e){ err('throws '+pk+': '+e.message); } }
  else if(x&&typeof x==='object') { if(!y||typeof y!=='object') err('not an object '+pk); else cmp(x,y,pk+'.'); }
  else if(typeof y!=='string'||!y.trim()) err('empty '+pk);
  else { const tags=s=>(String(s).match(/<[^>]+>/g)||[]).map(t=>t.replace(/\s.*$/,'')).sort().join(); if(tags(x)!==tags(y)) err('html tags differ '+pk); } } }
function cmpJ(a,b,p){ for(const k of Object.keys(a)){ const pk=p+k; if(!(k in b)){ err('missing '+pk); continue; }
  if(Array.isArray(a[k])){ if(!Array.isArray(b[k])||b[k].length!==a[k].length) err('array length '+pk); else a[k].forEach((v,i)=>cmpJ({v},{v:b[k][i]},pk+'['+i+'].')); continue; }
  if(a[k]&&typeof a[k]==='object'){ cmpJ(a[k],b[k]||{},pk+'.'); continue; }
  const ph=s=>(String(s).match(/\{\w+\}/g)||[]).sort().join(); if(ph(a[k])!==ph(b[k])) err(`placeholders ${pk}: [${ph(b[k])}] vs [${ph(a[k])}]`);
  const tags=s=>(String(s).match(/<[^>]+>/g)||[]).map(t=>t.replace(/\s.*$/,'')).sort().join(); if(tags(a[k])!==tags(b[k])) err('html tags differ '+pk);
  if(typeof b[k]!=='string'||!String(b[k]).trim()) { if(!(k==='auto')) err('empty '+pk); } } }
for(const code of process.argv.slice(2)){ bad=0; console.log(code);
  try{ const g=load(path.join(D,code+'.js')); const P=g.I18N[code]; if(!P) { err('I18N["'+code+'"] not set'); continue; }
    if(!Array.isArray(P.months)||P.months.length!==12) err('months must be 12');
    cmp(UI_EN,P.ui||{},'ui.',true); cmp(ACC_EN,P.acc||{},'acc.');
    if(!P.ui?.x?.auto) err('ui.x.auto (automatic-translation note) missing'); }
  catch(e){ err('js: '+e.message); }
  try{ const J=JSON.parse(fs.readFileSync(path.join(D,code+'.json'),'utf8')); cmpJ(EN,J,''); if(!J.seo?.auto) err('seo.auto note missing'); }
  catch(e){ err('json: '+e.message); }
  console.log(bad?`  ${bad} problem(s)`:'  OK'); }
