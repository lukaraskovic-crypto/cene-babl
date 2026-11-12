// product-page specifications → canonical keys used by the website's spec panel
window.specKV = html => { const d=new DOMParser().parseFromString(html,'text/html'); const out={};
  const add=(k,v)=>{ k=(k||'').replace(/\s+/g,' ').trim().replace(/:$/,''); v=(v||'').replace(/\s+/g,' ').trim(); if(k&&v&&k.length<60&&v.length<160&&!(k in out)) out[k]=v; };
  d.querySelectorAll('tr').forEach(tr=>{ const c=tr.querySelectorAll('th,td'); if(c.length===2) add(c[0].textContent,c[1].textContent); });
  d.querySelectorAll('dt').forEach(dt=>{ const dd=dt.nextElementSibling; if(dd&&dd.tagName==='DD') add(dt.textContent,dd.textContent); });
  d.querySelectorAll('li,p').forEach(li=>{ if(li.children.length<=3){ const m=li.textContent.match(/^\s*([^:\n]{2,50}):\s*([^\n]{1,140})$/); if(m) add(m[1],m[2]); } });
  if(Object.keys(out).length<6){   // marketplaces (Ananas): seller-written "Label: value" lines inside the page's JSON
    const txt=html.replace(/\\n/g,'\n').replace(/\\"|&#34;|&quot;/g,'″').replace(/<[^>]+>/g,'\n');
    for(const m of txt.matchAll(/^[ \t]*[•\-*]?[ \t]*([A-Za-zČĆŽŠĐčćžšđ][^:\n"{}]{1,48}):[ \t]*([^\n"{}]{1,140})$/gm)) add(m[1],m[2]); }
  return out; };
window.SPEC_MAP = [
  ['inch', /dijagonal|veli[čc]ina ekrana|veli[čc]ina displeja|ekran \(in|screen size/i, null],
  ['ram', /^(ram|radna memorija|ram memorija|ram \(memorija\)|memorija \(ram\)|kapacitet ram|instalirana memorija|koli[čc]ina ram)/i, null],
  ['sto', /^(ssd|hdd|interna memorija|kapacitet (ssd|diska|skladi)|skladi[šs]t|hard disk|memorija za skladi|ugra[dđ]ena memorija|kapacitet memorije)/i, null],
  ['hz', /osve[žz]avanj|refresh/i, null],
  ['res', /rezolucij/i, null],
  ['panel', /^(tip panela|tip ekrana|tip displeja|tehnologija ekrana|tehnologija displeja|panel|tip tv|tip televizora|tehnologija panela|tip osvetljenja)/i, null],
  ['cpu', /^(model procesora|procesor|cpu|tip procesora|serija procesora|[čc]ipset)/i, null],
  ['gpu', /^(grafi[čc]ka kart|tip grafi[čc]ke|model grafi[čc]ke|grafi[čc]ki [čc]ip|gpu|grafika)/i, /memorij/i],
  ['vram', /grafi[čc]ka memorija|memorija grafi[čc]ke|vram/i, null],
  ['kg', /kapacitet (pranja|su[šs]enja|punjenja)|kapacitet \(kg\)|maksimalno punjenje|kapacitet ve[šs]/i, null],
  ['rpm', /centrifug|obrtaj|brzina okretanja/i, null],
  ['lit', /^(ukupna zapremina|zapremina|ukupni neto kapacitet|neto zapremina|ukupna neto zapremina|bruto zapremina|kapacitet \(l\))/i, null],
  ['btu', /btu|kapacitet hla[dđ]enja/i, null],
  ['energy', /energetsk/i, /skal|ozna/i],
  ['net', /^(mre[žz]a|mre[žz]na podr[šs]ka|podr[žz]ane mre[žz]e|4g|5g|lte|sim|povezivanje|mobilna mre)/i, null]];
window.specFromKV = kv => { const o={}; const num=s=>{ const m=String(s).replace(/(\d)\.(\d{3})\b/g,'$1$2').match(/(\d+(?:[.,]\d+)?)/); return m?parseFloat(m[1].replace(',','.')):null; };
  for(const [label, v0] of Object.entries(kv)){ const v=String(v0);
    for(const [k, re, bad] of SPEC_MAP){ if(k in o || !re.test(label) || (bad && bad.test(label))) continue;
      let r=null;
      if(k==='inch'){ const m=v.match(/(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:"|''|”|″|in)/i); let n=m?parseFloat(m[1].replace(',','.')):null; if(n==null&&/cm/i.test(v)) n=Math.round(num(v)/2.54); else if(n==null) n=num(v); if(n>=5&&n<=120) r=n; }
      else if(k==='ram'||k==='vram'){ const m=v.match(/(\d{1,3})\s*GB/i); const n=m?+m[1]:num(v); if(n>=1&&n<=256) r=n; }
      else if(k==='sto'){ let b=0; for(const m of v.matchAll(/(\d{1,4}(?:[.,]\d)?)\s*(GB|TB)/gi)){ const g=parseFloat(m[1].replace(',','.'))*(m[2].toUpperCase()==='TB'?1024:1); if(g>=16&&g<=16384) b=Math.max(b,g);} r=b||null; }
      else if(k==='hz'){ const n=num(v); if(n>=50&&n<=600) r=n; }
      else if(k==='res'){ const v=v0.replace(/(\d)\.(\d{3})/g,'$1$2'); r=/7680|4320|\b8K\b/i.test(v)?'8K':/3840|2160|\b4K\b|UHD/i.test(v)?'4K UHD':/2560|1440|1600|QHD|2K\b/i.test(v)?'QHD':/1920|1080|1200|Full\s*HD|FHD/i.test(v)?'Full HD':/1366|1280|720|HD\s*Ready/i.test(v)?'HD':null; }
      else if(k==='panel'){ r=/QD-?OLED/i.test(v)?'QD-OLED':/\bOLED\b/i.test(v)?'OLED':/Neo\s*QLED/i.test(v)?'Neo QLED':/\bQLED\b/i.test(v)?'QLED':/Mini\s*-?LED/i.test(v)?'Mini LED':/Nano\s*Cell/i.test(v)?'NanoCell':/AMOLED/i.test(v)?'AMOLED':/\bIPS\b/i.test(v)?'IPS':/\bVA\b/.test(v)?'VA':/\bTN\b/.test(v)?'TN':/\bLED\b/i.test(v)?'LED':null; }
      else if(k==='cpu'){ let m=v.match(/Ultra\s*([579])\b/i); if(m) r='Intel Core Ultra '+m[1];
        else if((m=v.match(/\bi([3579])\b|\bi([3579])-\d/i))) r='Intel Core i'+(m[1]||m[2]);
        else if((m=v.match(/Core\s*([3579])\b/i))) r='Intel Core '+m[1];
        else if((m=v.match(/Ryzen\s*(?:AI\s*)?([3579])/i))) r='AMD Ryzen '+m[1];
        else if((m=v.match(/\bM([1-5])\s*(Pro|Max)?\b/))&&/apple|\bM[1-5]\b/i.test(v)) r='Apple M'+m[1]+(m[2]?' '+m[2]:'');
        else if((m=v.match(/Snapdragon\s*(X\s*(?:Elite|Plus)|8\s*(?:Gen\s*\d|Elite)|\d{3,4})/i))) r='Snapdragon '+m[1];
        else if((m=v.match(/(Celeron|Pentium|Athlon|Dimensity\s*\d{3,4}|Helio\s*\w+|Exynos\s*\d{3,4}|Tensor\s*G\d|A1[5-9]\s*(?:Pro|Bionic)?)/i))) r=m[1]; }
      else if(k==='gpu'){ const m=v.match(/\b(RTX|GTX)\s*-?\s*(PRO\s*)?(\d{3,4})\s*(Ti)?/i); if(m) r=`${m[1].toUpperCase()} ${m[2]?'PRO ':''}${m[3]}${m[4]?' Ti':''}`;
        else if(/Radeon\s*RX\s*\d{4}/i.test(v)) r='Radeon '+v.match(/RX\s*\d{4}\w*/i)[0].toUpperCase();
        const vm=v.match(/(\d{1,2})\s*GB/i); if(vm&&!('vram' in o)) o.vram=+vm[1]; }
      else if(k==='kg'){ const n=num(v); if(n>=1&&n<=30) r=n; }
      else if(k==='rpm'){ const n=num(v); if(n>=400&&n<=2000) r=n; }
      else if(k==='lit'){ const n=num(v); if(n>=5&&n<=1500) r=n; }
      else if(k==='btu'){ const n=num(v.replace(/\s/g,'')); if(n>=5000&&n<=60000) r=n; else if(n>=5&&n<=60&&/k/i.test(v)) r=n*1000; }
      else if(k==='energy'){ const m=v.match(/^\s*([A-G](?:\+{1,3})?)(?![a-z])/i); if(m) r=m[1].toUpperCase(); }
      else if(k==='net'){ r=/\b5G\b/.test(v)?'5G':/\b(LTE|4G)\b/i.test(v)?'LTE/4G':null; }
      if(r!=null) o[k]=r; } }
  return o; };
true;
