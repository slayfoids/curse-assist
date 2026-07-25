"""The single-page web UI (HTML + CSS + JS) served by :mod:`webserver`.

Self-contained: no external fonts, scripts, or styles, so it works fully
offline. CURSE brand: full-width purple/black glass dashboard — layered
translucent cards over an animated violet aurora, gradient borders, noise
texture, and hover depth.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Curse</title>
<style>
  :root{
    --bg:#07040c; --fg:#f2edfa; --muted:#9b90ad; --muted2:#6f6580;
    --card:rgba(20,13,31,.55); --card-hi:rgba(29,19,45,.65);
    --field:rgba(12,7,20,.7); --edge:rgba(200,160,255,.09);
    --edge2:rgba(214,178,255,.2);
    --a1:#a855f7; --a2:#d946ef; --a3:#7c3aed;
    --on:#c26bff; --off:#ff5c49;
    --accent:linear-gradient(135deg,var(--a3),var(--a1) 55%,var(--a2));
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
      radial-gradient(1100px 700px at 12% -10%,rgba(124,58,237,.20),transparent 60%),
      radial-gradient(900px 640px at 105% 15%,rgba(217,70,239,.13),transparent 60%),
      radial-gradient(800px 700px at 50% 115%,rgba(88,28,135,.22),transparent 60%),
      var(--bg)}
  .blob{position:absolute;border-radius:50%;filter:blur(110px);opacity:.42;
    animation:drift 26s ease-in-out infinite}
  .b1{width:520px;height:520px;background:#6d28d9;top:-160px;left:-140px}
  .b2{width:460px;height:460px;background:#a21caf;bottom:-180px;right:-140px;animation-delay:-9s}
  .b3{width:380px;height:380px;background:#9333ea;top:35%;right:-160px;animation-delay:-15s;opacity:.28}
  .b4{width:340px;height:340px;background:#4c1d95;top:55%;left:-140px;animation-delay:-20s;opacity:.35}
  @keyframes drift{0%,100%{transform:translate(0,0) scale(1)}
    33%{transform:translate(60px,70px) scale(1.14)}
    66%{transform:translate(-40px,30px) scale(.92)}}
  .grid-lines{position:fixed;inset:0;z-index:-2;pointer-events:none;opacity:.5;
    background:
      linear-gradient(rgba(200,160,255,.025) 1px,transparent 1px),
      linear-gradient(90deg,rgba(200,160,255,.025) 1px,transparent 1px);
    background-size:44px 44px;
    -webkit-mask-image:radial-gradient(1200px 800px at 50% 0%,#000 30%,transparent 85%);
            mask-image:radial-gradient(1200px 800px at 50% 0%,#000 30%,transparent 85%)}
  .noise{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.05;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>")}

  /* ------------------------------------------------------------- top bar --- */
  .topbar{position:sticky;top:0;z-index:50;
    backdrop-filter:blur(22px) saturate(150%);-webkit-backdrop-filter:blur(22px) saturate(150%);
    background:linear-gradient(180deg,rgba(13,8,22,.82),rgba(13,8,22,.58));
    border-bottom:1px solid var(--edge)}
  .topbar-inner{max-width:1520px;margin:0 auto;padding:14px 28px;
    display:flex;align-items:center;gap:18px}
  .brand{display:flex;align-items:center;gap:12px;font-weight:800;font-size:19px;
    letter-spacing:4px}
  .brand .name{background:linear-gradient(90deg,#e9d5ff,var(--a1),var(--a2));
    -webkit-background-clip:text;background-clip:text;color:transparent}
  /* The mark stands on its own — no filled tile behind it, so the strokes
     read as a drawn logo rather than an app-store icon. */
  .mark{flex:0 0 34px;filter:drop-shadow(0 0 14px rgba(168,85,247,.45));
    transition:transform .5s cubic-bezier(.2,.8,.3,1)}
  .brand:hover .mark{transform:rotate(90deg)}
  .brand small{display:block;font-weight:500;font-size:10.5px;color:var(--muted);
    letter-spacing:1.2px;text-transform:none}
  .top-status{display:flex;gap:10px;margin-left:auto;align-items:center}
  .pill{display:flex;align-items:center;gap:8px;padding:7px 14px;border-radius:999px;
    background:var(--field);border:1px solid var(--edge);font-size:12px;color:var(--muted);
    font-variant-numeric:tabular-nums;transition:.25s}
  .pill b{color:var(--fg);font-weight:600}
  .dot{width:8px;height:8px;border-radius:50%;background:#4c4258;transition:.3s}
  .dot.live{background:var(--a2);box-shadow:0 0 12px var(--a2);animation:pulse 1.4s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

  /* ---------------------------------------------------------------- layout - */
  .wrap{max-width:1520px;margin:0 auto;padding:26px 28px 60px}
  .section{grid-column:1/-1;display:flex;align-items:center;gap:14px;
    margin:26px 0 2px;opacity:0;animation:rise .55s .1s forwards}
  .section:first-child{margin-top:0}
  .section .tag{font-size:11px;font-weight:800;letter-spacing:2.6px;text-transform:uppercase;
    background:linear-gradient(90deg,var(--a2),var(--a1),var(--a3));
    -webkit-background-clip:text;background-clip:text;color:transparent;white-space:nowrap}
  .section .rule{flex:1;height:1px;
    background:linear-gradient(90deg,rgba(168,85,247,.5),rgba(200,160,255,.07) 45%,transparent)}
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
      linear-gradient(155deg,rgba(233,213,255,.2),rgba(200,160,255,.05) 38%,rgba(168,85,247,.28) 100%) border-box;
    backdrop-filter:blur(20px) saturate(150%);-webkit-backdrop-filter:blur(20px) saturate(150%);
    box-shadow:0 14px 40px rgba(0,0,0,.5),inset 0 1px 0 rgba(233,213,255,.05);
    opacity:0;transform:translateY(14px);animation:rise .55s forwards;
    transition:transform .28s cubic-bezier(.2,.8,.2,1),box-shadow .28s,background .28s}
  .card:hover{transform:translateY(-4px);
    background:
      linear-gradient(var(--card-hi),var(--card-hi)) padding-box,
      linear-gradient(155deg,rgba(233,213,255,.32),rgba(200,160,255,.09) 38%,rgba(217,70,239,.45) 100%) border-box;
    box-shadow:0 22px 60px rgba(0,0,0,.6),0 0 0 1px rgba(168,85,247,.1),
      0 0 44px rgba(168,85,247,.13),inset 0 1px 0 rgba(233,213,255,.09)}
  .card::before{content:"";position:absolute;inset:0;pointer-events:none;
    background:linear-gradient(115deg,transparent 35%,rgba(233,213,255,.06) 48%,transparent 62%);
    transform:translateX(-130%);transition:transform .9s ease}
  .card:hover::before{transform:translateX(130%)}
  @keyframes rise{to{opacity:1;transform:none}}
  .card h2{margin:0 0 14px;font-size:11px;letter-spacing:1.6px;text-transform:uppercase;
    color:var(--muted);font-weight:700;display:flex;align-items:center;gap:9px}
  .card h2 .ico{width:24px;height:24px;border-radius:8px;display:grid;place-items:center;
    font-size:12px;color:#ead9ff;background:rgba(168,85,247,.14);
    border:1px solid rgba(168,85,247,.3);box-shadow:inset 0 0 10px rgba(168,85,247,.15)}

  /* ------------------------------------------------------------------ hero - */
  .hero{display:flex;align-items:center;gap:26px;flex-wrap:wrap;padding:24px 26px}
  .power{position:relative;border:0;border-radius:18px;padding:20px 44px;font-size:17px;
    font-weight:800;letter-spacing:1.2px;color:#fff;cursor:pointer;
    background:linear-gradient(135deg,#7a241b,var(--off));
    box-shadow:0 10px 30px rgba(224,80,58,.28),inset 0 1px 0 rgba(255,255,255,.22);
    transition:.28s;z-index:1}
  .power:hover{transform:translateY(-2px)}
  .power:active{transform:scale(.97)}
  .power.on{background:linear-gradient(135deg,#5b21b6,var(--a2));
    box-shadow:0 10px 34px rgba(168,85,247,.45),inset 0 1px 0 rgba(255,255,255,.25);
    animation:glow 1.9s ease-in-out infinite}
  .power.on::after{content:"";position:absolute;inset:-5px;border-radius:22px;z-index:-1;
    background:conic-gradient(from 0deg,#7c3aed,#d946ef,#a855f7,#7c3aed);
    filter:blur(14px);opacity:.6;animation:hue 4s linear infinite}
  @keyframes hue{to{filter:blur(14px) hue-rotate(360deg)}}
  @keyframes glow{0%,100%{box-shadow:0 10px 30px rgba(168,85,247,.38)}
    50%{box-shadow:0 12px 48px rgba(217,70,239,.7)}}
  .hero-info{flex:1;min-width:220px}
  .hero-info .title{font-size:15px;font-weight:700;margin-bottom:4px}
  .msg{font-size:12.5px;color:var(--muted);min-height:16px;transition:.2s}
  .stats{display:flex;gap:12px;flex-wrap:wrap}
  .stat{min-width:118px;padding:12px 16px;border-radius:14px;background:var(--field);
    border:1px solid var(--edge);transition:.25s}
  .stat:hover{border-color:var(--edge2);transform:translateY(-2px)}
  .stat .k{font-size:10px;letter-spacing:1.6px;color:var(--muted2);text-transform:uppercase;font-weight:700}
  .stat .v{font-size:19px;font-weight:750;margin-top:3px;font-variant-numeric:tabular-nums}
  .stat .v.ok{color:var(--on);text-shadow:0 0 14px rgba(194,107,255,.55)}
  .stat .v.bad{color:var(--muted)}

  /* --------------------------------------------------------------- controls - */
  /* Two lines, not one: label and value share the top row, the slider spans
     the full width underneath.
     The single-line version could not fit. A range input is a replaced element
     with an intrinsic width around 129px, and `flex:1` leaves `min-width:auto`
     in force — so the row refused to shrink below label + slider + value, a
     hard 355px, inside a 248px card. Everything past that was cut off by the
     card's overflow:hidden, which put every value readout 94px off the right
     edge of its card and out of sight.
     Grid columns of `minmax(0,...)` are the fix that keeps it fixed: children
     are allowed to shrink below their intrinsic width, so no future label or
     font fallback can push the number out of view again. */
  /* Rows are pinned explicitly rather than auto-placed. The slider sits
     between the label and the value in the markup, and a full-width item
     forces a new grid row — so with auto-placement the value was pushed below
     the slider onto a third row instead of sitting beside its label. */
  .row{display:grid;grid-template-columns:minmax(0,1fr) auto;
    align-items:center;column-gap:10px;row-gap:5px;margin:12px 0}
  .row label{grid-column:1;grid-row:1;min-width:0;color:var(--fg);font-size:13px;
    overflow-wrap:break-word;hyphens:auto}
  .row .val{grid-column:2;grid-row:1;justify-self:end;min-width:44px;
    text-align:right;
    font-variant-numeric:tabular-nums;color:#fff;font-weight:700;font-size:13px}
  .row input[type=range]{grid-column:1/-1;grid-row:2;width:100%}
  input[type=range]{-webkit-appearance:none;appearance:none;width:100%;
    min-width:0;height:6px;
    border-radius:999px;outline:0;cursor:pointer;
    background:linear-gradient(90deg,var(--a3),var(--a2) var(--p,50%),rgba(200,160,255,.1) var(--p,50%))}
  input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:17px;height:17px;
    border-radius:50%;background:#fff;cursor:grab;
    box-shadow:0 0 0 4px rgba(168,85,247,.22),0 0 14px rgba(168,85,247,.8),0 2px 6px rgba(0,0,0,.5);
    transition:transform .15s,box-shadow .15s}
  input[type=range]::-webkit-slider-thumb:hover{transform:scale(1.22);
    box-shadow:0 0 0 6px rgba(168,85,247,.25),0 0 20px rgba(217,70,239,.95)}
  input[type=range]::-webkit-slider-thumb:active{cursor:grabbing}
  input[type=range]::-moz-range-thumb{width:17px;height:17px;border:0;border-radius:50%;
    background:#fff;box-shadow:0 0 12px var(--a1)}

  .toggle{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:11px 0}
  .toggle > span{font-size:13px;min-width:0;overflow-wrap:break-word}
  .toggle small{color:var(--muted);font-size:11px}
  .switch{position:relative;width:46px;height:26px;flex:0 0 auto}
  .switch input{opacity:0;width:0;height:0}
  .track{position:absolute;inset:0;background:rgba(200,160,255,.1);border-radius:999px;
    transition:.28s;border:1px solid var(--edge)}
  .track:before{content:"";position:absolute;width:20px;height:20px;left:2px;top:2px;
    background:#fff;border-radius:50%;transition:.28s cubic-bezier(.2,.8,.2,1);
    box-shadow:0 2px 8px rgba(0,0,0,.5)}
  .switch input:checked + .track{background:var(--accent);border-color:transparent;
    box-shadow:0 0 16px rgba(168,85,247,.45)}
  .switch input:checked + .track:before{transform:translateX(20px)}
  .switch:hover .track{border-color:var(--edge2)}

  .btn{border:1px solid var(--edge);background:var(--field);color:var(--fg);
    padding:9px 15px;border-radius:12px;font-weight:600;font-size:13px;cursor:pointer;
    transition:.2s;backdrop-filter:blur(8px)}
  .btn:hover{transform:translateY(-2px);border-color:var(--edge2);
    box-shadow:0 8px 20px rgba(0,0,0,.35)}
  .btn:active{transform:scale(.96)}
  .btn.accent{background:var(--accent);border:0;color:#fff;font-weight:750;
    box-shadow:0 6px 20px rgba(168,85,247,.4)}
  .btn.accent:hover{box-shadow:0 10px 28px rgba(217,70,239,.55)}
  .btn.mini{padding:5px 10px;font-size:12px;border-radius:9px}
  .btn.mini.del{color:#ff9a8a}
  .btns{display:flex;gap:8px;flex-wrap:wrap}
  .btns > *{min-width:0}

  .gridchips{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .chip{padding:11px 0;text-align:center;border-radius:12px;background:var(--field);
    border:1px solid var(--edge);cursor:pointer;font-weight:700;font-size:13px;transition:.2s}
  .chip:hover{transform:translateY(-2px);border-color:var(--edge2)}
  .chip.sel{background:var(--accent);border-color:transparent;color:#fff;
    box-shadow:0 6px 22px rgba(168,85,247,.5)}

  /* ------------------------------------------------- detection-area crop --- */
  .roi-now{font-size:12px;color:var(--muted);background:var(--field);
    border:1px solid var(--edge);border-radius:10px;padding:8px 10px;
    font-variant-numeric:tabular-nums}
  .roi-now b{color:#e2b8ff}
  .cropbox{position:relative;overflow:hidden;border:1px solid var(--edge2);
    border-radius:12px;line-height:0;cursor:crosshair;touch-action:none}
  .cropbox canvas{display:block;width:100%;height:auto}
  .cropsel{position:absolute;display:none;border:2px solid var(--a2);
    background:rgba(217,70,239,.16);pointer-events:none;
    box-shadow:0 0 0 9999px rgba(7,4,12,.55)}
  details.adv{margin-top:10px}
  details.adv summary{cursor:pointer;color:var(--muted);font-size:12px;
    list-style:none;padding:4px 0}
  details.adv summary::-webkit-details-marker{display:none}
  details.adv summary:before{content:"▸ ";color:var(--a1)}
  details.adv[open] summary:before{content:"▾ "}
  details.adv summary:hover{color:var(--fg)}

  .swatches{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:12px;min-height:40px}
  .sw{width:40px;height:40px;border-radius:12px;position:relative;cursor:pointer;
    border:1px solid rgba(233,213,255,.3);transition:.2s;overflow:hidden;
    box-shadow:0 4px 14px rgba(0,0,0,.4)}
  .sw:hover{transform:scale(1.12) rotate(-3deg)}
  .sw:after{content:"✕";position:absolute;inset:0;display:grid;place-items:center;
    color:#fff;font-size:13px;font-weight:800;background:rgba(0,0,0,.5);opacity:0;transition:.15s}
  .sw:hover:after{opacity:1}
  .empty{color:var(--muted);font-size:12px;align-self:center}

  .seg{display:flex;background:var(--field);border:1px solid var(--edge);
    border-radius:13px;padding:4px;gap:4px;margin-bottom:12px}
  /* min-width:0 — flex items otherwise refuse to shrink below their text, and
     a two-word label then pushes the segment out past the card edge. */
  .seg button{flex:1;min-width:0;border:0;background:transparent;color:var(--muted);
    padding:9px 6px;border-radius:10px;font-weight:700;cursor:pointer;
    transition:.22s;font-size:13px;overflow-wrap:break-word}
  .seg button:hover{color:var(--fg)}
  .seg button.sel{background:var(--accent);color:#fff;
    box-shadow:0 4px 16px rgba(168,85,247,.45)}

  /* Same shrink rule as .row: flex children default to min-width:auto, so a
     text input keeps its intrinsic width and pushes the last field out of the
     card. min-width:0 lets the row give way instead of overflowing. */
  .fields{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
  .fields > *{min-width:0}
  .fields .lbl{color:var(--muted);font-size:12px;flex:0 0 auto}
  input.txt{width:64px;min-width:0;background:var(--field);
    border:1px solid var(--edge);color:var(--fg);
    border-radius:10px;padding:8px 9px;font:inherit;outline:0;transition:.2s}
  input.txt:focus{border-color:var(--a1);box-shadow:0 0 0 3px rgba(168,85,247,.2)}
  input.txt:hover{border-color:var(--edge2)}
  /* A four-up numeric grid that stays four-up at any card width. */
  .quad{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;
    margin:8px 0}
  .quad input.txt{width:100%}
  .hk{display:grid;grid-template-columns:minmax(0,1fr) auto;
    align-items:center;column-gap:8px;row-gap:6px;margin:9px 0}
  .hk label{grid-column:1;grid-row:1;min-width:0;color:var(--muted);
    font-size:12px;overflow-wrap:break-word;hyphens:auto}
  .hk input{grid-column:1/-1;grid-row:2;width:100%;min-width:0}
  .hk button{grid-column:2;grid-row:1}


  /* ---------- section tabs ---------------------------------------------- */
  .tabs{grid-column:span 12;display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 2px}
  .tabs button{appearance:none;cursor:pointer;font:600 12.5px/1 inherit;
    color:var(--muted);background:var(--card);border:1px solid var(--edge);
    padding:10px 16px;border-radius:12px;transition:.18s;letter-spacing:.02em}
  .tabs button:hover{color:var(--fg);border-color:var(--edge2)}
  .tabs button.sel{color:#fff;background:var(--accent);border-color:transparent;
    box-shadow:0 6px 20px rgba(168,85,247,.35)}
  .card[data-tab]{display:none}
  .card[data-tab].show{display:block}
  /* ---------- plain-language info bubbles ------------------------------- */
  .i{display:inline-flex;align-items:center;justify-content:center;
    width:15px;height:15px;margin-left:6px;border-radius:50%;flex:0 0 15px;
    font:600 10px/1 "Segoe UI",system-ui,sans-serif;cursor:help;
    color:var(--a1);background:rgba(168,85,247,.13);
    border:1px solid rgba(168,85,247,.34);vertical-align:middle;
    transition:.15s;position:relative}
  .i:hover{background:var(--a1);color:#fff;border-color:var(--a1)}
  /* One shared bubble parked on <body> and moved to whichever icon is hovered,
     rather than a ::after inside the card. Cards clip their contents (the
     sheen sweep needs overflow:hidden), so a bubble anchored to the icon was
     cut off by the card edge — - and being 250px wide opening upward, that was
     most of them. Fixed positioning takes it out of that box entirely. */
  #tip{position:fixed;z-index:120;width:250px;max-width:min(250px,86vw);
    padding:9px 11px;border-radius:11px;font:400 11.5px/1.45 inherit;
    color:var(--fg);background:rgba(24,14,38,.98);
    border:1px solid var(--edge2);box-shadow:0 12px 34px rgba(0,0,0,.6);
    opacity:0;pointer-events:none;transition:opacity .16s;text-align:left;
    left:0;top:0}
  #tip.on{opacity:1}

  /* ---------- first-paint loader ---------------------------------------- */
  #boot{position:fixed;inset:0;z-index:200;display:flex;flex-direction:column;
    align-items:center;justify-content:center;gap:20px;background:var(--bg);
    transition:opacity .5s ease,visibility .5s}
  #boot.gone{opacity:0;visibility:hidden}
  #boot .ring{width:62px;height:62px;border-radius:50%;
    border:2px solid rgba(168,85,247,.16);border-top-color:var(--a1);
    border-right-color:var(--a2);animation:spin 900ms cubic-bezier(.5,.1,.4,.9) infinite}
  #boot .wm{font-weight:800;font-size:15px;letter-spacing:.34em;
    background:linear-gradient(90deg,#e9d5ff,var(--a1),var(--a2));
    -webkit-background-clip:text;background-clip:text;color:transparent;
    animation:pulse 1.5s ease-in-out infinite}
  #boot .sub{font-size:11px;color:var(--muted2);letter-spacing:.06em;
    margin-top:-12px}
  @keyframes spin{to{transform:rotate(360deg)}}
  @keyframes pulse{0%,100%{opacity:.55}50%{opacity:1}}
  /* Cards settle in once the loader clears. */
  .booting .card{opacity:0}

  /* ---------- patch notes ----------------------------------------------- */
  .rel{border-left:2px solid rgba(168,85,247,.28);padding:0 0 2px 14px;
    margin:0 0 16px}
  .rel h3{margin:0 0 3px;font-size:13.5px;font-weight:700;color:var(--fg)}
  .rel h3 .tagv{font-size:10.5px;font-weight:600;color:var(--a1);
    background:rgba(168,85,247,.14);border:1px solid rgba(168,85,247,.3);
    padding:1px 7px;border-radius:20px;margin-left:7px;vertical-align:1px}
  .rel ul{margin:6px 0 0;padding-left:17px;color:var(--muted)}
  .rel li{margin:4px 0;font-size:12.5px;line-height:1.5}
  .rel li b{color:var(--fg);font-weight:600}
  .hint{color:var(--muted2);font-size:11.5px;margin-top:3px;line-height:1.5}
  .kbd{display:inline-block;padding:1px 7px;border-radius:6px;background:rgba(233,213,255,.08);
    border:1px solid var(--edge);font-size:11px;font-weight:600;color:var(--fg)}

  /* --------------------------------------------------------- saved configs - */
  .cfg-list{display:flex;flex-direction:column;gap:6px;margin:10px 0;
    max-height:230px;overflow-y:auto;padding-right:2px}
  .cfg{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:11px;
    background:var(--field);border:1px solid var(--edge);transition:.2s}
  .cfg:hover{border-color:var(--edge2);transform:translateX(3px)}
  .cfg .code{font-family:Consolas,ui-monospace,monospace;font-size:12px;font-weight:700;
    color:#e2b8ff;background:rgba(168,85,247,.13);border:1px solid rgba(168,85,247,.32);
    padding:3px 8px;border-radius:7px;cursor:copy;transition:.2s;white-space:nowrap}
  .cfg .code:hover{box-shadow:0 0 12px rgba(168,85,247,.4)}
  .cfg .nm{flex:1;font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .cfg .nm i{color:var(--muted2)}
  .cfg .dt{font-size:11px;color:var(--muted2);white-space:nowrap}

  footer{display:flex;gap:10px;margin-top:30px;align-items:center}
  footer .note{color:var(--muted2);font-size:12px}
  footer .btn.quit{margin-left:auto;color:#ff9a8a;border-color:rgba(224,80,58,.4)}
  footer .btn.quit:hover{background:rgba(224,80,58,.12);box-shadow:0 8px 22px rgba(224,80,58,.25)}
  ::-webkit-scrollbar{width:10px}
  ::-webkit-scrollbar-thumb{background:rgba(200,160,255,.12);border-radius:10px;
    border:2px solid transparent;background-clip:padding-box}
  ::-webkit-scrollbar-thumb:hover{background:rgba(200,160,255,.2);background-clip:padding-box}
  ::selection{background:rgba(168,85,247,.4)}
  @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}
    .card,.section{opacity:1;transform:none}}
</style>
</head>
<body class="booting">
<div id="boot">
  <div class="ring"></div>
  <div class="wm">CURSE</div>
  <div class="sub">starting engine…</div>
</div>
<div class="bg">
  <div class="blob b1"></div><div class="blob b2"></div>
  <div class="blob b3"></div><div class="blob b4"></div>
</div>
<div class="grid-lines"></div><div class="noise"></div>
<div id="tip" role="tooltip"></div>

<div class="topbar"><div class="topbar-inner">
  <div class="brand">
    <!-- Monoline mark: a reticle whose lower-right quadrant opens into a
         pointer. Drawn from circles and straight strokes on a single grid so
         it stays crisp at favicon size and reads as a tool, not decoration. -->
    <svg class="mark" width="34" height="34" viewBox="0 0 32 32" fill="none"
         aria-hidden="true">
      <defs>
        <linearGradient id="cg" x1="4" y1="4" x2="28" y2="28"
                        gradientUnits="userSpaceOnUse">
          <stop stop-color="#e9d5ff"/><stop offset=".55" stop-color="#a855f7"/>
          <stop offset="1" stop-color="#d946ef"/>
        </linearGradient>
      </defs>
      <circle cx="16" cy="16" r="10.5" stroke="url(#cg)" stroke-width="1.6"
              stroke-linecap="round" stroke-dasharray="41 8"
              transform="rotate(-45 16 16)"/>
      <circle cx="16" cy="16" r="4.2" stroke="url(#cg)" stroke-width="1.6"/>
      <path d="M16 1.5v5M1.5 16h5M16 25.5v5M25.5 16h5" stroke="url(#cg)"
            stroke-width="1.6" stroke-linecap="round"/>
      <path d="M17.6 17.6 27 27l-3.4.5-.5 3.4-5.5-13.3Z" fill="url(#cg)"/>
    </svg>
    <span><span class="name">CURSE</span><small>color-guided pointer accessibility
      · <span id="ver">—</span></small></span></div>
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

  <nav class="tabs" id="tabs" role="tablist">
    <button data-t="guide"  role="tab">⚡ Guidance</button>
    <button data-t="aim"    role="tab">⌖ Targeting</button>
    <button data-t="click"  role="tab">✦ Clicking</button>
    <button data-t="detect" role="tab">🎨 Detection</button>
    <button data-t="setup"  role="tab">⌨ Setup</button>
  </nav>
  </div>


  <div class="card s3" data-tab="guide" style="animation-delay:.05s"><h2><span class="ico">⚡</span>Activation</h2>
    <div class="seg" id="actmode">
      <button data-am="toggle">Toggle</button>
      <button data-am="hold">Hold</button>
    </div>
    <div id="holdRow">
      <div class="hk"><label>Hold button</label>
        <input class="txt" id="hk_hold" style="width:auto">
        <button class="btn" onclick="recordHold()">Record</button></div>
      <div class="btns" style="margin:6px 0 8px">
        <button class="btn" onclick="setHold('MB4')">Mouse4</button>
        <button class="btn" onclick="setHold('MB5')">Mouse5</button>
        <button class="btn" onclick="setHold('MMB')">MMB</button>
        <button class="btn" onclick="setHold('RMB')">RMB</button>
        <button class="btn" onclick="setHold('right ctrl')">R-Ctrl</button>
        <button class="btn" onclick="setHold('space')">Space</button>
      </div>
    </div>
    <div class="toggle"><span>Audio cues<br><small>2 high beeps = on · 2 low = off</small></span>
      <label class="switch"><input type="checkbox" data-key="audio_cues">
      <span class="track"></span></label></div>
    <div class="hint" id="actHint"></div>
  </div>

  <div class="card s3" data-tab="guide" style="animation-delay:.06s"><h2><span class="ico">〜</span>Motion</h2>
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

  <div class="card s3" data-tab="guide" style="animation-delay:.07s"><h2><span class="ico">◈</span>Fine tracking</h2>
    <div class="row"><label>Motion response</label>
      <input type="range" data-key="motion_response" min="0.2" max="3" step="0.1">
      <span class="val"></span></div>
    <div class="row"><label>Jitter floor</label>
      <input type="range" data-key="jitter_floor" min="0.2" max="3" step="0.1">
      <span class="val"></span></div>
    <div class="row"><label>Precision zone</label>
      <input type="range" data-key="precision_px" min="0" max="300" step="10">
      <span class="val"></span></div>
    <div class="row"><label>Zone slowdown</label>
      <input type="range" data-key="precision_slow" min="0.05" max="1" step="0.05">
      <span class="val"></span></div>
    <div class="row"><label>Accel limit</label>
      <input type="range" data-key="max_accel" min="0" max="400000" step="10000">
      <span class="val"></span></div>
    <div class="hint">
      <b>Motion response</b> — how readily tracking opens up as the target moves
      (higher = less lag on fast movement).<br>
      <b>Jitter floor</b> — how hard a <i>still</i> target is filtered
      (higher = calmer pointer at rest).<br>
      <b>Precision zone</b> — within this many px the pointer eases off and
      settles instead of darting the last stretch. 0 = off.<br>
      <b>Accel limit</b> — caps how fast the pointer's own speed can change, so
      one bad detection frame can't fling it. 0 = off.
    </div>
  </div>

  <div class="card s3" data-tab="guide" style="animation-delay:.08s"><h2><span class="ico">🖱</span>Pointer calibration</h2>
    <div class="toggle"><span>Auto-calibrate<br><small>learn this PC's pointer speed</small></span>
      <label class="switch"><input type="checkbox" data-key="pointer_gain_auto">
      <span class="track"></span></label></div>
    <div class="row"><label>Extra gain</label>
      <input type="range" data-key="pointer_gain" min="0.25" max="4" step="0.05">
      <span class="val"></span></div>
    <div class="roi-now" style="margin:10px 0 8px">Windows setting:
      <b id="ptrProfile">—</b><br>Measured: <b id="gainNow">—</b></div>
    <div class="hint">Windows scales mouse movement by the pointer-speed slider,
      and bends it further with “enhance pointer precision”. That makes the same
      request travel <b>1 px on a low setting and 35 px on a high one</b>, and
      travel different distances at different speeds when precision enhancement
      is on. The engine reads both settings and compensates, so it behaves the
      same at either extreme.<br><span id="ptrRes"></span><br>
      Leave <b>Extra gain</b> alone unless it still under-reaches — raising it
      reaches further, lowering it reaches less.</div>
  </div>

  <div class="card s3" data-tab="aim" style="animation-delay:.09s"><h2><span class="ico">⌖</span>Targeting</h2>
    <div class="toggle"><span>Lock onto one target<br><small>hold it until it's gone</small></span>
      <label class="switch"><input type="checkbox" data-key="lock_target">
      <span class="track"></span></label></div>
    <div class="toggle"><span>Target follow<br><small>scan a window, not the whole screen</small></span>
      <label class="switch"><input type="checkbox" data-key="adaptive_roi">
      <span class="track"></span></label></div>
    <div class="toggle"><span>Best-coverage snap<br><small>aim at the thickest part of the target</small></span>
      <label class="switch"><input type="checkbox" data-key="snap_to_best">
      <span class="track"></span></label></div>
    <div id="snapRow">
      <div class="row"><label>Snap after (ms)</label>
        <input type="range" data-key="snap_after_ms" min="0" max="3000" step="50">
        <span class="val"></span></div>
      <div class="row"><label>Snap circle</label>
        <input type="range" data-key="snap_radius" min="0" max="120" step="2">
        <span class="val"></span></div>
      <div class="hint" id="snapHint"></div>
    </div>
    <div class="hint">Lock stops the pointer drifting between several same-color
      targets. Snap then nudges the aim to the densest part <b>of that target</b>
      — it can't move it onto a different one.
      Set the delay to <b>0</b> for an instant snap — the timed version waits for
      the pointer to rest on the color, which a moving target never lets it do.</div>
  </div>

  <div class="card s3" data-tab="aim" style="animation-delay:.12s"><h2><span class="ico">◎</span>Field of view</h2>
    <div class="toggle"><span>Show crosshair circle</span>
      <label class="switch"><input type="checkbox" data-key="show_overlay">
      <span class="track"></span></label></div>
    <div class="toggle"><span>Show aim line<br><small>cyan line to the pixel it's aiming for</small></span>
      <label class="switch"><input type="checkbox" data-key="show_aim_line">
      <span class="track"></span></label></div>
    <div class="row"><label>Pull radius</label>
      <input type="range" data-key="pull_radius" min="0" max="1000" step="10">
      <span class="val"></span></div>
    <div class="row"><label>Circle size</label>
      <input type="range" data-key="overlay_radius" min="0" max="1000" step="10">
      <span class="val"></span></div>
    <div class="hint">Only assist toward colors within the pull radius of the
      cursor (0 = whole screen). Circle size is purely the drawn circle
      (0 = match pull radius) — it no longer doubles as the snap circle, which
      has its own setting under Targeting.</div>
  </div>


  <div class="card s6" data-tab="click" style="animation-delay:.15s"><h2><span class="ico">✦</span>Click</h2>
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

  <div class="card s6" data-tab="click" style="animation-delay:.18s"><h2><span class="ico">⛨</span>Input control</h2>
    <div class="toggle"><span>Block my mouse while the bot is moving<br>
      <small>steadies a shaky hand so it doesn't fight the assist</small></span>
      <label class="switch"><input type="checkbox" data-key="suppress_mouse">
      <span class="track"></span></label></div>
    <div class="hint">Uses a low-level Windows mouse hook while a pull is active;
      clicks always pass through. Turn guidance off (<span class="kbd">F8</span>
      by default) to take back full control instantly.</div>
  </div>


  <div class="card s4" data-tab="detect" style="animation-delay:.21s"><h2><span class="ico">🎨</span>Target colors</h2>
    <div class="swatches" id="swatches"></div>
    <div class="btns" style="margin-bottom:12px">
      <input type="color" id="picker" style="width:0;height:0;opacity:0;position:absolute">
      <button class="btn accent" onclick="document.getElementById('picker').click()">＋ Pick</button>
      <button class="btn" onclick="eyedrop()" id="eyeBtn">⦿ Eyedropper</button>
      <button class="btn" onclick="shotOpen()">📷 Screenshot</button>
      <button class="btn" onclick="act('clear_colors')">Clear</button>
    </div>
    <div id="shotWrap" style="display:none;margin-bottom:12px">
      <div class="hint" style="margin:0 0 8px">Click any pixel to add its colour.
        Scroll to zoom the preview. <b id="shotHint">—</b></div>
      <div style="position:relative;overflow:auto;max-height:340px;
                  border:1px solid var(--edge2);border-radius:12px">
        <canvas id="shotCv" style="display:block;cursor:crosshair;max-width:100%"></canvas>
      </div>
      <div class="btns" style="margin-top:8px">
        <button class="btn" onclick="shotGrab()">↻ Retake</button>
        <button class="btn" onclick="shotClose()">Close</button>
      </div>
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
    <div class="roi-now" style="margin-top:8px" id="covNow">—</div>
    <div class="hint">Sensitivity widens the range of hues that count as your
      colour, while keeping it distinct from grey and from black — so the whole
      slider stays usable instead of matching most of the screen near the top.
      Reds are handled across the hue wrap automatically.</div>
  </div>

  <div class="card s4" data-tab="aim" style="animation-delay:.24s"><h2><span class="ico">☰</span>Body aim</h2>
    <div class="toggle"><span>Body-part detection<br><small>off = track the color directly</small></span>
      <label class="switch"><input type="checkbox" data-key="body_part_detection">
      <span class="track"></span></label></div>
    <div class="gridchips" id="regions" style="margin-top:10px"></div>
    <div class="row" id="attractRow" style="margin-top:12px"><label>Part attraction</label>
      <input type="range" data-key="part_attraction" min="0.3" max="1" step="0.05">
      <span class="val"></span></div>
    <div class="hint" id="regionHint"></div>
    <div class="hint">1.00 = aim exactly at the part; lower blends toward the
      figure's center for extra steadiness. Bands adapt to the figure's pose
      (standing / crouching / prone).</div>
  </div>

  <div class="card s4" data-tab="detect" style="animation-delay:.27s"><h2><span class="ico">▣</span>Detection area</h2>
    <div class="hint" style="margin-bottom:8px">Only look for colors inside this
      box — everything outside is ignored, which is faster and stops it picking
      up things you don't mean.</div>
    <div class="btns" style="margin-bottom:10px">
      <button class="btn accent" onclick="pickRegion('roi')">◫ Select on screen</button>
      <button class="btn" onclick="cropOpen()">🖼 Crop a screenshot</button>
      <button class="btn" onclick="clearRoi()">Full frame</button>
    </div>
    <div class="roi-now" id="roiNow">—</div>
    <div id="cropWrap" style="display:none;margin:10px 0">
      <div class="hint" style="margin:0 0 8px">Drag a box over the part to
        watch. <b id="cropHint">—</b></div>
      <div class="cropbox" id="cropBox">
        <canvas id="cropCv"></canvas>
        <div class="cropsel" id="cropSel"></div>
      </div>
      <div class="btns" style="margin-top:8px">
        <button class="btn" onclick="cropGrab()">↻ Retake</button>
        <button class="btn" onclick="cropClose()">Close</button>
      </div>
    </div>
    <div class="toggle"><span>Show the area on screen<br>
      <small>dashed outline over the desktop</small></span>
      <label class="switch"><input type="checkbox" data-key="show_roi">
      <span class="track"></span></label></div>
    <details class="adv"><summary>Type exact numbers</summary>
      <div class="quad">
        <input class="txt" id="roi_x" placeholder="X"><input class="txt" id="roi_y" placeholder="Y">
        <input class="txt" id="roi_w" placeholder="W"><input class="txt" id="roi_h" placeholder="H">
      </div>
      <div class="btns"><button class="btn" onclick="applyRoi()">Apply</button></div>
    </details>
  </div>

  <div class="card s6" data-tab="detect" style="animation-delay:.3s"><h2><span class="ico">🖵</span>Capture source</h2>
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
    <div class="row"><label>Scan rate</label>
      <input type="range" data-key="scan_fps" min="0" max="360" step="5">
      <span class="val"></span></div>
    <div class="hint" id="scanHint">—</div>
  </div>

  <div class="card s6" data-tab="setup" style="animation-delay:.33s"><h2><span class="ico">⌨</span>Hotkeys</h2>
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


  <div class="card s12" data-tab="setup" style="animation-delay:.36s"><h2><span class="ico">☷</span>Configs</h2>
    <div class="fields">
      <input class="txt" id="cfg_name" placeholder="config name (optional)"
        style="flex:1;min-width:160px;width:auto">
      <button class="btn accent" onclick="saveConfig()">💾 Save current setup</button>
      <span class="lbl" style="margin-left:12px">Load by code</span>
      <input class="txt" id="cfg_code" placeholder="CRS-XXXXXX" style="width:120px">
      <button class="btn" onclick="loadConfigCode()">Load</button>
    </div>
    <div class="hint">Every save gets a unique random code. Click a code to copy
      it — share it or type it on another setup to load that exact config.</div>
    <div class="cfg-list" id="cfgList"></div>
  </div>

  <div class="card s12" data-tab="setup" style="animation-delay:.38s"><h2><span class="ico">✧</span>Latest updates</h2>
    <div id="notes"></div>
    <div class="hint">You're running <b><span id="verNote">—</span></b>. Newest
      changes first.</div>
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
// activation-mode segmented
$$('#actmode button').forEach(b=>b.onclick=()=>setKey('activation_mode',b.dataset.am).then(load));
function setHold(t){$('#hk_hold').value=t;setKey('hotkey_hold',t).then(load);flash('hold button set to '+t);}
$('#hk_hold').addEventListener('change',e=>{const v=e.target.value.trim();
  if(v)setKey('hotkey_hold',v).then(load);});
/* mouse:true -> the capture polls real key state, so a side button records as
   MB4 instead of leaving the keyboard-only reader blocked until some unrelated
   key (classically the Windows key) arrived and got bound by mistake. */
async function recordHold(){flash('press the mouse button or key to hold… (Esc cancels)');
  const r=await act('record_hotkey',{mouse:true});
  if(r&&r.hotkey){setHold(r.hotkey);flash('bound to '+r.hotkey);}
  else flash('nothing recorded — try again, or use a preset button');}
// remember focus so polling doesn't stomp typed text
$$('input.txt').forEach(el=>{el.addEventListener('focus',()=>focused=el);
  el.addEventListener('blur',()=>{if(focused===el)focused=null;});});

function togglePull(){act('toggle_pull').then(render);}
function eyedrop(){act('eyedrop');flash('Eyedropper armed — click any pixel on screen (Esc cancels)');}

/* ---- screenshot colour picker -------------------------------------------
   Freezes one frame of the capture source and lets the colour be clicked at
   leisure. The live eyedropper needs the colour still on screen *and* a
   steady click, which is the exact difficulty this tool exists to help with. */
let shotImg=null;
async function shotGrab(){
  $('#shotHint').textContent='grabbing…';
  try{
    const r=await fetch('/api/screenshot?t='+Date.now());
    if(!r.ok){$('#shotHint').textContent='capture failed — check the Capture card';return;}
    const blob=await r.blob();
    const img=new Image();
    img.onload=()=>{
      shotImg=img;
      const cv=$('#shotCv');cv.width=img.width;cv.height=img.height;
      cv.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
      $('#shotHint').textContent=img.width+'×'+img.height+' — click a pixel';
    };
    img.src=URL.createObjectURL(blob);
  }catch(e){$('#shotHint').textContent='capture failed';}
}
function shotOpen(){$('#shotWrap').style.display='';shotGrab();}
function shotClose(){$('#shotWrap').style.display='none';shotImg=null;}
$('#shotCv').addEventListener('click',async e=>{
  if(!shotImg)return;
  const cv=$('#shotCv'),r=cv.getBoundingClientRect();
  // Map the click from displayed size back to true pixel coordinates.
  const x=Math.floor((e.clientX-r.left)*(cv.width/r.width));
  const y=Math.floor((e.clientY-r.top)*(cv.height/r.height));
  const d=cv.getContext('2d',{willReadFrequently:true}).getImageData(x,y,1,1).data;
  const hex='#'+[d[0],d[1],d[2]].map(v=>v.toString(16).padStart(2,'0')).join('');
  await act('add_color',{hex});
  $('#shotHint').textContent='added '+hex+' at '+x+','+y;
  load();
});
function applyCapture(){act('apply_capture',{
  monitor:+$('#cap_monitor').value||0, obs_device_index:+$('#cap_obs').value||0,
  left:+$('#cap_left').value||0, top:+$('#cap_top').value||0,
  width:+$('#cap_width').value||0, height:+$('#cap_height').value||0}).then(()=>flash('capture applied'));}
function applyRoi(){act('apply_roi',{
  roi_x:+$('#roi_x').value||0, roi_y:+$('#roi_y').value||0,
  roi_w:+$('#roi_w').value||0, roi_h:+$('#roi_h').value||0})
  .then(()=>{flash('detection area applied');load();});}
function clearRoi(){['roi_x','roi_y','roi_w','roi_h'].forEach(id=>$('#'+id).value=0);applyRoi();}

/* ---- detection area ------------------------------------------------------
   Two ways to say where to look, because typing four desktop-pixel numbers
   means knowing where a window is before you can describe it:
   * "Select on screen" dims the desktop and takes a dragged box, the way a
     screen-capture tool does. Handled by the engine, since only it can draw
     over other windows.
   * "Crop a screenshot" drags the same box over a frozen frame in the panel,
     for when reaching across the screen is the hard part. */
function pickRegion(what){
  act('pick_region',{what}).then(()=>flash(
    'drag a box on the screen — Esc cancels'));
}

let cropImg=null, cropDrag=null;
async function cropGrab(){
  $('#cropHint').textContent='grabbing…';
  try{
    const r=await fetch('/api/screenshot?t='+Date.now());
    if(!r.ok){$('#cropHint').textContent='capture failed — check Capture source';return;}
    const img=new Image();
    img.onload=()=>{
      cropImg=img;
      const cv=$('#cropCv');cv.width=img.width;cv.height=img.height;
      cv.getContext('2d').drawImage(img,0,0);
      $('#cropHint').textContent=img.width+'×'+img.height+' — drag to crop';
      drawCropSel();
    };
    img.src=URL.createObjectURL(await r.blob());
  }catch(e){$('#cropHint').textContent='capture failed';}
}
function cropOpen(){$('#cropWrap').style.display='';cropGrab();}
function cropClose(){$('#cropWrap').style.display='none';cropImg=null;}
/* Frame pixels -> displayed pixels. The canvas is scaled to the card width, so
   every coordinate has to cross that ratio in one direction or the other. */
function cropScale(){const cv=$('#cropCv');
  return cv.width? cv.getBoundingClientRect().width/cv.width : 1;}
function drawCropSel(){
  const sel=$('#cropSel'), k=cropScale();
  const w=+S.roi_w||0, h=+S.roi_h||0;
  if(!cropImg||w<=0||h<=0){sel.style.display='none';return;}
  sel.style.display='';
  sel.style.left=((+S.roi_x||0)*k)+'px'; sel.style.top=((+S.roi_y||0)*k)+'px';
  sel.style.width=(w*k)+'px'; sel.style.height=(h*k)+'px';
}
(function wireCrop(){
  const box=$('#cropBox'), sel=$('#cropSel');
  const at=e=>{const r=$('#cropCv').getBoundingClientRect();
    return [e.clientX-r.left, e.clientY-r.top];};
  box.addEventListener('pointerdown',e=>{
    if(!cropImg)return;
    box.setPointerCapture(e.pointerId);
    cropDrag=at(e); sel.style.display='';
    sel.style.left=cropDrag[0]+'px';sel.style.top=cropDrag[1]+'px';
    sel.style.width='0px';sel.style.height='0px';
  });
  box.addEventListener('pointermove',e=>{
    if(!cropDrag)return;
    const [x,y]=at(e);
    sel.style.left=Math.min(cropDrag[0],x)+'px';
    sel.style.top=Math.min(cropDrag[1],y)+'px';
    sel.style.width=Math.abs(x-cropDrag[0])+'px';
    sel.style.height=Math.abs(y-cropDrag[1])+'px';
  });
  box.addEventListener('pointerup',e=>{
    if(!cropDrag)return;
    const [x,y]=at(e), k=cropScale(), s=cropDrag; cropDrag=null;
    const x0=Math.min(s[0],x)/k, y0=Math.min(s[1],y)/k;
    const w=Math.abs(x-s[0])/k, h=Math.abs(y-s[1])/k;
    if(w<6||h<6){drawCropSel();flash('too small — drag a bigger box');return;}
    $('#roi_x').value=Math.round(x0);$('#roi_y').value=Math.round(y0);
    $('#roi_w').value=Math.round(w); $('#roi_h').value=Math.round(h);
    applyRoi();
  });
})();
function applyHotkeys(){act('apply_hotkeys',{show:$('#hk_show').value.trim(),
  pull:$('#hk_pull').value.trim(), trigger:$('#hk_trigger').value.trim()})
  .then(()=>flash('hotkeys applied'));}
function setTrigger(t){$('#hk_trigger').value=t;applyHotkeys();flash('click set to '+t);}
async function record(which){
  // The click trigger may legitimately be a mouse button; the panel/toggle
  // hotkeys are keyboard combos, so those keep the combo-aware reader.
  const wantMouse = which==='trigger';
  flash(wantMouse?'press the mouse button or key… (Esc cancels)'
                 :'press any key or combo…');
  const r=await act('record_hotkey',wantMouse?{mouse:true}:{});
  if(r&&r.hotkey){
    const el=which==='show'?$('#hk_show'):which==='trigger'?$('#hk_trigger'):$('#hk_pull');
    el.value=r.hotkey;applyHotkeys();flash('bound: '+r.hotkey);}
  else flash("recording needs the 'keyboard' package");}
function quit(){act('quit');flash('quitting — you can close this tab');}

// ------------------------------------------------------------ saved configs
function saveConfig(){act('save_config',{name:$('#cfg_name').value.trim()}).then(r=>{
  if(r&&r.code){flash('saved as '+r.code);$('#cfg_name').value='';load();}
  else flash('save failed');});}
function loadConfigCode(){const c=$('#cfg_code').value.trim();if(!c)return;
  act('load_config',{code:c}).then(r=>{
    flash(r&&r.ok?('config '+c.toUpperCase()+' loaded'):'code not found');load();});}
function loadCfg(code){act('load_config',{code}).then(r=>{
  flash(r&&r.ok?('config '+code+' loaded'):'load failed');load();});}
function delCfg(code){act('delete_config',{code}).then(()=>{flash(code+' deleted');load();});}
function copyCode(code){
  (navigator.clipboard?navigator.clipboard.writeText(code):Promise.reject())
    .then(()=>flash(code+' copied'),()=>flash(code));}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
let cfgSig='';
function renderConfigs(){
  const box=$('#cfgList'); const list=S.configs||[];
  const sig=JSON.stringify(list);
  if(sig===cfgSig)return; cfgSig=sig;   // don't rebuild rows mid-click
  box.innerHTML='';
  if(!list.length){box.innerHTML='<div class="empty">no saved configs yet — save your current setup above</div>';return;}
  list.forEach(c=>{
    const row=document.createElement('div');row.className='cfg';
    const when=c.created?new Date(c.created*1000)
      .toLocaleString([],{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'';
    row.innerHTML='<span class="code" title="click to copy">'+c.code+'</span>'+
      '<span class="nm">'+(c.name?esc(c.name):'<i>unnamed</i>')+'</span>'+
      '<span class="dt">'+when+'</span>'+
      '<button class="btn mini" data-a="load">Load</button>'+
      '<button class="btn mini del" data-a="del" title="delete">✕</button>';
    row.querySelector('.code').onclick=()=>copyCode(c.code);
    row.querySelector('[data-a=load]').onclick=()=>loadCfg(c.code);
    row.querySelector('[data-a=del]').onclick=()=>delCfg(c.code);
    box.appendChild(row);});
}

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
  $('#attractRow').style.opacity=bp?'1':'.4';
  $('#attractRow').style.pointerEvents=bp?'auto':'none';
  $('#regionHint').textContent=bp?'':'Regions apply only with body-part detection on.';
}
function render(){
  // status
  $('#fps').textContent=(S.target_found?'● ':'')+(S.fps||0)+' fps';
  $('#dot').classList.toggle('live',!!S.target_found);
  // A low number while guidance is off is the deliberate idle tick, not a
  // fault — saying so stops it reading as "detection is broken".
  const _f=Math.round(S.fps||0);
  $('#statFps').textContent = S.pull_enabled
    ? _f+'/s'+(S.roi_following?' · following':'')
    : _f+'/s · idle';
  if(S.version)$('#ver').textContent='v'+S.version;
  // Target vs achieved: the scan rate is a ceiling, not a promise — if a grab
  // takes longer than the target period the loop simply runs slower, and
  // seeing both numbers is what makes that obvious rather than mysterious.
  const hz=S.display_hz||0, want=S.scan_fps||0, got=S.fps||0;
  const sh=$('#scanHint');
  if(sh) sh.innerHTML = want>0
    ? `Target <b>${want}/s</b> (manual) · achieving <b>${got}/s</b>. `+
      `Your display refreshes at <b>${hz} Hz</b>`+
      (want>hz?` — above that, scans re-read frames the screen hasn't redrawn yet.`:`.`)
    : `<b>Auto</b>: matching your display's <b>${hz} Hz</b> · achieving `+
      `<b>${got}/s</b>. Plug in a faster monitor and this follows it.`;
  const g=S.pointer_gain_measured, res=S.pointer_resolution||1;
  $('#gainNow').textContent=(g==null?'—':(g.toFixed(2)+'× per unit'));
  const pp=$('#ptrProfile');
  if(pp) pp.textContent=S.pointer_profile||'reading…';
  // At a high pointer speed one device unit is several pixels, so the pointer
  // physically cannot be placed closer than that. Saying so beats leaving it
  // looking like the aim is simply inaccurate.
  const pr=$('#ptrRes');
  if(pr) pr.innerHTML = res>2.0
    ? `One step of your mouse moves <b>${res.toFixed(1)} px</b>, so the pointer `+
      `settles within about that — the finest a high pointer speed allows.`
    : `One step of your mouse moves <b>${res.toFixed(2)} px</b> — fine enough `+
      `to land exactly on target.`;
  // Detection area readout.
  const rn=$('#roiNow');
  if(rn) rn.innerHTML = (S.roi_w>0&&S.roi_h>0)
    ? `Watching <b>${S.roi_w} × ${S.roi_h}</b> px at <b>${S.roi_x}, ${S.roi_y}</b>`
    : `Watching the <b>whole frame</b>`;
  if(S.region_pick) flash('drag a box on the screen — Esc cancels');
  drawCropSel();
  // Colour-match coverage: a selection loose enough to match most of the
  // screen produces confident, meaningless targets.
  const cov=S.mask_coverage, cv=$('#covNow');
  if(cv){
    cv.innerHTML = (cov==null)?'—':
      (cov>25 ? `<b style="color:#ff9a8a">${cov}% of the frame matches</b> — `+
                `too much to aim at. Lower Sensitivity, or pick a colour that `+
                `stands out more.`
              : `<b>${cov}%</b> of the frame matches your colours.`);
  }
  const st=$('#statTarget');
  st.textContent=S.target_found?'locked':'none';
  st.className='v '+(S.target_found?'ok':'bad');
  $('#statMode').textContent=({dwell:'Dwell',trigger:'Trigger',off:'Manual'})[S.click_mode]||'—';
  const on=!!S.pull_enabled, p=$('#power'), hold=S.activation_mode==='hold';
  p.innerHTML=hold?(on?'HOLDING&nbsp;— ACTIVE':'HOLD&nbsp;'+esc(S.hotkey_hold||'?').toUpperCase())
                  :('PULL&nbsp;'+(on?'ON':'OFF'));
  p.classList.toggle('on',on);
  // activation card
  $$('#actmode button').forEach(b=>b.classList.toggle('sel',b.dataset.am===(S.activation_mode||'toggle')));
  $('#holdRow').style.display=hold?'':'none';
  $('#actHint').textContent=hold
    ?'Pull is live only while the hold button is pressed. The toggle hotkey still works as an override.'
    :'Hotkey / button flips the pull on and off.';
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
  const sh2=$('#snapHint');
  if(sh2) sh2.innerHTML = (S.snap_radius>0)
    ? `Fixed <b>${S.snap_radius} px</b> circle. Slide to <b>0</b> to size it `+
      `from the target instead, which suits targets of changing size.`
    : `<b>Auto</b> — sized from the target itself (about a third of its narrow `+
      `side). This used to borrow the field-of-view circle, which was far too `+
      `big and dragged the aim toward whatever else was nearby.`;
  $('#clickHint').textContent=cm==='dwell'?'Clicks after holding on target.':
    cm==='trigger'?'Press the trigger key to click instantly.':
    'No auto-click — click manually.';
  renderRegions();renderColors();renderConfigs();
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
  set('#hk_trigger',S.hotkey_trigger);set('#hk_hold',S.hotkey_hold);
}
/* ---- plain-language help on every setting -------------------------------
   Written for someone who has never read the README: what it does and when to
   change it, no jargon. Keyed by the setting's data-key so adding a control
   never means hunting through the markup to attach its explanation. */
const TIPS={
  smoothness:"How gliding the pointer feels. Higher is smoother and calmer; lower reacts faster. If it feels floaty, lower it.",
  max_speed:"The fastest the pointer is ever allowed to travel. Lower it if the pointer feels like it lunges.",
  target_ema:"How much wobble is filtered out of the target. Higher holds steadier on something still. It eases off by itself when the target moves.",
  motion_response:"How quickly tracking reacts once the target starts moving. Raise this if the pointer trails behind moving things.",
  jitter_floor:"How firmly the pointer is held still when the target isn't moving. Raise it if the pointer shivers while resting on something.",
  precision_px:"How close to the target the pointer starts slowing down, so it settles gently instead of darting the last bit. Set 0 to turn off.",
  precision_slow:"How much it slows inside that zone. Lower is gentler and more precise, but takes a moment longer to arrive.",
  max_accel:"A limit on how sharply the pointer can speed up. Stops it lurching if the camera has a bad moment. Lower = calmer.",
  pointer_gain:"Only needed if the pointer still comes up short. The app reads your Windows mouse speed by itself first — try leaving this alone. Higher reaches further, lower reaches less.",
  pointer_gain_auto:"Read your Windows mouse speed and acceleration, and keep checking what your moves actually do. Leave this on — it is what keeps the pull the same on a slow mouse and a fast one.",
  show_roi:"Draw a dashed outline on screen showing the area being watched, so you can see it rather than work it out from numbers.",
  snap_radius:"How big a circle to look for the densest colour in. Leave at 0 to size it from the target automatically.",
  dwell_ms:"How long to rest on something before it clicks for you.",
  click_radius:"How close the pointer must be to count as resting on the target. Bigger is more forgiving.",
  click_interval_ms:"When repeat clicking is on, the gap between each click.",
  dwell_grace_ms:"If the colour flickers for a moment, keep counting instead of starting over. Raise it if clicks don't happen on a jumpy picture.",
  sensitivity:"How fussy colour matching is. Raise it if your target isn't spotted; lower it if it grabs the wrong things. Watch the percentage below — if it climbs past about a quarter of the frame, it is matching too much to aim at.",
  min_contour_area:"Ignore colour patches smaller than this, so specks and noise don't get chased.",
  detect_scale:"Detection quality vs effort. Lower is lighter on the computer; higher spots smaller things.",
  scan_fps:"How many times a second the screen is checked. Leave at 0 to match your monitor automatically — a screen can't show new pictures faster than its refresh rate, so scanning above it just sees the same picture twice. Set a number to cap it and free up the computer, or to go higher if you capture from OBS rather than the screen.",
  pull_radius:"The pointer is only guided toward colours inside this circle. Everything outside is ignored.",
  overlay_radius:"Just the size of the circle drawn on screen. Doesn't change behaviour.",
  snap_after_ms:"After resting on the colour this long, aim shifts to the thickest part of that target. Set 0 to do it straight away — better for things that keep moving.",
  part_attraction:"How strictly it aims at the exact body part. Lower blends toward the middle of the figure, which is steadier.",
};
/* The bubble lives on <body> and is positioned at hover time. Cards clip their
   contents, so anchoring it inside one cut it off; and the panel is fluid, so
   the room available above/left/right of an icon is only known on hover. */
function placeTip(i){
  const t=$('#tip');
  t.textContent=i.dataset.tip;
  t.classList.add('on');
  const r=i.getBoundingClientRect();
  const tw=t.offsetWidth, th=t.offsetHeight, pad=8;
  let left=r.left-4;
  if(left+tw>innerWidth-pad) left=innerWidth-pad-tw;   // keep the right edge in
  if(left<pad) left=pad;
  let top=r.top-th-9;
  if(top<pad) top=r.bottom+9;                          // no room above: go below
  // Neither side fits for the tallest bubbles low on the page, so clamp into
  // view as a last resort rather than letting one run off the bottom.
  if(top+th>innerHeight-pad) top=innerHeight-pad-th;
  if(top<pad) top=pad;
  t.style.left=left+'px';
  t.style.top=top+'px';
}
function attachTips(){
  document.querySelectorAll('[data-key]').forEach(el=>{
    const tip=TIPS[el.dataset.key];if(!tip)return;
    const row=el.closest('.row,.toggle');if(!row)return;
    const host=row.querySelector('label,span');
    if(!host||host.querySelector('.i'))return;
    const i=document.createElement('span');
    i.className='i';i.textContent='i';i.dataset.tip=tip;
    // Whitespace first, so the label can wrap between text and bubble rather
    // than being forced into one over-wide unbreakable run.
    host.appendChild(document.createTextNode(' '));
    i.addEventListener('mouseenter',()=>placeTip(i));
    i.addEventListener('mouseleave',()=>$('#tip').classList.remove('on'));
    host.appendChild(i);
  });
}

/* ---- patch notes --------------------------------------------------------
   Kept here so the panel is the single place a user looks; each entry says
   what changed in terms of what they would have noticed. */
const NOTES=[
 {v:"1.0.7",t:"Snap fixed, any mouse sensitivity, drag-a-box area",items:[
   ["Best-coverage snap no longer ruins the aim","The snap circle was borrowing your field-of-view circle — 250px across by default — so it was answering 'where is this colour thickest' about half the screen instead of about your target. With two figures 220px apart it settled 47px off the one you were locked on, and at some spacings it aimed between the two, at neither. It now only looks inside the target it is already locked on, so it can never walk onto something else, and it has its own size setting that works itself out from the target by default."],
   ["Works the same on a fast mouse and a slow one","Windows shrinks or stretches every movement by your mouse-speed setting — from a thirty-second up to three and a half times — and 'enhance pointer precision' changes that again depending on how fast the pointer is already moving. It now reads those settings directly instead of guessing and correcting, so the very first movement is the right size. Wasted back-and-forth travel at the highest setting dropped from 96% down to 2%, and the shaking on arrival is gone at both ends."],
   ["Extra gain was backwards","The slider that says 'raise this if it still under-reaches' was making it reach less, not more."],
   ["The top half of the Sensitivity slider was unusable","Past about 24 it matched anything roughly the right colour no matter how washed out or nearly black — over half the screen at 28, and above 36 your actual target disappeared into the mess. The whole slider works now, and the panel tells you what percentage of the screen your colours are matching."],
   ["Pick the detection area by dragging a box","Instead of typing four numbers, 'Select on screen' dims the desktop and lets you drag over the part you want watched, like a snipping tool. It shows the size as you drag, Esc cancels, and it works across several monitors. You can also crop a screenshot inside the panel, and the area is outlined on screen so you can see it."],
   ["Numbers were off the edge of the panel","Every slider's value was 94px past the right edge of its card and cut off — sliders refuse to shrink past a certain width, so the row simply did not fit. Each row is now two lines: name and value on top, slider underneath. Checked at every window size from 400px to 1600px."],
 ]},
 {v:"1.0.6",t:"Five times faster searching, and a tidier panel",items:[
   ["Much faster when looking for a target","Before locking on, it was grabbing the whole screen every time — about 67ms — so it only managed around 10 checks a second no matter what the scan rate said. It now only looks at the area around your pointer, since anything outside the circle is ignored anyway. Measured 10 → 52 checks a second."],
   ["The 'Detection' number now says when it's idle","A low number with guidance switched off is the deliberate slow tick, not a fault. It now says 'idle' so it doesn't look broken."],
   ["Tabs instead of one long wall","The panel had fourteen cards on screen at once. They're now grouped into Guidance, Targeting, Clicking, Detection and Setup, and it remembers which one you were on."],
 ]},
 {v:"1.0.5",t:"Scan rate is now adjustable",items:[
   ["Set your own scan rate","A new Scan rate slider in Capture source. Leave it at 0 and it matches your monitor automatically — including 144Hz, 165Hz and 240Hz screens, and it follows along if you plug a different one in while it's running."],
   ["Why 0 is usually right","A screen only draws new pictures at its refresh rate, so checking more often than that just sees the same picture twice — cost with nothing gained. Set a number if you want to cap it and free up the computer, or to go higher when you capture from OBS instead of the screen, since OBS runs at its own rate."],
   ["It shows you both numbers","The panel shows what you asked for and what it's actually managing, so if your computer can't keep up you can see that rather than guess."],
 ]},
 {v:"1.0.4",t:"Four times the scan rate",items:[
   ["Much faster scanning","Grabbing the whole screen cost about 67ms — that alone held everything to roughly 15 looks per second, however little work the rest did. While locked on, only the small area around your target is grabbed now, which is about 4× quicker and reaches 60 per second: the most your screen can actually show."],
   ["Why not higher","A 60Hz screen only draws 60 new pictures a second, so looking more often than that just sees the same picture twice. On a 120Hz or 144Hz screen this will go faster on its own — nothing to change."],
 ]},
 {v:"1.0.3",t:"Aim line, plain-English help, and two real fixes",items:[
   ["Aim guide line","A cyan line now runs from your pointer to the exact pixel it's steering for, so you can move with it instead of fighting it by accident."],
   ["Dwell clicks that never fired","If the colour flickered for even one frame the click timer silently restarted, so on a jumpy picture it could never finish. It now rides out brief dropouts."],
   ["Record button binding the wrong key","Recording only ever watched the keyboard, so pressing a mouse button left it waiting — and it then grabbed whatever key you pressed next, usually the Windows key. It now records mouse buttons properly."],
   ["Target follow","Once locked on, only a small window around the target is scanned, at full quality — about 17× less work per frame, and a more precise aim point."],
   ["Info buttons","Every setting has an 'i' explaining what it does in plain language."],
 ]},
 {v:"1.0.2",t:"Hold rewritten, low-sensitivity support, spasm damping",items:[
   ["Hold button works","Hold was going through a system-wide event hook that failed three different silent ways. It now reads the button directly, and tells you if a button can't be used instead of doing nothing."],
   ["Low mouse sensitivity","Windows shrinks the app's movements to match your mouse speed setting, so on a low setting the pull crawled. It now measures that and compensates."],
   ["Precision zone","The pointer eases off close to the target instead of darting the last stretch."],
   ["Steadier under stress","A limit on how sharply the pointer can speed up, so one bad camera frame can't fling it."],
   ["Screenshot colour picker","Freeze the screen and click the exact pixel, instead of chasing a live eyedropper."],
 ]},
 {v:"1.0.1",t:"Tracking overhaul",items:[
   ["Spasms on direction changes","The speed estimate lagged about a tenth of a second, so on anything moving back and forth the pointer was thrown the wrong way each time it turned. Fixed at the source."],
   ["Consistent at any frame rate","Smoothing used to depend on how fast the camera ran, so the same settings felt different on different machines."],
   ["Instant snap","Snap delay can be set to 0 for targets that keep moving."],
 ]},
];
function renderNotes(){
  const box=document.getElementById('notes');if(!box||box.dataset.done)return;
  box.dataset.done='1';
  box.innerHTML=NOTES.map(r=>`<div class="rel"><h3>${esc(r.t)}
    <span class="tagv">v${esc(r.v)}</span></h3><ul>`+
    r.items.map(([h,b])=>`<li><b>${esc(h)}</b> — ${esc(b)}</li>`).join('')+
    `</ul></div>`).join('');
}

/* ---- section tabs -------------------------------------------------------
   Fourteen cards at once was too much to take in. Grouping them behind tabs
   keeps the status header plus only the controls you're using on screen. The
   choice is remembered, so reopening the panel puts you back where you were. */
function showTab(name){
  document.querySelectorAll('.card[data-tab]').forEach(c=>
    c.classList.toggle('show', c.dataset.tab===name));
  document.querySelectorAll('#tabs button').forEach(b=>{
    const on=b.dataset.t===name;
    b.classList.toggle('sel',on);
    b.setAttribute('aria-selected',on?'true':'false');
  });
  try{localStorage.setItem('curse.tab',name);}catch(e){}
}
function initTabs(){
  const tabs=document.getElementById('tabs');
  if(!tabs||tabs.dataset.done)return;
  tabs.dataset.done='1';
  tabs.querySelectorAll('button').forEach(b=>
    b.onclick=()=>showTab(b.dataset.t));
  let want='guide';
  try{const s=localStorage.getItem('curse.tab');
      if(s&&tabs.querySelector('[data-t="'+s+'"]'))want=s;}catch(e){}
  showTab(want);
}

function bootDone(){
  const b=document.getElementById('boot');
  if(!b||b.classList.contains('gone'))return;
  b.classList.add('gone');
  document.body.classList.remove('booting');
  setTimeout(()=>b.remove(),600);
}

async function load(){S=await fetch('/api/state').then(r=>r.json());fillStatic();render();
  attachTips();renderNotes();initTabs();
  if(S.version)$('#verNote').textContent='v'+S.version;
  bootDone();}
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
