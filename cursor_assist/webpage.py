"""The single-page web UI (HTML + CSS + JS) served by :mod:`webserver`.

Self-contained: no external fonts, scripts, or styles, so it works fully offline.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cursor Assist</title>
<style>
  :root{
    --bg:#040406; --card:rgba(18,18,24,.55); --edge:rgba(255,255,255,.08);
    --edge2:rgba(255,255,255,.14); --fg:#eef0f6; --muted:#8b8b96;
    --field:#141419; --a1:#3aa0ff; --a2:#7b61ff; --on:#25c65a; --off:#e0503a;
    --accent:linear-gradient(135deg,var(--a1),var(--a2));
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{
    background:var(--bg); color:var(--fg);
    font:14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased; overflow-x:hidden; position:relative;
  }
  /* animated ambient blobs */
  .blob{position:fixed;border-radius:50%;filter:blur(90px);opacity:.5;z-index:-1;
    animation:drift 22s ease-in-out infinite}
  .b1{width:420px;height:420px;background:#1e5bff;top:-120px;left:-120px}
  .b2{width:380px;height:380px;background:#7b1fff;bottom:-140px;right:-120px;
    animation-delay:-7s}
  .b3{width:300px;height:300px;background:#00c2ff;top:40%;right:-140px;
    animation-delay:-13s;opacity:.35}
  @keyframes drift{0%,100%{transform:translate(0,0) scale(1)}
    33%{transform:translate(40px,50px) scale(1.12)}
    66%{transform:translate(-30px,20px) scale(.94)}}

  .wrap{max-width:440px;margin:0 auto;padding:20px 16px 40px}
  header{display:flex;align-items:center;justify-content:space-between;
    margin-bottom:16px}
  .brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:18px;
    letter-spacing:.2px}
  .brand .glyph{width:26px;height:26px;border-radius:8px;background:var(--accent);
    display:grid;place-items:center;font-size:14px;box-shadow:0 0 18px rgba(58,160,255,.5)}
  .pill{display:flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;
    background:var(--field);border:1px solid var(--edge);font-size:12px;color:var(--muted)}
  .dot{width:8px;height:8px;border-radius:50%;background:#555;transition:.3s}
  .dot.live{background:var(--on);box-shadow:0 0 10px var(--on);animation:pulse 1.4s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

  .power{width:100%;border:0;border-radius:16px;padding:16px;font-size:16px;
    font-weight:800;letter-spacing:.5px;color:#fff;cursor:pointer;margin-bottom:8px;
    background:linear-gradient(135deg,#7a241b,var(--off));transition:.25s;
    box-shadow:0 8px 26px rgba(224,80,58,.25)}
  .power.on{background:linear-gradient(135deg,#12813a,var(--on));
    box-shadow:0 8px 30px rgba(37,198,90,.4);animation:glow 1.8s ease-in-out infinite}
  @keyframes glow{0%,100%{box-shadow:0 8px 30px rgba(37,198,90,.35)}
    50%{box-shadow:0 8px 44px rgba(37,198,90,.65)}}
  .power:active{transform:scale(.985)}
  .msg{min-height:16px;font-size:12px;color:var(--muted);margin:2px 2px 14px;
    transition:.2s}

  .card{background:var(--card);border:1px solid var(--edge);border-radius:18px;
    padding:16px;margin-bottom:14px;backdrop-filter:blur(14px);
    -webkit-backdrop-filter:blur(14px);box-shadow:0 10px 34px rgba(0,0,0,.5);
    opacity:0;transform:translateY(10px);animation:rise .5s forwards;transition:border .25s}
  .card:hover{border-color:var(--edge2)}
  @keyframes rise{to{opacity:1;transform:none}}
  .card h2{margin:0 0 12px;font-size:11px;letter-spacing:1.4px;text-transform:uppercase;
    color:var(--muted);font-weight:700}

  .row{display:flex;align-items:center;gap:12px;margin:10px 0}
  .row label{flex:0 0 118px;color:var(--fg);font-size:13px}
  .row .val{flex:0 0 46px;text-align:right;font-variant-numeric:tabular-nums;
    color:#fff;font-weight:700}
  input[type=range]{-webkit-appearance:none;appearance:none;flex:1;height:6px;
    border-radius:999px;outline:0;cursor:pointer;
    background:linear-gradient(90deg,var(--a1) var(--p,50%),#26262e var(--p,50%))}
  input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;
    border-radius:50%;background:#fff;box-shadow:0 0 0 4px rgba(58,160,255,.18),0 0 10px var(--a1);
    transition:.15s}
  input[type=range]::-webkit-slider-thumb:hover{transform:scale(1.15)}
  input[type=range]::-moz-range-thumb{width:16px;height:16px;border:0;border-radius:50%;
    background:#fff;box-shadow:0 0 10px var(--a1)}

  .toggle{display:flex;align-items:center;justify-content:space-between;margin:10px 0}
  .switch{position:relative;width:44px;height:26px;flex:0 0 auto}
  .switch input{opacity:0;width:0;height:0}
  .track{position:absolute;inset:0;background:#2a2a32;border-radius:999px;transition:.25s}
  .track:before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;
    background:#fff;border-radius:50%;transition:.25s;box-shadow:0 2px 6px rgba(0,0,0,.4)}
  .switch input:checked + .track{background:var(--accent)}
  .switch input:checked + .track:before{transform:translateX(18px)}

  .btn{border:1px solid var(--edge);background:var(--field);color:var(--fg);
    padding:9px 14px;border-radius:11px;font-weight:600;font-size:13px;cursor:pointer;
    transition:.18s}
  .btn:hover{transform:translateY(-1px);border-color:var(--edge2)}
  .btn:active{transform:scale(.96)}
  .btn.accent{background:var(--accent);border:0;color:#04121f;font-weight:800;
    box-shadow:0 6px 18px rgba(58,160,255,.3)}
  .btns{display:flex;gap:8px;flex-wrap:wrap}

  .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .chip{padding:11px 0;text-align:center;border-radius:12px;background:var(--field);
    border:1px solid var(--edge);cursor:pointer;font-weight:700;font-size:13px;transition:.18s}
  .chip:hover{transform:translateY(-1px);border-color:var(--edge2)}
  .chip.sel{background:var(--accent);border:0;color:#04121f;
    box-shadow:0 6px 20px rgba(58,160,255,.45)}

  .swatches{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;min-height:38px}
  .sw{width:38px;height:38px;border-radius:11px;position:relative;cursor:pointer;
    border:1px solid rgba(255,255,255,.25);transition:.18s;overflow:hidden}
  .sw:hover{transform:scale(1.08)}
  .sw:after{content:"✕";position:absolute;inset:0;display:grid;place-items:center;
    color:#fff;font-size:13px;font-weight:800;background:rgba(0,0,0,.45);opacity:0;transition:.15s}
  .sw:hover:after{opacity:1}
  .empty{color:var(--muted);font-size:12px;align-self:center}

  .seg{display:flex;background:var(--field);border:1px solid var(--edge);
    border-radius:12px;padding:4px;gap:4px;margin-bottom:12px}
  .seg button{flex:1;border:0;background:transparent;color:var(--muted);padding:8px;
    border-radius:9px;font-weight:700;cursor:pointer;transition:.2s}
  .seg button.sel{background:var(--accent);color:#04121f;
    box-shadow:0 4px 14px rgba(58,160,255,.4)}

  .fields{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}
  .fields .lbl{color:var(--muted);font-size:12px}
  input.txt{width:60px;background:var(--field);border:1px solid var(--edge);color:var(--fg);
    border-radius:9px;padding:7px 8px;font:inherit;outline:0;transition:.18s}
  input.txt:focus{border-color:var(--a1);box-shadow:0 0 0 3px rgba(58,160,255,.15)}
  .hk{display:flex;align-items:center;gap:8px;margin:8px 0}
  .hk label{flex:0 0 84px;color:var(--muted);font-size:12px}
  .hk input{flex:1}
  .hint{color:var(--muted);font-size:11px;margin-top:2px}
  footer{display:flex;gap:8px;margin-top:6px}
  footer .btn.quit{margin-left:auto;color:#ff9a8a;border-color:rgba(224,80,58,.4)}
  ::-webkit-scrollbar{width:9px}::-webkit-scrollbar-thumb{background:#26262e;border-radius:9px}
</style>
</head>
<body>
<div class="blob b1"></div><div class="blob b2"></div><div class="blob b3"></div>
<div class="wrap">
  <header>
    <div class="brand"><span class="glyph">◎</span> Cursor Assist</div>
    <div class="pill"><span class="dot" id="dot"></span><span id="fps">—</span></div>
  </header>

  <button class="power" id="power" onclick="togglePull()">PULL: OFF</button>
  <div class="msg" id="msg">idle</div>

  <div class="card" style="animation-delay:.05s"><h2>Motion</h2>
    <div class="row"><label>Smoothness</label>
      <input type="range" data-key="smoothness" min="0" max="1" step="0.05">
      <span class="val"></span></div>
    <div class="row"><label>Max speed</label>
      <input type="range" data-key="max_speed" min="500" max="8000" step="100">
      <span class="val"></span></div>
    <div class="row"><label>Target steadiness</label>
      <input type="range" data-key="target_ema" min="0.05" max="0.9" step="0.05">
      <span class="val"></span></div>
  </div>

  <div class="card" style="animation-delay:.1s"><h2>Click</h2>
    <div class="toggle"><span>Auto dwell-click</span>
      <label class="switch"><input type="checkbox" data-key="auto_click_enabled">
      <span class="track"></span></label></div>
    <div class="row"><label>Dwell time</label>
      <input type="range" data-key="dwell_ms" min="200" max="1500" step="50">
      <span class="val"></span></div>
    <div class="row"><label>Click radius</label>
      <input type="range" data-key="click_radius" min="5" max="80" step="1">
      <span class="val"></span></div>
  </div>

  <div class="card" style="animation-delay:.15s"><h2>Target colors</h2>
    <div class="swatches" id="swatches"></div>
    <div class="btns" style="margin-bottom:10px">
      <input type="color" id="picker" style="width:0;height:0;opacity:0;position:absolute">
      <button class="btn accent" onclick="document.getElementById('picker').click()">＋ Pick</button>
      <button class="btn" onclick="eyedrop()" id="eyeBtn">⦿ Eyedropper</button>
      <button class="btn" onclick="act('clear_colors')">Clear</button>
    </div>
    <div class="row"><label>Sensitivity</label>
      <input type="range" data-key="sensitivity" min="2" max="45" step="1">
      <span class="val"></span></div>
    <div class="row"><label>Min area</label>
      <input type="range" data-key="min_contour_area" min="5" max="500" step="5">
      <span class="val"></span></div>
    <div class="toggle"><span>Detect thin outlines</span>
      <label class="switch"><input type="checkbox" data-key="detect_thin_border">
      <span class="track"></span></label></div>
  </div>

  <div class="card" style="animation-delay:.2s"><h2>Target region</h2>
    <div class="grid3" id="regions"></div>
  </div>

  <div class="card" style="animation-delay:.25s"><h2>Capture source</h2>
    <div class="seg" id="seg">
      <button data-src="obs">OBS cam</button>
      <button data-src="screen">Screen</button>
    </div>
    <div class="fields">
      <span class="lbl">Monitor</span><input class="txt" id="cap_monitor" style="width:48px">
      <span class="lbl">OBS idx</span><input class="txt" id="cap_obs" style="width:48px">
    </div>
    <div class="hint">Region L / T / W / H &nbsp; (0 0 0 0 = full monitor)</div>
    <div class="fields">
      <input class="txt" id="cap_left"><input class="txt" id="cap_top">
      <input class="txt" id="cap_width"><input class="txt" id="cap_height">
      <button class="btn accent" onclick="applyCapture()">Apply</button>
    </div>
    <div class="row"><label>Detail (speed)</label>
      <input type="range" data-key="detect_scale" min="0.25" max="1" step="0.05">
      <span class="val"></span></div>
  </div>

  <div class="card" style="animation-delay:.3s"><h2>Input control</h2>
    <div class="toggle"><span>Block my mouse while the bot is moving</span>
      <label class="switch"><input type="checkbox" data-key="suppress_mouse">
      <span class="track"></span></label></div>
  </div>

  <div class="card" style="animation-delay:.35s"><h2>Hotkeys</h2>
    <div class="hk"><label>Show panel</label><input class="txt" id="hk_show" style="width:auto">
      <button class="btn" onclick="record('show')">Record</button></div>
    <div class="hk"><label>Toggle pull</label><input class="txt" id="hk_pull" style="width:auto">
      <button class="btn" onclick="record('pull')">Record</button></div>
    <div class="btns" style="margin-top:8px;justify-content:flex-end">
      <button class="btn accent" onclick="applyHotkeys()">Apply hotkeys</button></div>
  </div>

  <footer>
    <button class="btn" onclick="act('reset_defaults').then(load)">Reset defaults</button>
    <button class="btn quit" onclick="quit()">Quit</button>
  </footer>
</div>

<script>
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let dragging=false, focused=null;

function fmt(v,step){return (parseFloat(step)<1)?parseFloat(v).toFixed(2):(''+Math.round(v));}
function setSlider(el,v){el.value=v;const min=+el.min,max=+el.max;
  el.style.setProperty('--p',((v-min)/(max-min)*100)+'%');
  el.closest('.row').querySelector('.val').textContent=fmt(v,el.step);}

async function post(url,body){return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body)}).then(r=>r.json());}
async function setKey(name,value){return post('/api/set',{name,value});}
async function act(a,extra={}){return post('/api/action',Object.assign({action:a},extra));}

function flash(t){$('#msg').textContent=t;}

// wire sliders
$$('input[type=range]').forEach(el=>{
  el.addEventListener('input',()=>{setSlider(el,el.value);dragging=true;});
  el.addEventListener('change',()=>{dragging=false;setKey(el.dataset.key,parseFloat(el.value));});
});
// wire toggles
$$('input[type=checkbox][data-key]').forEach(el=>{
  el.addEventListener('change',()=>setKey(el.dataset.key,el.checked));
});
// color picker
$('#picker').addEventListener('change',e=>act('add_color',{hex:e.target.value}).then(load));
// capture source segmented
$$('#seg button').forEach(b=>b.onclick=()=>act('set_source',{source:b.dataset.src}).then(load));
// remember focus so polling doesn't stomp typed text
$$('input.txt').forEach(el=>{el.addEventListener('focus',()=>focused=el);
  el.addEventListener('blur',()=>{if(focused===el)focused=null;});});

function togglePull(){act('toggle_pull').then(render);}
function eyedrop(){act('eyedrop');flash('Eyedropper armed — click any pixel on screen (Esc cancels)');}
function applyCapture(){act('apply_capture',{
  monitor:+$('#cap_monitor').value||0, obs_device_index:+$('#cap_obs').value||0,
  left:+$('#cap_left').value||0, top:+$('#cap_top').value||0,
  width:+$('#cap_width').value||0, height:+$('#cap_height').value||0}).then(()=>flash('capture applied'));}
function applyHotkeys(){act('apply_hotkeys',{show:$('#hk_show').value.trim(),pull:$('#hk_pull').value.trim()})
  .then(()=>flash('hotkeys applied'));}
async function record(which){flash('press a key or combo…');
  const r=await act('record_hotkey');
  if(r&&r.hotkey){(which==='show'?$('#hk_show'):$('#hk_pull')).value=r.hotkey;applyHotkeys();}
  else flash("recording needs the 'keyboard' package");}
function quit(){act('quit');flash('quitting — you can close this tab');}

let S={};
function renderColors(){
  const box=$('#swatches');box.innerHTML='';
  if(!S.colors||!S.colors.length){box.innerHTML='<span class="empty">no colors — add one</span>';return;}
  S.colors.forEach((hex,i)=>{const d=document.createElement('div');d.className='sw';
    d.style.background=hex;d.title=hex+' (click to remove)';
    d.onclick=()=>act('remove_color',{index:i}).then(load);box.appendChild(d);});
}
function renderRegions(){
  const box=$('#regions');
  if(box.childElementCount!==(S.regions||[]).length){box.innerHTML='';
    (S.regions||[]).forEach(r=>{const b=document.createElement('div');b.className='chip';
      b.textContent=r;b.dataset.r=r;b.onclick=()=>act('set_region',{region:r}).then(render);box.appendChild(b);});}
  $$('#regions .chip').forEach(c=>c.classList.toggle('sel',c.dataset.r===S.active_region));
}
function render(){
  // status
  $('#fps').textContent=(S.target_found?'● ':'')+ (S.fps||0)+' fps';
  $('#dot').classList.toggle('live',!!S.target_found);
  const on=!!S.pull_enabled, p=$('#power');
  p.textContent='PULL: '+(on?'ON':'OFF');p.classList.toggle('on',on);
  if(!dragging&&S.error){/*keep*/}
  // segmented + region
  $$('#seg button').forEach(b=>b.classList.toggle('sel',b.dataset.src===(S.capture||{}).source));
  renderRegions();renderColors();
  if(S.eyedropping) flash('Eyedropper armed — click any pixel on screen (Esc cancels)');
}
function fillStatic(){
  $$('input[type=range]').forEach(el=>{if(el.dataset.key in S)setSlider(el,S[el.dataset.key]);});
  $$('input[type=checkbox][data-key]').forEach(el=>{if(el.dataset.key in S)el.checked=!!S[el.dataset.key];});
  const c=S.capture||{};
  const set=(id,v)=>{const e=$(id);if(e&&focused!==e)e.value=v;};
  set('#cap_monitor',c.monitor);set('#cap_obs',c.obs_device_index);
  set('#cap_left',c.left);set('#cap_top',c.top);set('#cap_width',c.width);set('#cap_height',c.height);
  set('#hk_show',S.hotkey_show_panel);set('#hk_pull',S.hotkey_toggle_pull);
}
async function load(){S=await fetch('/api/state').then(r=>r.json());fillStatic();render();}
async function poll(){try{S=await fetch('/api/state').then(r=>r.json());
  if(!dragging)fillStaticStatusOnly();render();}catch(e){}}
function fillStaticStatusOnly(){ // refresh only fields the user isn't editing
  const c=S.capture||{};const set=(id,v)=>{const e=$(id);if(e&&focused!==e&&document.activeElement!==e)e.value=v;};
  set('#hk_show',S.hotkey_show_panel);set('#hk_pull',S.hotkey_toggle_pull);
}
load();setInterval(poll,300);
</script>
</body>
</html>
"""
