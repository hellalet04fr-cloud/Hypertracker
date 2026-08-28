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

  // ══════════════════════════════════════════════ M1 — les totaux de section
  // Le compteur affichait la longueur de la TRANCHE : « Dormants 6 » quand il y
  // en a 100, soit 44 % des wallets classes. Sous-declarer un risque par un
  // effet de decoupage est la faute la plus grave de cet ecran.
  etape = 'M1 totaux de section';
  await cmd('Page.navigate', { url: URL + '#/' });
  await dodo(2400);
  const totDorm = W.filter(w => w.st === 'RANKED' && (w.dort_j ?? 0) > 60).length;
  const cpt = await js(`(()=>{const out={};
    document.querySelectorAll('#jour .sect').forEach(x=>{
      const l=x.querySelector('.lab'), c=x.querySelector('.cpt');
      if(l&&c) out[l.textContent.trim()]=c.textContent.trim();});
    return out;})()`);
  vrai('« Dormants » annonce le total réel, pas la tranche',
    (cpt['Dormants'] || '').indexOf('/ ' + totDorm) > 0,
    `affiché « ${cpt['Dormants']} », attendu « … / ${totDorm} »`);
  vrai('chaque section tronquée annonce affichés / total',
    Object.values(cpt).some(v => v.indexOf('/') > 0), JSON.stringify(cpt));
  vrai('un lien mène à la population entière',
    (await js(`document.querySelectorAll('#jour .tout').length`)) > 0, 'aucun lien');
  await js(`document.querySelector('#jour .tout[data-f="dormant"]').click()`);
  await dodo(900);
  vrai('le lien « Voir les N » ouvre exactement cette population',
    (await js(`document.getElementById('v-rank').classList.contains('on')`))
    && (await js(`courant.length`)) === W.filter(w => (w.dort_j ?? 0) > 60).length,
    'filtre=' + await js(`ETAT.filtre`) + ' n=' + await js(`courant.length`));

  // ══════════════════════════════════════════════ M2/M3 — la précision juste
  // Largeur mediane de l'IC : 56 points sur 100. Ecrire « 98,1 » sur [64-100]
  // annonce un dixieme la ou la mesure ne porte pas dix points.
  etape = 'M2 précision et M3 saturation';
  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(500);
  await js(`window.scrollTo(0, document.body.scrollHeight)`); await dodo(700);
  const faux = await js(`[...document.querySelectorAll('#liste .row')]
    .filter(r=>{const w=byA[r.dataset.a], t=r.querySelector('.sc').textContent;
      return (w.ic[1]-w.ic[0])>20 && /[.,]/.test(t);})
    .map(r=>r.dataset.a.slice(0,10)+' '+r.querySelector('.sc').textContent)`);
  vrai('aucune décimale au-delà de 20 points d’intervalle', faux.length === 0,
    faux.slice(0, 3).join(' · '));

  const zero = W.filter(w => w.ic[0] === w.ic[1]);
  vrai('des intervalles de largeur nulle existent bien dans les données',
    zero.length > 0, 'aucun — le contrôle suivant ne prouverait rien');
  await va('#/w/' + zero[0].a, 1000);
  const txtZero = await js(`document.getElementById('v-wallet').textContent`);
  vrai('un IC de largeur nulle n’est jamais affiché comme un intervalle',
    txtZero.indexOf(zero[0].ic[0] + '–' + zero[0].ic[1]) < 0
    && /borne de l’échelle/.test(txtZero),
    'la fiche présente encore ' + zero[0].ic[0] + '–' + zero[0].ic[1]);
  vrai('la saturation est dessinée par un mors ouvert, pas fermé',
    await js(`(()=>{const s=document.querySelector('#v-wallet svg.rail');
      return !!s && s.innerHTML.indexOf('<path') >= 0;})()`), 'mors fermé sur une borne');

  // ══════════════════════════════════════════════ M4 — le verdict domine
  etape = 'M4 verdict visible sans défiler';
  await va('#/rank', 900);
  await js(`window.scrollTo(0,0)`); await dodo(300);
  const vb = await js(`(()=>{const e=document.querySelector('#verdict .vbn');
    if(!e) return null; const r=e.getBoundingClientRect();
    return {haut:Math.round(r.top), bas:Math.round(r.bottom),
      vh:window.innerHeight, txt:e.textContent.trim().slice(0,60)};})()`);
  vrai('le verdict est visible sans défiler',
    !!vb && vb.haut < vb.vh && vb.bas > 0, JSON.stringify(vb));
  vrai('le verdict nomme l’absence de validation',
    !!vb && /non validé/.test(vb.txt), (vb || {}).txt);

  // ══════════════════════════════════════════════ M6 — le profit factor
  // Au-dela de 10, un profit factor decrit un echantillon degenere — quelques
  // gagnants enormes, presque aucun perdant — pas une performance.
  etape = 'M6 profit factor dégénéré';
  const pfHauts = W.filter(w => (w.pf || 0) > 10);
  vrai('des profit factors dégénérés existent dans les données',
    pfHauts.length > 0, 'aucun — le contrôle suivant ne prouverait rien');
  const enForts = pfHauts.filter(w => (w.forts || []).some(x => /rofit factor/.test(x)));
  vrai('aucun profit factor > 10 n’est présenté comme un point fort',
    enForts.length === 0, enForts.length + ' wallets');
  const enRisques = pfHauts.filter(w => (w.risques || []).some(x => /dégénérée/.test(x)));
  vrai('ils sont portés en vigilance, avec leur motif',
    enRisques.length === pfHauts.length,
    enRisques.length + ' / ' + pfHauts.length);

  // ══════════════════════════════════════════════ M7 — les non-mesurables
  // `?? -1` les poussait en queue de tri : a l'ecran ils formaient une fin de
  // classement qui ressemble a une mauvaise performance, alors que c'est une
  // absence de mesure — ce que la regle N/D interdit partout ailleurs.
  etape = 'M7 non-mesurables regroupés';
  await js(`document.querySelector('[data-t="conf"]').click()`); await dodo(600);
  const sansP = W.filter(w => w.conf == null).length;
  vrai('les wallets sans probabilité sortent de l’ordre',
    (await js(`SEP.n`)) === sansP && (await js(`SEP.i`)) > 0,
    'SEP=' + JSON.stringify(await js(`SEP`)) + ' attendu n=' + sansP);
  vrai('la partition mesurable / non mesurable est stricte',
    await js(`courant.slice(0,SEP.i).every(w=>w.conf!=null)
      && courant.slice(SEP.i).every(w=>w.conf==null)`), 'partition poreuse');
  // Le separateur vit APRES le dernier wallet mesurable : sur 291 releves il
  // faut derouler la liste entiere pour l'atteindre. Deux defilements n'y
  // suffisaient pas, et le controle concluait a son absence.
  for (let k = 0; k < 30 && (await js(`vus < courant.length`)); k++) {
    await js(`window.scrollTo(0, document.body.scrollHeight)`);
    await dodo(280);
  }
  vrai('toute la liste a été déroulée',
    await js(`vus >= courant.length`),
    await js(`vus + ' / ' + courant.length`));
  vrai('un séparateur nommé les annonce',
    await js(`(()=>{const s=document.querySelector('#liste .sep');
      return !!s && /non mesurable/.test(s.textContent);})()`),
    'aucun séparateur rendu');

  // ══════════════════════════════════════════════ M8 — deux populations
  etape = 'M8 observation, échantillon contre total';
  await js(`document.querySelector('[data-f="disco"]').click()`); await dodo(600);
  vrai('le filtre Observation annonce son dénominateur réel',
    (await js(`document.getElementById('cntx').textContent`))
      === String(META.discovery_total),
    'dénominateur ' + await js(`document.getElementById('cntx').textContent`));
  vrai('son libellé dit qu’il s’agit d’un échantillon',
    /échantillon/.test(await js(`document.querySelector('[data-f="disco"]').textContent`)),
    'libellé ambigu');

  // ══════════════════════════════════════════════ M9 — les marques suivent
  etape = 'M9 marques croisées';
  await cmd('Page.navigate', { url: URL + '#/' });
  await dodo(2200);
  vrai('un wallet dormant est marqué partout où il apparaît',
    await js(`[...document.querySelectorAll('#jour .li[data-a]')]
      .every(l => !!l.querySelector('.mk.d') === ((byA[l.dataset.a].dort_j??0)>60))`),
    'marque absente dans au moins une section');
  vrai('un wallet fraîchement qualifié aussi',
    await js(`[...document.querySelectorAll('#jour .li[data-a]')]
      .every(l => !!l.querySelector('.mk.n') === (byA[l.dataset.a].promu != null))`),
    'marque absente dans au moins une section');

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
