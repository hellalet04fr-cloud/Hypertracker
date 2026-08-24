"""Genere l'application mobile HyperTracker. Aucun calcul scientifique ici :
les donnees sont deja precalculees par prep_app.py."""
import json, os

D = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
DATA = json.load(open(os.path.join(D, "app_data.json")))

TPL = r"""<title>HyperTracker</title>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>
/* Terminal sombre assume : un seul monde visuel, chaque couleur peinte explicitement.
   Les couleurs ne decorent pas — elles transportent une information. */
:root{
  --bg:#080b10; --surf:#111620; --surf2:#171d29; --surf3:#1e2532;
  --line:#232b3a; --line2:#2e3849;
  --ink:#e9edf4; --soft:#8b96a9; --faint:#59637a;
  --pos:#2fe0a4; --neg:#ff5f6d; --acc:#4d9dff; --warn:#ffb545;
  --pos-d:#0f2b23; --neg-d:#2c1418; --acc-d:#0f2138; --warn-d:#2b2110;
  --nav-h:calc(58px + env(safe-area-inset-bottom));
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{overscroll-behavior-y:none}
body{margin:0;background:var(--bg);color:var(--ink);
  font:500 15px/1.45 Manrope,system-ui,-apple-system,sans-serif;
  -webkit-font-smoothing:antialiased;padding-bottom:var(--nav-h)}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}

/* ---------- header ---------- */
header{position:sticky;top:0;z-index:40;background:rgba(8,11,16,.92);
  backdrop-filter:blur(14px);border-bottom:1px solid var(--line);
  padding:calc(env(safe-area-inset-top) + 12px) 16px 12px}
.hrow{display:flex;align-items:center;justify-content:space-between;gap:10px}
.hrow>div{min-width:0}
.hrow>div:last-child{flex:0 0 auto}
.brand{font:800 20px/1 Manrope,sans-serif;letter-spacing:-.02em}
.brand i{font-style:normal;color:var(--acc)}
.hsub{font:500 11px/1 "IBM Plex Mono",monospace;color:var(--faint);
  letter-spacing:.09em;text-transform:uppercase;margin-top:5px}
.pill{display:inline-flex;align-items:center;gap:5px;font:600 10.5px/1 "IBM Plex Mono",monospace;
  padding:5px 8px;border-radius:6px;border:1px solid;letter-spacing:.04em;white-space:nowrap}
.pill.d{color:var(--warn);background:var(--warn-d);border-color:#4a3a18}
.pill.o{color:var(--pos);background:var(--pos-d);border-color:#1c4a3c}
.pill.i{color:var(--soft);background:var(--surf2);border-color:var(--line2)}

/* ---------- vues ---------- */
main{padding:14px 14px 20px;max-width:640px;margin:0 auto}
.view{display:none}.view.on{display:block}

/* ---------- recherche + filtres ---------- */
.search{display:flex;align-items:center;gap:9px;background:var(--surf);
  border:1px solid var(--line);border-radius:11px;padding:12px 13px;margin-bottom:12px}
.search input{flex:1;background:none;border:0;outline:none;color:var(--ink);
  font:500 15px Manrope,sans-serif;min-width:0}
.search input::placeholder{color:var(--faint)}
.chips{display:flex;gap:7px;overflow-x:auto;padding-bottom:3px;margin-bottom:12px;
  scrollbar-width:none}
.chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;padding:8px 13px;border-radius:9px;background:var(--surf);
  border:1px solid var(--line);color:var(--soft);font:600 12.5px Manrope,sans-serif;
  min-height:38px;transition:.15s}
.chip.on{background:var(--acc-d);border-color:#2d5b8f;color:var(--acc)}
.chip.off{opacity:.32;cursor:default}
.frow{display:flex;gap:8px;align-items:center;margin-bottom:12px}
.fbtn{flex:0 0 auto;padding:8px 12px;border-radius:9px;background:var(--surf);
  border:1px solid var(--line);color:var(--soft);font:600 12.5px Manrope;min-height:38px}
.fbtn.on{color:var(--acc);border-color:#2d5b8f}
.count{margin-left:auto;font:500 12px "IBM Plex Mono",monospace;color:var(--faint)}
.panel{background:var(--surf);border:1px solid var(--line);border-radius:12px;
  padding:14px;margin-bottom:12px;display:none}
.panel.on{display:block}
.frange{margin-bottom:14px}
.frange:last-child{margin-bottom:0}
.frange label{display:flex;justify-content:space-between;font:600 12px Manrope;
  color:var(--soft);margin-bottom:7px}
.frange label b{color:var(--acc);font-family:"IBM Plex Mono",monospace}
input[type=range]{width:100%;accent-color:var(--acc);height:26px}

/* ---------- carte wallet ---------- */
.card{width:100%;text-align:left;display:block;background:var(--surf);
  border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:10px;
  transition:.15s}
.card:active{transform:scale(.985);background:var(--surf2)}
.card.top{border-color:#2d5b8f}
.chead{display:flex;align-items:flex-start;gap:11px;margin-bottom:12px}
.rank{flex:0 0 auto;width:34px;height:34px;border-radius:9px;background:var(--surf3);
  display:grid;place-items:center;font:700 13px "IBM Plex Mono",monospace;color:var(--soft)}
.rank.g{background:var(--acc-d);color:var(--acc)}
.cid{flex:1;min-width:0}
.addr{font:600 13.5px "IBM Plex Mono",monospace;color:var(--ink);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meta{font:500 11.5px/1.4 Manrope;color:var(--faint);margin-top:3px;
  min-width:0;overflow-wrap:anywhere}
.sbox{flex:0 0 auto;text-align:right}
.sval{font:700 21px/1 "IBM Plex Mono",monospace}
.slab{font:600 9.5px/1 "IBM Plex Mono",monospace;color:var(--faint);
  letter-spacing:.08em;margin-top:4px}
.spk{width:100%;height:30px;display:block;margin-bottom:10px;opacity:.9}
.bar{height:5px;background:var(--surf3);border-radius:3px;overflow:hidden;margin-bottom:12px}
.bar i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,#2d5b8f,var(--acc))}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}
.kv{min-width:0}
.kv .k{font:600 9.5px/1 "IBM Plex Mono",monospace;color:var(--faint);
  letter-spacing:.06em;text-transform:uppercase}
.kv .v{font:600 14px/1.2 "IBM Plex Mono",monospace;margin-top:5px;
  white-space:nowrap;overflow:visible}
.pos{color:var(--pos)}.neg{color:var(--neg)}.na{color:var(--faint);font-weight:500}
.cfoot{display:flex;align-items:center;justify-content:space-between;gap:8px;
  flex-wrap:wrap;margin-top:12px;padding-top:11px;border-top:1px solid var(--line)}
.cfoot .meta{min-width:0;flex:1 1 auto;margin-top:0}
.go{flex:0 0 auto;font:700 12.5px Manrope;color:var(--acc)}

/* ---------- detail ---------- */
#detail{position:fixed;inset:0;z-index:60;background:var(--bg);overflow-y:auto;
  display:none;padding-bottom:calc(24px + env(safe-area-inset-bottom))}
#detail.on{display:block}
.dhead{position:sticky;top:0;z-index:5;background:rgba(8,11,16,.94);
  backdrop-filter:blur(14px);border-bottom:1px solid var(--line);
  padding:calc(env(safe-area-inset-top) + 11px) 14px 11px}
.back{display:inline-flex;align-items:center;gap:7px;font:700 14px Manrope;
  color:var(--acc);min-height:40px}
.dbody{padding:16px 14px;max-width:640px;margin:0 auto}
.dtitle{font:800 23px/1.15 Manrope;letter-spacing:-.02em}
.daddr{font:500 12.5px "IBM Plex Mono",monospace;color:var(--soft);
  margin-top:7px;word-break:break-all;line-height:1.5}
.acts{display:flex;gap:8px;margin:13px 0 18px;flex-wrap:wrap}
.act{flex:1 1 calc(50% - 4px);min-width:0;min-height:44px;display:inline-flex;align-items:center;
  justify-content:center;gap:7px;padding:11px;border-radius:10px;
  background:var(--surf2);border:1px solid var(--line2);font:700 13px Manrope}
.act.p{background:var(--acc-d);border-color:#2d5b8f;color:var(--acc)}
.act.w{background:var(--warn-d);border-color:#4a3a18;color:var(--warn)}
.hero{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:18px}
.hcard{background:var(--surf);border:1px solid var(--line);border-radius:13px;padding:15px}
.hcard .k{font:600 10px/1 "IBM Plex Mono",monospace;color:var(--faint);
  letter-spacing:.09em;text-transform:uppercase}
.hcard .v{font:700 30px/1 "IBM Plex Mono",monospace;margin:9px 0 5px}
.hcard .s{font:500 11.5px Manrope;color:var(--soft)}
h3{font:700 12px/1 "IBM Plex Mono",monospace;color:var(--faint);letter-spacing:.11em;
  text-transform:uppercase;margin:24px 0 11px}
.sect{background:var(--surf);border:1px solid var(--line);border-radius:13px;padding:15px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:13px}
.g2 .k{font:600 10px/1 "IBM Plex Mono",monospace;color:var(--faint);
  letter-spacing:.06em;text-transform:uppercase}
.g2 .v{font:600 16px/1.2 "IBM Plex Mono",monospace;margin-top:5px}
.li{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid var(--line)}
.li:last-child{border:0;padding-bottom:0}
.li:first-child{padding-top:0}
.li i{flex:0 0 auto;font-style:normal;font-size:14px;line-height:1.5}
.li span{font:500 13.5px/1.5 Manrope;color:var(--soft)}
.li b{color:var(--ink);font-weight:600}
canvas{width:100%;display:block;touch-action:pan-y}
.legend{display:flex;justify-content:space-between;font:500 11px "IBM Plex Mono",monospace;
  color:var(--faint);margin-top:9px}

/* ---------- comparaison ---------- */
.ctable{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;min-width:340px}
th,td{padding:11px 10px;text-align:right;font:600 13px "IBM Plex Mono",monospace;
  border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left;font-family:Manrope;font-size:12.5px;
  color:var(--faint);position:sticky;left:0;background:var(--surf)}
thead th{font-size:11px;color:var(--acc);letter-spacing:.04em}
.empty{text-align:center;padding:52px 20px;color:var(--faint)}
.empty div:first-child{font-size:38px;margin-bottom:14px;opacity:.5}
.empty p{font:500 14px/1.6 Manrope;max-width:30ch;margin:9px auto 0}

/* ---------- nav ---------- */
nav{position:fixed;left:0;right:0;bottom:0;z-index:50;display:grid;
  grid-template-columns:repeat(4,1fr);background:rgba(8,11,16,.96);
  backdrop-filter:blur(18px);border-top:1px solid var(--line);
  padding-bottom:env(safe-area-inset-bottom)}
nav button{display:flex;flex-direction:column;align-items:center;gap:4px;
  padding:9px 4px;color:var(--faint);min-height:56px;justify-content:center}
nav button.on{color:var(--acc)}
nav i{font-style:normal;font-size:19px;line-height:1}
nav span{font:700 10px Manrope;letter-spacing:.01em}
.toast{position:fixed;left:50%;bottom:calc(var(--nav-h) + 16px);transform:translateX(-50%) translateY(14px);
  background:var(--surf3);border:1px solid var(--line2);color:var(--ink);
  padding:11px 17px;border-radius:11px;font:600 13px Manrope;z-index:90;
  opacity:0;pointer-events:none;transition:.22s}
.toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
/* Sous 392px — iPhone SE, mini, 12/13 mini — quatre colonnes deviennent trop
   etroites pour les valeurs les plus longues (+$13.9K). On passe a deux lignes
   plutot que de rogner un chiffre : un montant tronque est pire qu'un montant
   qui prend deux lignes. */
@media (max-width:392px){
  main{padding:12px 10px 18px}
  .card{padding:12px}
  .grid{grid-template-columns:repeat(2,1fr);gap:11px 9px}
  .sval{font-size:19px}
  .hcard .v{font-size:26px}
  .dtitle{font-size:21px}
  .g2{gap:11px}
  nav span{font-size:9.5px}
}
@media (max-width:340px){
  .hero,.g2{grid-template-columns:1fr}
  .brand{font-size:18px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style>

<header>
  <div class="hrow">
    <div>
      <div class="brand">Hyper<i>Tracker</i></div>
      <div class="hsub">Wallet Intelligence</div>
    </div>
    <div style="text-align:right">
      <span class="pill i" id="pverdict">—</span>
      <div class="hsub" style="margin-top:6px" id="pmaj"></div>
    </div>
  </div>
</header>

<main>
  <!-- ============ CLASSEMENT ============ -->
  <section class="view on" id="v-rank">
    <div class="search">
      <span style="color:var(--faint)">⌕</span>
      <input id="q" placeholder="Rechercher une adresse ou un rang" autocomplete="off"
             autocapitalize="off" spellcheck="false">
    </div>
    <div class="chips" id="sorts"></div>
    <div class="frow">
      <button class="fbtn" id="ftoggle">⚙ Filtres</button>
      <span class="count" id="count"></span>
    </div>
    <div class="panel" id="fpanel"></div>
    <div id="list"></div>
  </section>

  <!-- ============ RECHERCHE ============ -->
  <section class="view" id="v-search">
    <div class="search">
      <span style="color:var(--faint)">⌕</span>
      <input id="q2" placeholder="Coller une adresse 0x… ou un rang" autocomplete="off"
             autocapitalize="off" spellcheck="false">
    </div>
    <div id="sres"></div>
  </section>

  <!-- ============ WATCHLIST ============ -->
  <section class="view" id="v-watch"><div id="wlist"></div></section>

  <!-- ============ COMPARER ============ -->
  <section class="view" id="v-cmp"><div id="cmp"></div></section>
</main>

<div id="detail"></div>

<nav>
  <button data-v="rank" class="on"><i>🏆</i><span>Classement</span></button>
  <button data-v="search"><i>🔎</i><span>Recherche</span></button>
  <button data-v="watch"><i>⭐</i><span>Watchlist</span></button>
  <button data-v="cmp"><i>📊</i><span>Comparer</span></button>
</nav>
<div class="toast" id="toast"></div>

<script>
const DB = %%DATA%%;
const W = DB.wallets, META = DB.meta;
const byA = Object.fromEntries(W.map(w => [w.a, w]));

/* ---------- stockage local, toujours defensif ---------- */
const S = {
  get(k, d){ try{ const v = localStorage.getItem('ht_'+k); return v ? JSON.parse(v) : d; }catch(e){ return d; } },
  set(k, v){ try{ localStorage.setItem('ht_'+k, JSON.stringify(v)); }catch(e){} }
};
let watch = S.get('watch', []), sel = S.get('sel', []);

/* ---------- format ---------- */
const NA = '<span class="na">N/A</span>';
const money = v => v == null ? NA : (v >= 0 ? '+' : '−') + '$' +
  (Math.abs(v) >= 1000 ? (Math.abs(v)/1000).toFixed(1) + 'K' : Math.abs(v).toFixed(0));
const sign = v => v == null ? '' : (v >= 0 ? 'pos' : 'neg');
const num = (v, d = 2) => v == null ? NA : v.toFixed(d);
const pct = v => v == null ? NA : v.toFixed(0) + ' %';
const short = a => a.slice(0, 8) + '…' + a.slice(-6);
const dt = t => t ? new Date(t).toLocaleDateString('fr-FR', {day:'2-digit', month:'short', year:'2-digit'}) : '—';

function toast(m){
  const t = document.getElementById('toast');
  t.textContent = m; t.classList.add('on');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('on'), 1700);
}
function copie(a){
  const ok = () => toast('✓ Adresse copiée');
  if (navigator.clipboard) navigator.clipboard.writeText(a).then(ok).catch(() => fallback(a, ok));
  else fallback(a, ok);
}
function fallback(a, ok){
  try{ const i = document.createElement('textarea'); i.value = a;
    i.style.position='fixed'; i.style.opacity='0'; document.body.appendChild(i);
    i.select(); document.execCommand('copy'); document.body.removeChild(i); ok();
  }catch(e){ toast('Copie indisponible'); }
}

/* ---------- statut des donnees ---------- */
function statut(w){
  if (!w.obs) return ['d', '🟡 DERIVED'];
  if (w.obs.suffisant) return ['o', '🟢 OBSERVED'];
  return ['i', '⚠️ PARTIEL'];
}

/* ---------- tri et filtres ---------- */
const SORTS = [
  ['score', 'Top score',   (a,b) => b.score - a.score],
  ['perf',  'Performance', (a,b) => b.post - a.post],
  ['conf',  'Confiance',   (a,b) => b.conf - a.conf || b.qualite - a.qualite],
  ['pnl',   'PnL',         (a,b) => b.pnl - a.pnl],
  ['stab',  'Stabilité',   (a,b) => a.conc - b.conc || b.n - a.n],
  ['trades','Trades',      (a,b) => b.n - a.n]
];
let tri = 'score', q = '';
const F = { score:0, n:0, conf:0, dd:1e9, conc:1, obs:'all' };

const FDEF = [
  ['score', 'Score minimum',        0, 100, 1, v => v],
  ['n',     'Trades minimum',       0, 400, 10, v => v],
  ['conf',  'Confiance minimum',    0, 100, 5, v => v + ' %'],
  ['conc',  'Concentration max',    0.05, 1, 0.05, v => v.toFixed(2)]
];

function filtre(){
  let r = W.filter(w =>
    w.score >= F.score && w.n >= F.n && w.conf >= F.conf &&
    (w.conc == null || w.conc <= F.conc) &&
    (F.obs === 'all' || (F.obs === 'obs' ? !!w.obs : !w.obs)));
  if (q){
    const s = q.toLowerCase().trim();
    r = r.filter(w => w.a.toLowerCase().includes(s) || String(w.rang) === s);
  }
  return r.sort(SORTS.find(x => x[0] === tri)[2]);
}

/* ---------- carte ---------- */
function carte(w){
  const [cls, lab] = statut(w);
  return `<button class="card${w.rang <= 5 ? ' top' : ''}" onclick="ouvre('${w.a}')">
    <div class="chead">
      <div class="rank${w.rang <= 3 ? ' g' : ''}">${w.rang}</div>
      <div class="cid">
        <div class="addr">${short(w.a)}</div>
        <div class="meta">${w.n} trades · ${w.jours} j</div>
        <div class="meta" style="margin-top:5px"><span class="pill ${cls}" style="padding:2px 6px;font-size:9px">${lab}</span></div>
      </div>
      <div class="sbox">
        <div class="sval" style="color:var(--acc)">${w.score.toFixed(1)}</div>
        <div class="slab">SCORE</div>
      </div>
    </div>
    ${spark(w)}
    <div class="bar"><i style="width:${w.score}%"></i></div>
    <div class="grid">
      <div class="kv"><div class="k">PnL</div><div class="v ${sign(w.pnl)}">${money(w.pnl)}</div></div>
      <div class="kv"><div class="k">Win rate</div><div class="v">${pct(w.win)}</div></div>
      <div class="kv"><div class="k">Sharpe</div><div class="v">${num(w.sr)}</div></div>
      <div class="kv"><div class="k">Confiance</div><div class="v">${w.conf} %</div></div>
    </div>
    <div class="cfoot">
      <span class="meta">Conc. ${num(w.conc)} · DD ${money(-Math.abs(w.dd || 0))}</span>
      <span class="go">Voir →</span>
    </div>
  </button>`;
}

/* ---------- sparkline : SVG, pas canvas — 60 cartes a l'ecran ---------- */
function spark(w){
  if (!w.sp || w.sp.length < 3) return '<div style="height:30px"></div>';
  const L = 100, H = 26, n = w.sp.length;
  const pts = w.sp.map((v, i) => `${(i / (n - 1) * L).toFixed(1)},${(H - 2 - v * (H - 4)).toFixed(1)}`).join(' ');
  const c = w.pnl >= 0 ? '#2fe0a4' : '#ff5f6d';
  return `<svg class="spk" viewBox="0 0 ${L} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <polyline points="${pts}" fill="none" stroke="${c}" stroke-width="1.6"
      stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`;
}

/* ---------- rendu classement ---------- */
function rendu(){
  const r = filtre();
  document.getElementById('count').textContent = r.length + ' / ' + W.length + ' wallets';
  document.getElementById('list').innerHTML = r.length
    ? r.slice(0, 60).map(carte).join('') +
      (r.length > 60 ? `<div class="empty"><p>60 premiers affichés sur ${r.length}. Affinez les filtres ou la recherche.</p></div>` : '')
    : `<div class="empty"><div>⌕</div><p>Aucun wallet ne correspond à ces critères.</p></div>`;
}

/* ---------- graphiques ---------- */
function dessine(cv, pts, couleur){
  const r = window.devicePixelRatio || 1, L = cv.clientWidth, H = cv.clientHeight;
  cv.width = L * r; cv.height = H * r;
  const c = cv.getContext('2d'); c.scale(r, r); c.clearRect(0, 0, L, H);
  if (!pts || pts.length < 2) return;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys, 0), y1 = Math.max(...ys, 0);
  if (y1 === y0) y1 = y0 + 1;
  const P = 6, X = v => P + (v - x0) / (x1 - x0 || 1) * (L - 2*P),
        Y = v => H - P - (v - y0) / (y1 - y0) * (H - 2*P);
  c.strokeStyle = '#1e2532'; c.lineWidth = 1;
  for (let i = 0; i <= 3; i++){ const y = P + i * (H - 2*P) / 3;
    c.beginPath(); c.moveTo(0, y); c.lineTo(L, y); c.stroke(); }
  if (y0 < 0 && y1 > 0){ c.strokeStyle = '#2e3849'; c.setLineDash([3,3]);
    c.beginPath(); c.moveTo(0, Y(0)); c.lineTo(L, Y(0)); c.stroke(); c.setLineDash([]); }
  const g = c.createLinearGradient(0, P, 0, H);
  g.addColorStop(0, couleur + '38'); g.addColorStop(1, couleur + '00');
  c.beginPath(); c.moveTo(X(pts[0][0]), Y(pts[0][1]));
  pts.forEach(p => c.lineTo(X(p[0]), Y(p[1])));
  c.lineTo(X(pts[pts.length-1][0]), Y(Math.max(y0, 0))); c.lineTo(X(pts[0][0]), Y(Math.max(y0, 0)));
  c.closePath(); c.fillStyle = g; c.fill();
  c.beginPath(); c.moveTo(X(pts[0][0]), Y(pts[0][1]));
  pts.forEach(p => c.lineTo(X(p[0]), Y(p[1])));
  c.strokeStyle = couleur; c.lineWidth = 2; c.lineJoin = 'round'; c.stroke();
  const last = pts[pts.length-1];
  c.beginPath(); c.arc(X(last[0]), Y(last[1]), 3.5, 0, 7); c.fillStyle = couleur; c.fill();
}
function histo(cv, h){
  const r = window.devicePixelRatio || 1, L = cv.clientWidth, H = cv.clientHeight;
  cv.width = L * r; cv.height = H * r;
  const c = cv.getContext('2d'); c.scale(r, r); c.clearRect(0, 0, L, H);
  if (!h || !h.b) return;
  const m = Math.max(...h.b), n = h.b.length, w = (L - 4) / n;
  h.b.forEach((v, i) => {
    const ht = m ? (v / m) * (H - 12) : 0;
    c.fillStyle = (h.lo + i * h.pas) >= 0 ? '#2fe0a4' : '#ff5f6d';
    c.globalAlpha = .82;
    c.fillRect(2 + i * w + 1, H - ht, w - 2, ht);
  });
  c.globalAlpha = 1;
}

/* ---------- fiche wallet ---------- */
let retour = 0, courant = null;
function ouvre(a){
  const w = byA[a]; if (!w) return;
  courant = w;
  retour = window.scrollY;
  const [cls, lab] = statut(w);
  const inW = watch.includes(a), inS = sel.includes(a);
  const eq = w.eq || [];
  const li = (arr, ic) => arr.length
    ? arr.map(x => `<div class="li"><i>${ic}</i><span>${x}</span></div>`).join('')
    : `<div class="li"><i>·</i><span>Aucun élément relevé.</span></div>`;

  document.getElementById('detail').innerHTML = `
  <div class="dhead"><button class="back" onclick="ferme()">← Retour au classement</button></div>
  <div class="dbody">
    <div class="dtitle">Wallet #${w.rang}</div>
    <div class="daddr">${w.a}</div>
    <div class="acts">
      <button class="act p" onclick="copie('${w.a}')">⧉ Copier l'adresse</button>
      <button class="act" onclick="window.open('https://app.hyperliquid.xyz/explorer/address/${w.a}','_blank')">↗ Hyperliquid</button>
      <button class="act ${inW ? 'w' : ''}" id="bw" onclick="tw('${w.a}')">${inW ? '★ Dans la watchlist' : '☆ Watchlist'}</button>
      <button class="act ${inS ? 'p' : ''}" id="bs" onclick="ts('${w.a}')">${inS ? '✓ Sélectionné' : '＋ Comparer'}</button>
    </div>

    <div class="hero">
      <div class="hcard"><div class="k">Score</div>
        <div class="v" style="color:var(--acc)">${w.score.toFixed(1)}</div>
        <div class="s">Intervalle ${w.ic[0]}–${w.ic[1]} / 100</div></div>
      <div class="hcard"><div class="k">Confiance</div>
        <div class="v">${w.conf} %</div>
        <div class="s">${w.conf_lab} · qualité ${w.qualite}/3</div></div>
    </div>
    <div class="sect" style="display:flex;align-items:center;gap:10px;margin-top:-8px">
      <span class="pill ${cls}">${lab}</span>
      <span class="meta" style="font-size:12px">${w.obs
        ? (w.obs.suffisant
           ? `Confirmé sur ${w.obs.n} trades natifs · écart ${num(w.obs.ecart, 3)}`
           : `${w.obs.n} trades natifs seulement — 30 requis par le protocole`)
        : 'Reconstruit depuis Hyperliquid, non confirmé nativement'}</span>
    </div>

    <h3>Courbe de performance</h3>
    <div class="sect">
      <div class="chips" style="margin-bottom:12px" id="per">
        ${[['30J',30],['90J',90],['1A',365],['TOUT',0]].map(([l, j], i) => {
          const n = j ? eq.filter(p => p[0] >= w.t1 - j*86400000).length : eq.length;
          const mort = n < 3;
          return `<button class="chip${i === 3 ? ' on' : ''}${mort ? ' off' : ''}"
            ${mort ? 'disabled title="Pas assez de trades sur cette période"' : `onclick="per('${w.a}',${j},this)"`}
            >${l}${mort ? ' ·' : ''}</button>`;
        }).join('')}
      </div>
      <canvas id="eqc" height="168"></canvas>
      <div class="legend"><span>${dt(w.t0)}</span>
        <span class="${sign(w.pnl)}">${money(w.pnl)} cumulé</span>
        <span>${dt(w.t1)}</span></div>
    </div>

    <h3>Distribution des résultats</h3>
    <div class="sect">
      <canvas id="hic" height="112"></canvas>
      <div class="legend"><span class="neg">Pertes</span>
        <span>${w.n} trades</span><span class="pos">Gains</span></div>
    </div>

    <h3>Performance</h3>
    <div class="sect g2">
      <div><div class="k">PnL net</div><div class="v ${sign(w.pnl)}">${money(w.pnl)}</div></div>
      <div><div class="k">ROI</div><div class="v">${NA}</div></div>
      <div><div class="k">Sharpe / trade</div><div class="v">${num(w.sr)}</div></div>
      <div><div class="k">Sharpe estimé</div><div class="v" style="color:var(--acc)">${num(w.post)}</div></div>
      <div><div class="k">Win rate</div><div class="v">${pct(w.win)}</div></div>
      <div><div class="k">Profit factor</div><div class="v">${num(w.pf)}</div></div>
    </div>

    <h3>Activité</h3>
    <div class="sect g2">
      <div><div class="k">Trades</div><div class="v">${w.n}</div></div>
      <div><div class="k">Trades / jour</div><div class="v">${num(w.tpj)}</div></div>
      <div><div class="k">Durée médiane</div><div class="v">${w.duree_h == null ? NA : w.duree_h + ' h'}</div></div>
      <div><div class="k">Historique</div><div class="v">${w.jours} j</div></div>
      <div><div class="k">Long / Short</div><div class="v">${NA}</div></div>
      <div><div class="k">Actifs</div><div class="v" style="font-size:12px">${w.coins.length ? w.coins.join(' · ') : NA}</div></div>
    </div>

    <h3>Risque</h3>
    <div class="sect g2">
      <div><div class="k">Max drawdown</div><div class="v neg">${money(-Math.abs(w.dd || 0))}</div></div>
      <div><div class="k">Concentration</div><div class="v">${num(w.conc)}</div></div>
      <div><div class="k">Volatilité / trade</div><div class="v">${num(w.vol)}</div></div>
      <div><div class="k">Meilleur trade</div><div class="v pos">${money(w.best)}</div></div>
      <div><div class="k">Pire trade</div><div class="v neg">${money(w.pire)}</div></div>
      <div><div class="k">Échantillon</div><div class="v">${w.n >= 150 ? 'Suffisant' : 'Limité'}</div></div>
    </div>

    <h3>Pourquoi ce wallet est classé #${w.rang} ?</h3>
    <div class="sect">
      <div style="font:600 11px 'IBM Plex Mono';color:var(--pos);letter-spacing:.08em;margin-bottom:9px">POINTS FORTS</div>
      ${li(w.forts, '✓')}
      <div style="font:600 11px 'IBM Plex Mono';color:var(--warn);letter-spacing:.08em;margin:16px 0 9px">POINTS FAIBLES</div>
      ${li(w.faibles, '−')}
    </div>

    <h3>⚠️ Points de vigilance</h3>
    <div class="sect">${li(w.risques, '⚠')}</div>

    <div class="sect" style="margin-top:20px;background:var(--surf2)">
      <div class="li"><i>ℹ</i><span>Le <b>score</b> mesure la performance ; la <b>confiance</b> mesure la
      solidité de la preuve. Les deux sont volontairement séparés : un wallet peut être
      bien classé et peu fiable.</span></div>
    </div>
  </div>`;
  const d = document.getElementById('detail'); d.classList.add('on'); d.scrollTop = 0;
  document.body.style.overflow = 'hidden';
  requestAnimationFrame(() => {
    dessine(document.getElementById('eqc'), eq, w.pnl >= 0 ? '#2fe0a4' : '#ff5f6d');
    histo(document.getElementById('hic'), w.hist);
  });
}
function per(a, j, b){
  const w = byA[a]; if (!w) return;
  document.querySelectorAll('#per .chip').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  let pts = w.eq;
  if (j > 0 && w.t1){ const lim = w.t1 - j * 86400000; pts = w.eq.filter(p => p[0] >= lim); }
  if (pts.length < 2) pts = w.eq.slice(-2);
  dessine(document.getElementById('eqc'), pts, w.pnl >= 0 ? '#2fe0a4' : '#ff5f6d');
}
function ferme(){
  document.getElementById('detail').classList.remove('on');
  document.body.style.overflow = '';
  window.scrollTo(0, retour);
}

/* ---------- watchlist / selection ---------- */
function tw(a){
  const i = watch.indexOf(a);
  i < 0 ? watch.push(a) : watch.splice(i, 1);
  S.set('watch', watch); toast(i < 0 ? '★ Ajouté à la watchlist' : 'Retiré de la watchlist');
  const b = document.getElementById('bw');
  if (b){ const on = watch.includes(a); b.className = 'act' + (on ? ' w' : '');
    b.textContent = on ? '★ Dans la watchlist' : '☆ Watchlist'; }
  rw();
}
function ts(a){
  const i = sel.indexOf(a);
  if (i < 0){ if (sel.length >= 5){ toast('5 wallets maximum'); return; } sel.push(a); }
  else sel.splice(i, 1);
  S.set('sel', sel); toast(i < 0 ? '＋ Ajouté à la comparaison' : 'Retiré de la comparaison');
  const b = document.getElementById('bs');
  if (b){ const on = sel.includes(a); b.className = 'act' + (on ? ' p' : '');
    b.textContent = on ? '✓ Sélectionné' : '＋ Comparer'; }
  rc();
}
function rw(){
  document.getElementById('wlist').innerHTML = watch.length
    ? watch.map(a => byA[a]).filter(Boolean).sort((x, y) => x.rang - y.rang).map(carte).join('')
    : `<div class="empty"><div>⭐</div><p>Votre watchlist est vide. Ouvrez un wallet et touchez
       <b>☆ Watchlist</b> pour le suivre.</p></div>`;
}

/* ---------- comparaison ---------- */
const LIGNES = [
  ['Rang',          w => '#' + w.rang],
  ['Score',         w => w.score.toFixed(1), 'acc'],
  ['Perf. estimée', w => num(w.post)],
  ['Sharpe observé',w => num(w.sr)],
  ['PnL',           w => money(w.pnl), 'sign'],
  ['ROI',           () => NA],
  ['Win rate',      w => pct(w.win)],
  ['Profit factor', w => num(w.pf)],
  ['Trades',        w => String(w.n)],
  ['Historique',    w => w.jours + ' j'],
  ['Drawdown',      w => money(-Math.abs(w.dd || 0))],
  ['Concentration', w => num(w.conc)],
  ['Confiance',     w => w.conf + ' %'],
  ['Données',       w => statut(w)[1]]
];
function rc(){
  const ws = sel.map(a => byA[a]).filter(Boolean);
  const el = document.getElementById('cmp');
  if (ws.length < 2){
    el.innerHTML = `<div class="empty"><div>📊</div><p>Sélectionnez au moins 2 wallets
      (jusqu'à 5). Ouvrez un wallet et touchez <b>＋ Comparer</b>.</p>
      ${ws.length === 1 ? `<p style="color:var(--acc)">1 wallet sélectionné.</p>` : ''}</div>`;
    return;
  }
  const best = {
    score: Math.max(...ws.map(w => w.score)), pnl: Math.max(...ws.map(w => w.pnl ?? -1e9)),
    conf: Math.max(...ws.map(w => w.conf))
  };
  el.innerHTML = `<div class="sect" style="padding:0;overflow:hidden"><div class="ctable"><table>
    <thead><tr><th>Métrique</th>${ws.map(w => `<th>#${w.rang}</th>`).join('')}</tr></thead>
    <tbody>${LIGNES.map(([k, f, m]) => `<tr><td>${k}</td>${ws.map(w => {
      const v = f(w);
      let c = m === 'acc' ? 'style="color:var(--acc)"' : (m === 'sign' ? `class="${sign(w.pnl)}"` : '');
      const gagne = (k === 'Score' && w.score === best.score) ||
                    (k === 'PnL' && w.pnl === best.pnl) ||
                    (k === 'Confiance' && w.conf === best.conf);
      return `<td ${c}>${v}${gagne ? ' <span style="color:var(--pos)">◆</span>' : ''}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div></div>
    <div class="sect" style="margin-top:12px">
      <div class="li"><i>◆</i><span>Marque la meilleure valeur de la ligne. Un score élevé
      avec une confiance basse repose sur une preuve plus mince — regardez toujours
      <b>les deux ensemble</b>.</span></div></div>
    <div style="margin-top:12px">${ws.map(w =>
      `<button class="chip on" style="margin-right:7px" onclick="ts('${w.a}')">#${w.rang} ✕</button>`).join('')}</div>`;
}

/* ---------- recherche ---------- */
function rs(){
  const s = document.getElementById('q2').value.toLowerCase().trim();
  const el = document.getElementById('sres');
  if (!s){
    el.innerHTML = `<div class="empty"><div>🔎</div><p>Collez une adresse complète ou partielle,
      ou saisissez un rang (1 à ${W.length}).</p></div>`;
    return;
  }
  const r = W.filter(w => w.a.toLowerCase().includes(s) || String(w.rang) === s).slice(0, 25);
  el.innerHTML = r.length
    ? `<div class="count" style="margin:0 0 11px">${r.length} résultat${r.length > 1 ? 's' : ''}</div>` + r.map(carte).join('')
    : `<div class="empty"><div>∅</div><p>Aucun wallet trouvé pour «&nbsp;${s}&nbsp;».
       Ce wallet n'est pas dans les ${W.length} analysés.</p></div>`;
}

/* ---------- navigation ---------- */
function vue(v){
  document.querySelectorAll('.view').forEach(x => x.classList.remove('on'));
  document.getElementById('v-' + v).classList.add('on');
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
  window.scrollTo(0, 0);
  if (v === 'watch') rw(); if (v === 'cmp') rc();
}
document.querySelectorAll('nav button').forEach(b => b.onclick = () => vue(b.dataset.v));

/* ---------- init ---------- */
document.getElementById('sorts').innerHTML = SORTS.map(([k, l], i) =>
  `<button class="chip${i === 0 ? ' on' : ''}" data-s="${k}">${l}</button>`).join('');
document.querySelectorAll('#sorts .chip').forEach(c => c.onclick = () => {
  tri = c.dataset.s;
  document.querySelectorAll('#sorts .chip').forEach(x => x.classList.remove('on'));
  c.classList.add('on'); rendu();
});
document.getElementById('fpanel').innerHTML = FDEF.map(([k, l, mn, mx, st]) =>
  `<div class="frange"><label>${l} <b id="lb-${k}">${F[k]}</b></label>
   <input type="range" min="${mn}" max="${mx}" step="${st}" value="${F[k]}" data-f="${k}"></div>`).join('') +
  `<div class="frange"><label>Provenance des données</label>
   <div class="chips" style="margin:0">
     <button class="chip on" data-o="all">Toutes</button>
     <button class="chip" data-o="obs">🟢 Avec natif</button>
     <button class="chip" data-o="der">🟡 DERIVED seul</button></div></div>`;
document.querySelectorAll('#fpanel input[type=range]').forEach(i => i.oninput = () => {
  const k = i.dataset.f, v = parseFloat(i.value); F[k] = v;
  document.getElementById('lb-' + k).textContent = FDEF.find(f => f[0] === k)[5](v);
  rendu();
});
document.querySelectorAll('#fpanel [data-o]').forEach(b => b.onclick = () => {
  F.obs = b.dataset.o;
  document.querySelectorAll('#fpanel [data-o]').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); rendu();
});
document.getElementById('ftoggle').onclick = function(){
  const p = document.getElementById('fpanel');
  p.classList.toggle('on'); this.classList.toggle('on', p.classList.contains('on'));
};
document.getElementById('q').oninput = e => { q = e.target.value; rendu(); };
document.getElementById('q2').oninput = rs;

const pv = document.getElementById('pverdict');
pv.textContent = META.verdict === 'VALIDE' ? '🟢 VALIDÉ'
  : META.verdict === 'INCONCLUSIF' ? '⚠️ INCONCLUSIF' : '🔴 ' + META.verdict;
pv.className = 'pill ' + (META.verdict === 'VALIDE' ? 'o' : 'i');
document.getElementById('pmaj').textContent = META.maj;
rendu(); rs(); rw(); rc();
let rz;
addEventListener('resize', () => {
  clearTimeout(rz);
  rz = setTimeout(() => {
    if (!courant || !document.getElementById('detail').classList.contains('on')) return;
    const c = document.getElementById('eqc'), h = document.getElementById('hic');
    if (c) dessine(c, courant.eq, courant.pnl >= 0 ? '#2fe0a4' : '#ff5f6d');
    if (h) histo(h, courant.hist);
  }, 140);
});
</script>"""

html = TPL.replace("%%DATA%%", json.dumps(DATA, separators=(",", ":")))
out = os.environ.get("HT_APP_OUT", os.path.join(D, "app.html"))
open(out, "w", encoding="utf8").write(html)
print(f"ecrit : {out}  ({len(html)/1024:.0f} Ko)")
