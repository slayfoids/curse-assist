"""The single-page web UI (HTML + CSS + JS) served by :mod:`webserver`.

Self-contained: no external fonts, scripts, or styles, so it works fully
offline. Full-width dark "glass" dashboard: layered translucent cards over an
animated aurora background, gradient borders, noise texture, and hover depth.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cursor Assist</title>
<style>
  :root{
    --bg:#05060a; --fg:#eef1f8; --muted:#8f93a3; --muted2:#6b6f7e;
    --card:rgba(17,19,28,.52); --card-hi:rgba(24,27,40,.62);
    --field:rgba(10,12,18,.65); --edge:rgba(255,255,255,.07);
    --edge2:rgba(255,255,255,.16);
    --a1:#3aa0ff; --a2:#7b61ff; --a3:#00d4ff;
    --on:#2ee06a; --off:#ff5c49;
    --accent:linear-gradient(135deg,var(--a1),var(--a2));
    --radius:20px;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  html,body{margin:0;min-height:100%}
  body{
    background:var(--bg); color:var(--fg);
    font:14px/1.45 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
    -webkit-font-smoothing:antialiased; overflow-x:hidden; position:relative;
  }

  /* ---------- ambient background: gradient mesh + aurora + grid + noise --- */
  .bg{position:fixed;inset:0;z-index:-3;overflow:hidden;
    background:
      radial-gradient(1100px 700px at 12% -10%,rgba(30,91,255,.16),transparent 60%),
      radial-gradient(900px 640px at 105% 15%,rgba(123,31,255,.14),transparent 60%),
      radial-gradient(800px 700px at 50% 115%,rgba(0,194,255,.10),transparent 60%),
      var(--bg)}
  .blob{position:absolute;border-radius:50%;filter:blur(110px);opacity:.45;
    animation:drift 26s ease-in-out infinite}
  .b1{width:520px;height:520px;background:#1e5bff;top:-160px;left:-140px}
  .b2{width:460px;height:460px;background:#7b1fff;bottom:-180px;right:-140px;animation-delay:-9s}
  .b3{width:380px;height:380px;background:#00c2ff;top:35%;right:-160px;animation-delay:-15s;opacity:.3}
  .b4{width:340px;height:340px;background:#1444ff;top:55%;left:-140px;animation-delay:-20s;opacity:.3}
  @keyframes drift{0%,100%{transform:translate(0,0) scale(1)}
    33%{transform:translate(60px,70px) scale(1.14)}
    66%{transform:translate(-40px,30px) scale(.92)}}
  .grid-lines{position:fixed;inset:0;z-index:-2;pointer-events:none;opacity:.5;
    background:
      linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),
      linear-gradient(90deg,rgba(255,255,255,.022) 1px,transparent 1px);
    background-size:44px 44px;
    -webkit-mask-image:radial-gradient(1200px 800px at 50% 0%,#000 30%,transparent 85%);
            mask-image:radial-gradient(1200px 800px at 50% 0%,#000 30%,transparent 85%)}
  .noise{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.05;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>")}

  /* ------------------------------------------------------------- top bar --- */
  .topbar{position:sticky;top:0;z-index:50;
    backdrop-filter:blur(22px) saturate(150%);-webkit-backdrop-filter:blur(22px) saturate(150%);
    background:linear-gradient(180deg,rgba(10,12,20,.78),rgba(10,12,20,.55));
    border-bottom:1px solid var(--edge)}
  .topbar-inner{max-width:1520px;margin:0 auto;padding:14px 28px;
    display:flex;align-items:center;gap:18px}
  .brand{display:flex;align-items:center;gap:12px;font-weight:700;font-size:17px;letter-spacing:.2px}
  .glyph{width:34px;height:34px;border-radius:10px;background:var(--accent);
    display:grid;place-items:center;font-size:17px;color:#fff;
    box-shadow:0 0 22px rgba(58,160,255,.55),inset 0 0 12px rgba(255,255,255,.25)}
  .brand small{display:block;font-weight:500;font-size:11px;color:var(--muted);letter-spacing:.6px}
  .top-status{display:flex;gap:10px;margin-left:auto;align-items:center}
  .pill{display:flex;align-items:center;gap:8px;padding:7px 14px;border-radius:999px;
    background:var(--field);border:1px solid var(--edge);font-size:12px;color:var(--muted);
    font-variant-numeric:tabular-nums;transition:.25s}
  .pill b{color:var(--fg);font-weight:600}
  .dot{width:8px;height:8px;border-radius:50%;background:#4a4e5c;transition:.3s}
  .dot.live{background:var(--on);box-shadow:0 0 12px var(--on);animation:pulse 1.4s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

  /* ---------------------------------------------------------------- layout - */
  .wrap{max-width:1520px;margin:0 auto;padding:26px 28px 60px}
  .section{grid-column:1/-1;display:flex;align-items:center;gap:14px;
    margin:26px 0 2px;opacity:0;animation:rise .55s .1s forwards}
  .section:first-child{margin-top:0}
  .section .tag{font-size:11px;font-weight:800;letter-spacing:2.6px;text-transform:uppercase;
    background:linear-gradient(90deg,var(--a3),var(--a1),var(--a2));
    -webkit-background-clip:text;background-clip:text;color:transparent;white-space:nowrap}
  .section .rule{flex:1;height:1px;
    background:linear-gradient(90deg,rgba(58,160,255,.45),rgba(255,255,255,.06) 45%,transparent)}
  .grid{display:grid;grid-template-columns:repeat(12,1fr);gap:18px}
  .s12{grid-column:span 12}.s8{grid-column:span 8}.s6{grid-column:span 6}
  .s4{grid-column:span 4}.s3{grid-column:span 3}
  @media(max-width:1120px){.s4,.s3{grid-column:span 6}.s8{grid-column:span 12}}
  @media(max-width:760px){.s6,.s4,.s3{grid-column:span 12}
    .wrap{padding:18px 14px 50px}.topbar-inner{padding:12px 14px}}

  /* ----------------------------------------------------------------- cards - */
  .card{position:relative;border-radius:var(--radius);padding:20px 20px 16px;
    border:1px solid transparent;overflow:hidden;
    background:
      linear-gradient(var(--card),var(--card)) padding-box,
      linear-gradient(155deg,rgba(255,255,255,.18),rgba(255,255,255,.04) 38%,rgba(58,160,255,.22) 100%) border-box;
    backdrop-filter:blur(20px) saturate(150%);-webkit-backdrop-filter:blur(20px) saturate(150%);
    box-shadow:0 14px 40px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.05);
    opacity:0;transform:translateY(14px);animation:rise .55s forwards;
    transition:transform .28s cubic-bezier(.2,.8,.2,1),box-shadow .28s,background .28s}
  .card:hover{transform:translateY(-4px);
    background:
      linear-gradient(var(--card-hi),var(--card-hi)) padding-box,
      linear-gradient(155deg,rgba(255,255,255,.28),rgba(255,255,255,.07) 38%,rgba(123,97,255,.4) 100%) border-box;
    box-shadow:0 22px 60px rgba(0,0,0,.55),0 0 0 1px rgba(58,160,255,.08),
      0 0 44px rgba(58,160,255,.10),inset 0 1px 0 rgba(255,255,255,.08)}
  .card::before{content:"";position:absolute;inset:0;pointer-events:none;
    background:linear-gradient(115deg,transparent 35%,rgba(255,255,255,.055) 48%,transparent 62%);
    transform:translateX(-130%);transition:transform .9s ease}
  .card:hover::before{transform:translateX(130%)}
  @keyframes rise{to{opacity:1;transform:none}}
  .card h2{margin:0 0 14px;font-size:11px;letter-spacing:1.6px;text-transform:uppercase;
    color:var(--muted);font-weight:700;display:flex;align-items:center;gap:9px}
  .card h2 .ico{width:24px;height:24px;border-radius:8px;display:grid;place-items:center;
    font-size:12px;color:#cfe4ff;background:rgba(58,160,255,.12);
    border:1px solid rgba(58,160,255,.25);box-shadow:inset 0 0 10px rgba(58,160,255,.12)}

  /* ------------------------------------------------------------------ hero - */
  .hero{display:flex;align-items:center;gap:26px;flex-wrap:wrap;padding:24px 26px}
  .power{position:relative;border:0;border-radius:18px;padding:20px 44px;font-size:17px;
    font-weight:800;letter-spacing:1.2px;color:#fff;cursor:pointer;
    background:linear-gradient(135deg,#7a241b,var(--off));
    box-shadow:0 10px 30px rgba(224,80,58,.28),inset 0 1px 0 rgba(255,255,255,.22);
    transition:.28s;z-index:1}
  .power:hover{transform:translateY(-2px)}
  .power:active{transform:scale(.97)}
  .power.on{background:linear-gradient(135deg,#0f8c3c,var(--on));
    box-shadow:0 10px 34px rgba(37,198,90,.42),inset 0 1px 0 rgba(255,255,255,.25);
    animation:glow 1.9s ease-in-out infinite}
  .power.on::after{content:"";position:absolute;inset:-5px;border-radius:22px;z-index:-1;
    background:conic-gradient(from 0deg,#2ee06a,#3aa0ff,#7b61ff,#2ee06a);
    filter:blur(14px);opacity:.55;animation:hue 4s linear infinite}
  @keyframes hue{to{filter:blur(14px) hue-rotate(360deg)}}
  @keyframes glow{0%,100%{box-shadow:0 10px 30px rgba(37,198,90,.35)}
    50%{box-shadow:0 12px 48px rgba(37,198,90,.65)}}
  .hero-info{flex:1;min-width:220px}
  .hero-info .title{font-size:15px;font-weight:700;margin-bottom:4px}
  .msg{font-size:12.5px;color:var(--muted);min-height:16px;transition:.2s}
  .stats{display:flex;gap:12px;flex-wrap:wrap}
  .stat{min-width:118px;padding:12px 16px;border-radius:14px;background:var(--field);
    border:1px solid var(--edge);transition:.25s}
  .stat:hover{border-color:var(--edge2);transform:translateY(-2px)}
  .stat .k{font-size:10px;letter-spacing:1.6px;color:var(--muted2);text-transform:uppercase;font-weight:700}
  .stat .v{font-size:19px;font-weight:750;margin-top:3px;font-variant-numeric:tabular-nums}
  .stat .v.ok{color:var(--on);text-shadow:0 0 14px rgba(46,224,106,.5)}
  .stat .v.bad{color:var(--muted)}

  /* --------------------------------------------------------------- controls - */
  .row{display:flex;align-items:center;gap:12px;margin:11px 0}
  .row label{flex:0 0 128px;color:var(--fg);font-size:13px}
  .row .val{flex:0 0 52px;text-align:right;font-variant-numeric:tabular-nums;
    color:#fff;font-weight:700;font-size:13px}
  input[type=range]{-webkit-appearance:none;appearance:none;flex:1;height:6px;
    border-radius:999px;outline:0;cursor:pointer;
    background:linear-gradient(90deg,var(--a1),var(--a2) var(--p,50%),rgba(255,255,255,.09) var(--p,50%))}
  input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:17px;height:17px;
    border-radius:50%;background:#fff;cursor:grab;
    box-shadow:0 0 0 4px rgba(58,160,255,.2),0 0 14px rgba(58,160,255,.75),0 2px 6px rgba(0,0,0,.5);
    transition:transform .15s,box-shadow .15s}
  input[type=range]::-webkit-slider-thumb:hover{transform:scale(1.22);
    box-shadow:0 0 0 6px rgba(58,160,255,.22),0 0 20px rgba(58,160,255,.9)}
  input[type=range]::-webkit-slider-thumb:active{cursor:grabbing}
  input[type=range]::-moz-range-thumb{width:17px;height:17px;border:0;border-radius:50%;
    background:#fff;box-shadow:0 0 12px var(--a1)}

  .toggle{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:11px 0}
  .toggle > span{font-size:13px}
  .toggle small{color:var(--muted);font-size:11px}
  .switch{position:relative;width:46px;height:26px;flex:0 0 auto}
  .switch input{opacity:0;width:0;height:0}
  .track{position:absolute;inset:0;background:rgba(255,255,255,.09);border-radius:999px;
    transition:.28s;border:1px solid var(--edge)}
  .track:before{content:"";position:absolute;width:20px;height:20px;left:2px;top:2px;
    background:#fff;border-radius:50%;transition:.28s cubic-bezier(.2,.8,.2,1);
    box-shadow:0 2px 8px rgba(0,0,0,.5)}
  .switch input:checked + .track{background:var(--accent);border-color:transparent;
    box-shadow:0 0 16px rgba(58,160,255,.4)}
  .switch input:checked + .track:before{transform:translateX(20px)}
  .switch:hover .track{border-color:var(--edge2)}

  .btn{border:1px solid var(--edge);background:var(--field);color:var(--fg);
    padding:9px 15px;border-radius:12px;font-weight:600;font-size:13px;cursor:pointer;
    transition:.2s;backdrop-filter:blur(8px)}
  .btn:hover{transform:translateY(-2px);border-color:var(--edge2);
    box-shadow:0 8px 20px rgba(0,0,0,.35)}
  .btn:active{transform:scale(.96)}
  .btn.accent{background:var(--accent);border:0;color:#fff;font-weight:750;
    box-shadow:0 6px 20px rgba(58,160,255,.35)}
  .btn.accent:hover{box-shadow:0 10px 28px rgba(58,160,255,.5)}
  .btns{display:flex;gap:8px;flex-wrap:wrap}

  .gridchips{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .chip{padding:11px 0;text-align:center;border-radius:12px;background:var(--field);
    border:1px solid var(--edge);cursor:pointer;font-weight:700;font-size:13px;transition:.2s}
  .chip:hover{transform:translateY(-2px);border-color:var(--edge2)}
  .chip.sel{background:var(--accent);border-color:transparent;color:#fff;
    box-shadow:0 6px 22px rgba(58,160,255,.45)}

  .swatches{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:12px;min-height:40px}
  .sw{width:40px;height:40px;border-radius:12px;position:relative;cursor:pointer;
    border:1px solid rgba(255,255,255,.3);transition:.2s;overflow:hidden;
    box-shadow:0 4px 14px rgba(0,0,0,.4)}
  .sw:hover{transform:scale(1.12) rotate(-3deg)}
  .sw:after{content:"✕";position:absolute;inset:0;display:grid;place-items:center;
    color:#fff;font-size:13px;font-weight:800;background:rgba(0,0,0,.5);opacity:0;transition:.15s}
  .sw:hover:after{opacity:1}
  .empty{color:var(--muted);font-size:12px;align-self:center}

  .seg{display:flex;background:var(--field);border:1px solid var(--edge);
    border-radius:13px;padding:4px;gap:4px;margin-bottom:12px}
  .seg button{flex:1;border:0;background:transparent;color:var(--muted);padding:9px;
    border-radius:10px;font-weight:700;cursor:pointer;transition:.22s;font-size:13px}
  .seg button:hover{color:var(--fg)}
  .seg button.sel{background:var(--accent);color:#fff;
    box-shadow:0 4px 16px rgba(58,160,255,.4)}

  .fields{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
  .fields .lbl{color:var(--muted);font-size:12px}
  input.txt{width:64px;background:var(--field);border:1px solid var(--edge);color:var(--fg);
    border-radius:10px;padding:8px 9px;font:inherit;outline:0;transition:.2s}
  input.txt:focus{border-color:var(--a1);box-shadow:0 0 0 3px rgba(58,160,255,.18)}
  input.txt:hover{border-color:var(--edge2)}
  .hk{display:flex;align-items:center;gap:8px;margin:9px 0}
  .hk label{flex:0 0 88px;color:var(--muted);font-size:12px}
  .hk input{flex:1}
  .hint{color:var(--muted2);font-size:11.5px;margin-top:3px;line-height:1.5}
  .kbd{display:inline-block;padding:1px 7px;border-radius:6px;background:rgba(255,255,255,.07);
    border:1px solid var(--edge);font-size:11px;font-weight:600;color:var(--fg)}

  footer{display:flex;gap:10px;margin-top:30px;align-items:center}
  footer .note{color:var(--muted2);font-size:12px}
  footer .btn.quit{margin-left:auto;color:#ff9a8a;border-color:rgba(224,80,58,.4)}
  footer .btn.quit:hover{background:rgba(224,80,58,.12);box-shadow:0 8px 22px rgba(224,80,58,.25)}
  ::-webkit-scrollbar{width:10px}
  ::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1);border-radius:10px;
    border:2px solid transparent;background-clip:padding-box}
  ::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.18);background-clip:padding-box}
  ::selection{background:rgba(58,160,255,.35)}
  @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}
    .card,.section{opacity:1;transform:none}}
</style>
</head>
<body>
<div class="bg">
  <div class="blob b1"></div><div class="blob b2"></div>
  <div class="blob b3"></div><div class="blob b4"></div>
</div>
<div class="grid-lines"></div><div class="noise"></div>

<div class="topbar"><div class="topbar-inner">
  <div class="brand"><span class="glyph">◎</span>
    <span>Cursor Assist<small>color-guided pointer accessibility</small></span></div>
  <div class="top-status">
    <div class="pill"><span class="dot" id="dot"></span><b id="fps">—</b></div>
  </div>
</div></div>

<div class="wrap">
<div class="grid">

  <div class="card hero s12" style="animation-delay:.03s">
    <button class="power" id="power" onclick="togglePull()">PULL&nbsp;OFF</button>
    <div class="hero-info">
      <div class="title">Guidance engine</div>
      <div class="msg" id="msg">idle</div>
    </div>
    <div class="stats">
      <div class="stat"><div class="k">Detection</div><div class="v" id="statFps">— fps</div></div>
      <div class="stat"><div class="k">Target</div><div class="v bad" id="statTarget">none</div></div>
      <div class="stat"><div class="k">Click mode</div><div class="v" id="statMode">—</div></div>
    </div>
  </div>

  <div class="section"><span class="tag">Guidance &amp; Motion</span><span class="rule"></span></div>

  <div class="card s4" style="animation-delay:.06s"><h2><span class="ico">〜</span>Motion</h2>
    <div class="row"><label>Smoothness</label>
      <input type="range" data-key="smoothness" min="0" max="1" step="0.05">
      <span class="val"></span></div>
    <div class="row"><label>Max speed</label>
      <input type="range" data-key="max_speed" min="500" max="100000" step="500">
      <span class="val"></span></div>
    <div class="row"><label>Target steadiness</label>
      <input type="range" data-key="target_ema" min="0.05" max="0.9" step="0.05">
      <span class="val"></span></div>
    <div class="hint">Motion is time-based and frame-rate independent — these tune
      feel, not speed of detection.</div>
  </div>

  <div class="card s4" style="animation-delay:.09s"><h2><span class="ico">⌖</span>Targeting</h2>
    <div class="toggle"><span>Lock onto one target<br><small>hold it until it's gone</small></span>
      <label class="switch"><input type="checkbox" data-key="lock_target">
      <span class="track"></span></label></div>
    <div class="toggle"><span>Best-coverage snap<br><small>after resting on the color</small></span>
      <label class="switch"><input type="checkbox" data-key="snap_to_best">
      <span class="track"></span></label></div>
    <div class="row" id="snapRow"><label>Snap after (ms)</label>
      <input type="range" data-key="snap_after_ms" min="200" max="3000" step="100">
      <span class="val"></span></div>
    <div class="hint">Lock stops the pointer drifting between several same-color
      targets. Snap re-aims to where the circle covers the most color.</div>
  </div>

  <div class="card s4" style="animation-delay:.12s"><h2><span class="ico">◎</span>Field of view</h2>
    <div class="toggle"><span>Show crosshair circle</span>
      <label class="switch"><input type="checkbox" data-key="show_overlay">
      <span class="track"></span></label></div>
    <div class="row"><label>Pull radius</label>
      <input type="range" data-key="pull_radius" min="0" max="1000" step="10">
      <span class="val"></span></div>
    <div class="row"><label>Circle size</label>
      <input type="range" data-key="overlay_radius" min="0" max="1000" step="10">
      <span class="val"></span></div>
    <div class="hint">Only assist toward colors within the pull radius of the
      cursor (0 = whole screen). Circle size is the drawn circle (0 = match
      pull radius); it also sets the best-coverage snap circle.</div>
  </div>

  <div class="section"><span class="tag">Clicking</span><span class="rule"></span></div>

  <div class="card s6" style="animation-delay:.15s"><h2><span class="ico">✦</span>Click</h2>
    <div class="seg" id="clickmode">
      <button data-mode="dwell">Dwell</button>
      <button data-mode="trigger">Trigger key</button>
      <button data-mode="off">Off</button>
    </div>
    <div class="row" id="dwellRow"><label>Dwell time</label>
      <input type="range" data-key="dwell_ms" min="50" max="1500" step="25">
      <span class="val"></span></div>
    <div class="row"><label>Click radius</label>
      <input type="range" data-key="click_radius" min="5" max="80" step="1">
      <span class="val"></span></div>
    <div class="toggle" id="repeatRow"><span>Repeat clicks<br><small>auto-fire while on target</small></span>
      <label class="switch"><input type="checkbox" data-key="click_repeat">
      <span class="track"></span></label></div>
    <div class="row" id="intervalRow"><label>Click interval (ms)</label>
      <input type="range" data-key="click_interval_ms" min="30" max="1000" step="10">
      <span class="val"></span></div>
    <div id="triggerRow">
      <div class="hk"><label>Click key/button</label>
        <input class="txt" id="hk_trigger" style="width:auto">
        <button class="btn" onclick="record('trigger')">Record</button></div>
      <div class="btns" style="margin-top:6px">
        <button class="btn" onclick="setTrigger('RMB')">RMB</button>
        <button class="btn" onclick="setTrigger('MMB')">MMB</button>
        <button class="btn" onclick="setTrigger('MB4')">Mouse4</button>
        <button class="btn" onclick="setTrigger('MB5')">Mouse5</button>
        <button class="btn" onclick="setTrigger('LMB')">LMB</button>
        <button class="btn" onclick="setTrigger('right ctrl')">R-Ctrl</button>
        <button class="btn" onclick="setTrigger('space')">Space</button>
      </div>
      <div class="hint">Quick-pick a key or mouse button — no need to Record.
        (RMB may also open the right-click menu.)</div>
    </div>
    <div class="hint" id="clickHint"></div>
  </div>

  <div class="card s6" style="animation-delay:.18s"><h2><span class="ico">⛨</span>Input control</h2>
    <div class="toggle"><span>Block my mouse while the bot is moving<br>
      <small>steadies a shaky hand so it doesn't fight the assist</small></span>
      <label class="switch"><input type="checkbox" data-key="suppress_mouse">
      <span class="track"></span></label></div>
    <div class="hint">Uses a low-level Windows mouse hook while a pull is active;
      clicks always pass through. Turn guidance off (<span class="kbd">F8</span>
      by default) to take back full control instantly.</div>
  </div>

  <div class="section"><span class="tag">Detection</span><span class="rule"></span></div>

  <div class="card s4" style="animation-delay:.21s"><h2><span class="ico">🎨</span>Target colors</h2>
    <div class="swatches" id="swatches"></div>
    <div class="btns" style="margin-bottom:12px">
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

  <div class="card s4" style="animation-delay:.24s"><h2><span class="ico">☰</span>Target region</h2>
    <div class="toggle"><span>Body-part detection<br><small>off = track the color directly</small></span>
      <label class="switch"><input type="checkbox" data-key="body_part_detection">
      <span class="track"></span></label></div>
    <div class="gridchips" id="regions" style="margin-top:10px"></div>
    <div class="hint" id="regionHint"></div>
  </div>

  <div class="card s4" style="animation-delay:.27s"><h2><span class="ico">▣</span>Detection area</h2>
    <div class="hint" style="margin-bottom:6px">Only look for colors inside this
      pixel box. X / Y / W / H — 0&nbsp;0&nbsp;0&nbsp;0 = whole frame.</div>
    <div class="fields">
      <input class="txt" id="roi_x" placeholder="X"><input class="txt" id="roi_y" placeholder="Y">
      <input class="txt" id="roi_w" placeholder="W"><input class="txt" id="roi_h" placeholder="H">
    </div>
    <div class="btns">
      <button class="btn accent" onclick="applyRoi()">Apply</button>
      <button class="btn" onclick="clearRoi()">Full frame</button>
    </div>
  </div>

  <div class="card s6" style="animation-delay:.3s"><h2><span class="ico">🖵</span>Capture source</h2>
    <div class="seg" id="seg">
      <button data-src="screen">Screen (recommended)</button>
      <button data-src="obs">OBS virtual cam</button>
    </div>
    <div class="fields">
      <span class="lbl">Monitor</span><input class="txt" id="cap_monitor" style="width:52px">
      <span class="lbl">OBS idx</span><input class="txt" id="cap_obs" style="width:52px">
    </div>
    <div class="hint">Region L / T / W / H &nbsp;(0 0 0 0 = full monitor)</div>
    <div class="fields">
      <input class="txt" id="cap_left"><input class="txt" id="cap_top">
      <input class="txt" id="cap_width"><input class="txt" id="cap_height">
      <button class="btn accent" onclick="applyCapture()">Apply</button>
    </div>
    <div class="row"><label>Detail (speed)</label>
      <input type="range" data-key="detect_scale" min="0.25" max="1" step="0.05">
      <span class="val"></span></div>
  </div>

  <div class="card s6" style="animation-delay:.33s"><h2><span class="ico">⌨</span>Hotkeys</h2>
    <div class="hk"><label>Show panel</label><input class="txt" id="hk_show" style="width:auto">
      <button class="btn" onclick="record('show')">Record</button></div>
    <div class="hk"><label>Toggle pull</label><input class="txt" id="hk_pull" style="width:auto">
      <button class="btn" onclick="record('pull')">Record</button></div>
    <div class="btns" style="margin-top:10px;justify-content:flex-end">
      <button class="btn accent" onclick="applyHotkeys()">Apply hotkeys</button></div>
    <div class="hint">Every hotkey is rebindable — type it or click
      <b>Record</b> and press the keys. Defaults: <span class="kbd">Right Shift</span>
      shows this panel, <span class="kbd">F8</span> toggles the pull.</div>
  </div>

</div>

<footer>
  <button class="btn" onclick="act('reset_defaults').then(load)">Reset defaults</button>
  <span class="note">Changes autosave · settings persist between runs</span>
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
// click-mode segmented
$$('#clickmode button').forEach(b=>b.onclick=()=>setKey('click_mode',b.dataset.mode).then(load));
// remember focus so polling doesn't stomp typed text
$$('input.txt').forEach(el=>{el.addEventListener('focus',()=>focused=el);
  el.addEventListener('blur',()=>{if(focused===el)focused=null;});});

function togglePull(){act('toggle_pull').then(render);}
function eyedrop(){act('eyedrop');flash('Eyedropper armed — click any pixel on screen (Esc cancels)');}
function applyCapture(){act('apply_capture',{
  monitor:+$('#cap_monitor').value||0, obs_device_index:+$('#cap_obs').value||0,
  left:+$('#cap_left').value||0, top:+$('#cap_top').value||0,
  width:+$('#cap_width').value||0, height:+$('#cap_height').value||0}).then(()=>flash('capture applied'));}
function applyRoi(){act('apply_roi',{
  roi_x:+$('#roi_x').value||0, roi_y:+$('#roi_y').value||0,
  roi_w:+$('#roi_w').value||0, roi_h:+$('#roi_h').value||0}).then(()=>flash('detection area applied'));}
function clearRoi(){['roi_x','roi_y','roi_w','roi_h'].forEach(id=>$('#'+id).value=0);applyRoi();}
function applyHotkeys(){act('apply_hotkeys',{show:$('#hk_show').value.trim(),
  pull:$('#hk_pull').value.trim(), trigger:$('#hk_trigger').value.trim()})
  .then(()=>flash('hotkeys applied'));}
function setTrigger(t){$('#hk_trigger').value=t;applyHotkeys();flash('click set to '+t);}
async function record(which){flash('press any key or combo…');
  const r=await act('record_hotkey');
  if(r&&r.hotkey){
    const el=which==='show'?$('#hk_show'):which==='trigger'?$('#hk_trigger'):$('#hk_pull');
    el.value=r.hotkey;applyHotkeys();flash('bound: '+r.hotkey);}
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
  const bp=!!S.body_part_detection;
  $$('#regions .chip').forEach(c=>c.classList.toggle('sel',bp&&c.dataset.r===S.active_region));
  box.style.opacity=bp?'1':'.4';box.style.pointerEvents=bp?'auto':'none';
  $('#regionHint').textContent=bp?'':'Regions apply only with body-part detection on.';
}
function render(){
  // status
  $('#fps').textContent=(S.target_found?'● ':'')+(S.fps||0)+' fps';
  $('#dot').classList.toggle('live',!!S.target_found);
  $('#statFps').textContent=(S.fps||0)+' fps';
  const st=$('#statTarget');
  st.textContent=S.target_found?'locked':'none';
  st.className='v '+(S.target_found?'ok':'bad');
  $('#statMode').textContent=({dwell:'Dwell',trigger:'Trigger',off:'Manual'})[S.click_mode]||'—';
  const on=!!S.pull_enabled, p=$('#power');
  p.innerHTML='PULL&nbsp;'+(on?'ON':'OFF');p.classList.toggle('on',on);
  if(!dragging&&S.error){/*keep*/}
  // segmented + region
  $$('#seg button').forEach(b=>b.classList.toggle('sel',b.dataset.src===(S.capture||{}).source));
  // click mode
  const cm=S.click_mode||'dwell';
  $$('#clickmode button').forEach(b=>b.classList.toggle('sel',b.dataset.mode===cm));
  $('#dwellRow').style.display=(cm==='dwell')?'':'none';
  $('#repeatRow').style.display=(cm==='dwell')?'':'none';
  $('#intervalRow').style.display=(cm==='dwell'&&S.click_repeat)?'':'none';
  $('#triggerRow').style.display=(cm==='trigger')?'':'none';
  $('#snapRow').style.display=S.snap_to_best?'':'none';
  $('#clickHint').textContent=cm==='dwell'?'Clicks after holding on target.':
    cm==='trigger'?'Press the trigger key to click instantly.':
    'No auto-click — click manually.';
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
  set('#roi_x',S.roi_x);set('#roi_y',S.roi_y);set('#roi_w',S.roi_w);set('#roi_h',S.roi_h);
  set('#hk_show',S.hotkey_show_panel);set('#hk_pull',S.hotkey_toggle_pull);
  set('#hk_trigger',S.hotkey_trigger);
}
async function load(){S=await fetch('/api/state').then(r=>r.json());fillStatic();render();}
async function poll(){try{S=await fetch('/api/state').then(r=>r.json());
  if(!dragging)fillStaticStatusOnly();render();}catch(e){}}
function fillStaticStatusOnly(){ // refresh only fields the user isn't editing
  const set=(id,v)=>{const e=$(id);if(e&&focused!==e&&document.activeElement!==e)e.value=v;};
  set('#hk_show',S.hotkey_show_panel);set('#hk_pull',S.hotkey_toggle_pull);
}
load();setInterval(poll,300);
</script>
</body>
</html>
"""
