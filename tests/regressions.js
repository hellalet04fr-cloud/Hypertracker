/**
 * CRITERES D'ACCEPTATION DE L'AUDIT DU 2026-08-28.
 *
 * Vingt-neuf defauts confirmes — 4 bloquants, 16 majeurs, 9 mineurs. Les trois
 * suites existantes couvrent les PARCOURS (test_interface), les FONCTIONS
 * (audit_fonctionnalites) et la FIDELITE des valeurs (coherence_ui). Aucune ne
 * pouvait voir ces defauts-la : ils vivent dans des etats que personne
 * n'exercait — la deuxieme fiche ouverte, un hote de polices injoignable, une
 * barre d'URL qui se retracte, un lien partage ouvert a froid.
 *
 * Chaque controle ci-dessous reproduit LE symptome mesure par l'audit, pas une
 * approximation de ce symptome. Un test qui ne peut pas echouer sur la version
 * fautive ne prouve rien.
 *
 *   node tests/regressions.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const DATA = process.env.HT_DATA_ROOT || 'C:\\Users\\maram\\ht_data';
const URL = 'file:///' + path.join(DATA, 'app.html').replace(/\\/g, '/');
const PORT = 9812;

const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--no-first-run', '--no-default-browser-check', '--disable-sync',
  `--remote-debugging-port=${PORT}`, '--user-data-dir=' + process.env.TEMP + '/cdpreg',
  'about:blank'], { stdio: 'ignore' });

const dodo = ms => new Promise(r => setTimeout(r, ms));
const vert = [], rouge = [];
let etape = 'demarrage';
const vrai = (nom, cond, detail) =>
  (cond ? vert : rouge).push(nom + (cond ? '' : '  << ' + detail));

(async () => {
  const app = JSON.parse(fs.readFileSync(path.join(DATA, 'app_data.json'), 'utf8'));
  const W = app.wallets, META = app.meta;

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
    if (r.exceptionDetails) throw new Error('JS: ' + r.exceptionDetails.text + ' :: ' +
      ((r.exceptionDetails.exception || {}).description || ''));
    return r.result.value;
  };
  const va = async (h, ms) => { await js(`location.hash='${h}'`); await dodo(ms || 650); };
  const metrique = async (w, h) => cmd('Emulation.setDeviceMetricsOverride',
    { width: w, height: h, deviceScaleFactor: 2, mobile: true });

  await cmd('Page.enable'); await cmd('Runtime.enable'); await cmd('Network.enable');
  await metrique(390, 844);
  await cmd('Page.navigate', { url: URL });
  await dodo(2400);

  // ══════════════════════════════════════════════ B1 — la deuxieme fiche
  // Le drapeau de trace vivait sur #v-wallet, un noeud qui survit aux
  // changements de fiche. Des la DEUXIEME ouverture, les six graphiques
  // secondaires restaient vides pour le reste de la session. On ouvre donc
  // TROIS wallets : un test a une seule fiche ne peut pas voir ce defaut.
  etape = 'B1 graphiques de la 2e et 3e fiche';
  const trois = W.filter(w => w.n > 20).slice(0, 3).map(w => w.a);
  for (let k = 0; k < trois.length; k++) {
    await va('#/w/' + trois[k], 900);
    await js(`(()=>{const d=document.getElementById('plus');
      d.open=true; d.dispatchEvent(new Event('toggle'));})()`);
    await dodo(850);
    // « peint » = au moins un pixel non transparent. Un canvas dimensionne mais
    // vierge passerait un controle sur width/height.
    const peints = await js(`(()=>{
      const out={};
      for (const g of ['cad','g1','g2','g3','g4','g7']) {
        const c=document.getElementById(g);
        if(!c){out[g]=-1;continue;}
        try{
          const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
          let n=0; for(let i=3;i<d.length;i+=4) if(d[i]) n++;
          out[g]=n;
        }catch(e){out[g]=-2;}
      }
      return out;})()`);
    const vides = Object.entries(peints).filter(x => x[1] === 0).map(x => x[0]);
    vrai(`fiche ${k + 1} : les six graphiques sont peints`, vides.length === 0,
      'vides : ' + vides.join(', ') + ' — ' + JSON.stringify(peints));
  }

  // ══════════════════════════════════════════════ B3 — la barre d'URL
  // Sur iOS et Android, la barre d'URL qui se retracte pendant le defilement
  // EST un evenement resize. Le gestionnaire rappelait ouvre(), qui regenere le
  // HTML et fait scrollTo(0,0) : le lecteur etait renvoye en haut de fiche,
  // panneau referme, a chaque scroll.
  etape = 'B3 resize en hauteur';
  await js(`window.scrollTo(0, 600)`); await dodo(400);
  const avant = await js(`({y: Math.round(window.scrollY),
    ouvert: document.getElementById('plus').open})`);
  await metrique(390, 790);                       // hauteur seule
  await dodo(700);
  const apres = await js(`({y: Math.round(window.scrollY),
    ouvert: document.getElementById('plus').open})`);
  vrai('un resize en hauteur ne touche ni le defilement ni le repli',
    Math.abs(avant.y - apres.y) < 20 && avant.ouvert === apres.ouvert,
    `${JSON.stringify(avant)} -> ${JSON.stringify(apres)}`);

  // Un vrai changement de LARGEUR doit, lui, redessiner les canvas.
  etape = 'B3 resize en largeur';
  await metrique(320, 790); await dodo(900);
  const larg = await js(`document.getElementById('g1').width`);
  await metrique(430, 844); await dodo(900);
  const larg2 = await js(`document.getElementById('g1').width`);
  vrai('un resize en largeur redessine les graphiques', larg2 > larg,
    `${larg} -> ${larg2}`);
  const apres2 = await js(`document.getElementById('plus').open`);
  vrai('le repli survit au changement de largeur', apres2 === true, 'panneau referme');
  await metrique(390, 844);

  // ══════════════════════════════════════════════ B4 — le lien partage
  // C'est exactement le lien que le bouton « Copier » invite a partager :
  // ouverture directe sur une fiche, sans historique derriere. history.back()
  // faisait alors sortir de l'application, ecran vide.
  etape = 'B4 retour sur ouverture directe';
  // DOCUMENT NEUF OBLIGATOIRE. Naviguer d'une fiche vers une autre fiche ne
  // change que le fragment : Chrome ne recharge pas, il emet hashchange — et le
  // test croyait mesurer une ouverture a froid alors qu'il mesurait une
  // navigation interne. Passer par about:blank force un vrai chargement.
  await cmd('Page.navigate', { url: 'about:blank' });
  await dodo(400);
  await cmd('Page.navigate', { url: URL + '#/w/' + trois[0] });
  await dodo(2400);
  vrai('la fiche s ouvre bien en direct',
    await js(`document.getElementById('v-wallet').classList.contains('on')`), 'fiche absente');
  await js(`document.getElementById('bk').click()`); await dodo(800);
  vrai('« Retour » sur un lien partagé mène au classement',
    await js(`document.getElementById('v-rank').classList.contains('on')`),
    'vue active : ' + await js(`[...document.querySelectorAll('.view')]
      .filter(v=>v.classList.contains('on')).map(v=>v.id).join(',') || 'AUCUNE'`));

  // ══════════════════════════════════════════════ B2 — polices injoignables
  // La feuille de polices bloquait le rendu : hote injoignable = 12 874 ms
  // d'ecran vide. On coupe l'hote et on mesure ce qui existe a t+500 ms.
  etape = 'B2 polices bloquees';
  await cmd('Network.setBlockedURLs', { urls: ['*fonts.googleapis.com*', '*fonts.gstatic.com*'] });
  await cmd('Page.navigate', { url: URL + '#/rank' });
  await dodo(500);
  const t500 = await js(`({lignes: document.querySelectorAll('#liste .row').length,
    texte: (document.body.innerText||'').trim().length})`);
  vrai('au moins une ligne rendue à t+500 ms sans les polices',
    t500.lignes > 0 && t500.texte > 200, JSON.stringify(t500));
  await cmd('Network.setBlockedURLs', { urls: [] });

  console.log('\n=== VERT (' + vert.length + ') ===');
  vert.forEach(v => console.log('  OK  ' + v));
  if (rouge.length) {
    console.log('\n=== ROUGE (' + rouge.length + ') ===');
    rouge.forEach(v => console.log('  !!  ' + v));
  }
  console.log(`\nRESULTAT : ${vert.length} verts / ${rouge.length} rouges`);
  ws.close(); edge.kill(); process.exit(rouge.length ? 1 : 0);
})().catch(e => {
  console.error('ECHEC a l etape [' + etape + '] : ' + e.message);
  edge.kill(); process.exit(2);
});
