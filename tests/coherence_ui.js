/**
 * COHERENCE INTERFACE <-> MOTEUR.
 *
 * Les controles existants couvrent deux choses et en laissent une de cote :
 *
 *   app/audit_donnees.py        les donnees preparees contre les fichiers bruts
 *   tests/audit_fonctionnalites  les fonctionnalites contre leur comportement
 *   CE FICHIER                   ce que l'ECRAN AFFICHE contre ce que le moteur
 *                                a calcule
 *
 * C'est le trou le plus dangereux des trois : une valeur peut etre juste dans
 * app_data.json, la fonctionnalite peut marcher, et l'ecran montrer autre chose
 * — un mauvais arrondi, un champ interverti, une unite absente. Ce defaut a
 * deja existe ici : 39 courbes se terminaient ailleurs que sur le PnL affiche
 * juste en dessous.
 *
 * On lit donc les valeurs DANS LE DOM RENDU et on les compare au JSON source.
 *
 *   node tests/coherence_ui.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const DATA = process.env.HT_DATA_ROOT || 'C:\\Users\\maram\\ht_data';
const URL = 'file:///' + path.join(DATA, 'app.html').replace(/\\/g, '/');
const PORT = 9795;
const N_WALLETS = 12;          // echantillon : premiers, milieu, derniers

const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--no-first-run', '--no-default-browser-check', '--disable-sync',
  `--remote-debugging-port=${PORT}`, '--user-data-dir=' + process.env.TEMP + '/cdpcoh',
  'about:blank'], { stdio: 'ignore' });

const dodo = ms => new Promise(r => setTimeout(r, ms));
const ecarts = [];
const N = s => {
  // « +$6.2k », « $164 », « 0,2383 », « 79.4 % », « 128 » -> nombre
  const t = String(s).replace(/\u2212/g, '-').replace(/[^\d.,\-kM]/g, '');
  let m = 1;
  if (/k$/.test(t)) m = 1e3; else if (/M$/.test(t)) m = 1e6;
  const v = parseFloat(t.replace(/[kM]$/, '').replace(/\s/g, '').replace(',', '.'));
  return isNaN(v) ? null : v * m;
};

(async () => {
  const app = JSON.parse(fs.readFileSync(path.join(DATA, 'app_data.json'), 'utf8'));
  const W = app.wallets;

  let wsUrl;
  for (let i = 0; i < 60 && !wsUrl; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = l.find(t => t.type === 'page'); if (p) wsUrl = p.webSocketDebuggerUrl;
    } catch {}
    if (!wsUrl) await dodo(250);
  }
  const ws = new WebSocket(wsUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const att = new Map();
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && att.has(m.id)) { att.get(m.id)(m); att.delete(m.id); }
  });
  const cmd = (m, p) => new Promise((res, rej) => {
    const n = ++id;
    att.set(n, x => x.error ? rej(new Error(m + ' ' + x.error.message)) : res(x.result));
    ws.send(JSON.stringify({ id: n, method: m, params: p || {} }));
  });
  const js = async e => {
    const r = await cmd('Runtime.evaluate',
      { expression: e, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('JS: ' + r.exceptionDetails.text);
    return r.result.value;
  };

  await cmd('Page.enable'); await cmd('Runtime.enable');
  await cmd('Emulation.setDeviceMetricsOverride',
    { width: 390, height: 900, deviceScaleFactor: 2, mobile: true });
  await cmd('Page.navigate', { url: URL });
  await dodo(2500);

  // ---- echantillon : tete, milieu, queue du classement
  const idx = [];
  for (let i = 0; i < Math.min(4, W.length); i++) idx.push(i);
  const mid = Math.floor(W.length / 2);
  for (let i = mid; i < Math.min(mid + 4, W.length); i++) idx.push(i);
  for (let i = Math.max(0, W.length - 4); i < W.length; i++) idx.push(i);
  const ech = [...new Set(idx)].slice(0, N_WALLETS).map(i => W[i]);

  let controles = 0;
  for (const w of ech) {
    await js(`location.hash='#/w/${w.a}'`);
    await dodo(620);
    // « Tout voir » : les mesures secondaires sont derriere une revelation
    // progressive. Sans cette ouverture le controle lirait un DOM vide et
    // conclurait a une divergence qui n'existe pas.
    await js(`(() => { const d = document.getElementById('plus');
      if (d && !d.open) { d.open = true; d.dispatchEvent(new Event('toggle')); }
      return !!d; })()`);
    await dodo(420);

    const lu = await js(`(() => {
      const el = document.getElementById('v-wallet');
      const cell = k => {
        const c = [...el.querySelectorAll('.cell')]
          .find(x => x.querySelector('.cell-k').textContent.trim() === k);
        return c ? c.querySelector('.cell-v').textContent.trim() : null;
      };
      const kv = k => {
        const d = [...el.querySelectorAll('.mini .kv')]
          .find(x => x.querySelector('span').textContent.trim() === k);
        return d ? d.querySelector('b').textContent.trim() : null;
      };
      return {
        adresse: (document.getElementById('adr').textContent || '').replace(/\\s/g, ''),
        score: (el.querySelector('.big') || {}).textContent,
        ic: kv('Incertitude'), largeur: kv('Largeur de l’IC'),
        proba: kv('Probabilité calibrée'), qualite: kv('Qualité des données'),
        sr: cell('Sharpe / trade'), post: cell('Sharpe retenu'),
        pnl: cell('PnL net'), dd: cell('Drawdown max'),
        n: cell('Trades clos'), jours: cell('Écart 1ᵉʳ–dernier'),
        win: cell('Taux de réussite'), pf: cell('Profit factor'),
        conc: cell('Concentration'), stab: cell('Régularité mens.'),
        r30: cell('Activité 30 j'), r7: cell('Activité 7 j'),
        best: cell('Meilleur trade'), pire: cell('Pire trade'),
        frais: cell('Frais payés'), tpj: cell('Trades / jour'),
        funding: cell('Funding'), roi: cell('ROI'),
      };
    })()`);

    const cmp = (nom, affiche, attendu, tol) => {
      controles++;
      if (attendu == null) {
        if (!/N\/D/.test(String(affiche)))
          ecarts.push(`${w.a.slice(0, 10)} ${nom} : absent en base, affiché « ${affiche} »`);
        return;
      }
      const v = N(affiche);
      if (v == null) {
        ecarts.push(`${w.a.slice(0, 10)} ${nom} : illisible « ${affiche} »`);
      } else if (Math.abs(v - attendu) > (tol ?? 0.011)) {
        ecarts.push(`${w.a.slice(0, 10)} ${nom} : écran ${v} ≠ moteur ${attendu}`);
      }
    };

    controles++;
    if (lu.adresse.toLowerCase() !== w.a.toLowerCase())
      ecarts.push(`${w.a.slice(0, 10)} adresse : « ${lu.adresse} »`);

    cmp('score', lu.score, w.score, 0.051);
    cmp('largeur IC', lu.largeur, w.ic[1] - w.ic[0]);
    cmp('probabilité', lu.proba, w.conf);
    cmp('Sharpe', lu.sr, w.sr, 0.00006);
    cmp('Sharpe retenu', lu.post, w.post, 0.00006);
    // Les montants sont ABREGES a l'affichage (+$6.2k) : la tolerance suit
    // l'arrondi reellement declare, pas une precision qu'on n'affiche pas.
    cmp('PnL', lu.pnl, w.pnl, Math.max(60, Math.abs(w.pnl) * 0.006));
    cmp('drawdown', lu.dd, w.dd, Math.max(1, Math.abs(w.dd) * 0.006));
    cmp('trades', lu.n, w.n);
    cmp('jours', lu.jours, w.jours);
    cmp('taux de réussite', lu.win, w.win, 0.06);
    cmp('profit factor', lu.pf, w.pf, 0.011);
    cmp('concentration', lu.conc, w.conc, 0.0011);
    // TOLERANCE ALIGNEE SUR L'ARRONDI REELLEMENT DECLARE. La regularite est
    // affichee a ZERO decimale — 77,8 % devient « 78 % » — donc l'ecart maximal
    // legitime est de 0,5. Une tolerance plus serree que l'arrondi fabrique des
    // divergences qui n'existent pas : le projet s'y est deja fait prendre.
    cmp('régularité', lu.stab, w.stab, 0.51);
    cmp('activité 30 j', lu.r30, w.r30);
    cmp('activité 7 j', lu.r7, w.r7);
    cmp('meilleur trade', lu.best, w.best, Math.max(1, Math.abs(w.best) * 0.006));
    cmp('pire trade', lu.pire, w.pire, Math.max(1, Math.abs(w.pire) * 0.006));
    cmp('frais', lu.frais, w.frais, Math.max(1, Math.abs(w.frais) * 0.006));
    cmp('trades / jour', lu.tpj, w.tpj, 0.011);

    // Ces deux-la n'existent PAS dans la source : elles doivent rester N/D.
    controles += 2;
    if (!/N\/D/.test(String(lu.funding)))
      ecarts.push(`${w.a.slice(0, 10)} funding : « ${lu.funding} » alors qu'il n'existe pas`);
    if (!/N\/D/.test(String(lu.roi)))
      ecarts.push(`${w.a.slice(0, 10)} ROI : « ${lu.roi} » alors qu'il n'existe pas`);

    // La courbe doit se terminer sur le PnL affiche : c'est le defaut qui avait
    // touche 39 wallets sur 231.
    controles++;
    const fin = (w.eq && w.eq.v && w.eq.v.length) ? w.eq.v[w.eq.v.length - 1] : null;
    if (fin != null && Math.abs(fin - w.pnl) > 0.02)
      ecarts.push(`${w.a.slice(0, 10)} courbe : finit à ${fin}, PnL ${w.pnl}`);

    controles++;
    const ddDeduit = await js(`(() => { const c = drawdown(byA['${w.a}']);
      return c.length ? Math.max(...c.map(p => -p[1])) : null; })()`);
    if (ddDeduit != null && w.dd != null && Math.abs(ddDeduit - w.dd) > 0.02)
      ecarts.push(`${w.a.slice(0, 10)} drawdown déduit ${ddDeduit} ≠ moteur ${w.dd}`);
  }

  // ---- coherence du CLASSEMENT : l'ordre affiche est-il l'ordre calcule ?
  await js(`location.hash='#/rank'`); await dodo(700);
  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(400);
  await js(`document.querySelector('[data-t="score"]').click()`); await dodo(400);
  const rangs = await js(`[...document.querySelectorAll('#liste .row')].slice(0,15)
    .map(r => ({a: r.dataset.a, n: r.querySelector('.no').textContent.replace(/\\D/g,''),
                s: r.querySelector('.sc').textContent}))`);
  const attendu = W.slice().sort((a, b) => b.score - a.score);
  rangs.forEach((r, i) => {
    controles += 2;
    if (r.a !== attendu[i].a)
      ecarts.push(`classement position ${i + 1} : ${r.a.slice(0, 10)} au lieu de ${attendu[i].a.slice(0, 10)}`);
    if (Math.abs(N(r.s) - attendu[i].score) > 0.051)
      ecarts.push(`classement position ${i + 1} : score ${r.s} ≠ ${attendu[i].score}`);
    if (+r.n !== attendu[i].rang)
      ecarts.push(`classement position ${i + 1} : rang affiché ${r.n} ≠ ${attendu[i].rang}`);
  });

  // ---- coherence des INDICATEURS d'accueil
  await js(`location.hash='#/'`); await dodo(700);
  const band = await js(`[...document.querySelectorAll('#jband .band>div')]
    .map(d => d.querySelector('.v').textContent.trim())`);
  const d = app.daily || {};
  const attBand = [
    (d.data_health || {}).ranked ?? app.meta.n,
    (d.new_ranked || []).length,
    (d.archived || []).length,
  ];
  attBand.forEach((v, i) => {
    controles++;
    if (N(band[i]) !== v)
      ecarts.push(`bandeau ${i + 1} : écran ${band[i]} ≠ rapport ${v}`);
  });
  controles++;
  if (band[3] !== app.meta.verdict)
    ecarts.push(`bandeau verdict : « ${band[3]} » ≠ « ${app.meta.verdict} »`);

  console.log('COHERENCE INTERFACE <-> MOTEUR');
  console.log('='.repeat(58));
  console.log(`  ${ech.length} wallets inspectés dans le DOM rendu`);
  console.log(`  ${controles} comparaisons`);
  console.log(`  ${ecarts.length} écart(s)`);
  if (ecarts.length) {
    console.log('');
    ecarts.slice(0, 25).forEach(e => console.log('  !! ' + e));
    if (ecarts.length > 25) console.log(`  … et ${ecarts.length - 25} autres`);
  }
  console.log('='.repeat(58));
  console.log('VERDICT :', ecarts.length ? 'DIVERGENCE ECRAN/MOTEUR' : "L'ECRAN DIT CE QUE LE MOTEUR CALCULE");
  ws.close(); edge.kill(); process.exit(ecarts.length ? 1 : 0);
})().catch(e => {
  console.error('ECHEC : ' + e.message);
  edge.kill(); process.exit(2);
});
