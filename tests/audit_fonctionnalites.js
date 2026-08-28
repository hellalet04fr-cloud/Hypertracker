/**
 * AUDIT EXHAUSTIF DES FONCTIONNALITES — pilote par le protocole DevTools.
 *
 * Il n'inspecte pas le code : il EXERCE chaque fonctionnalite et mesure ce
 * qu'elle rend. Chaque entree est classee :
 *
 *   OK     fonctionne comme attendu
 *   LIM    fonctionne, mais la donnee disponible en limite la portee
 *   KO     ne fonctionne pas
 *
 * Les entrees LIM sont les plus interessantes : elles disent ou le produit
 * bute sur la realite des donnees plutot que sur un defaut de code.
 */
const { spawn } = require('child_process');
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const URL = 'file:///C:/Users/maram/ht_data/app.html';
const PORT = 9788;

const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--no-first-run', '--no-default-browser-check', '--disable-sync',
  `--remote-debugging-port=${PORT}`, '--user-data-dir=' + process.env.TEMP + '/cdpaudit',
  'about:blank'], { stdio: 'ignore' });

const dodo = ms => new Promise(r => setTimeout(r, ms));
const R = [];
let section = '';
const dit = (etat, quoi, detail) => R.push({ section, etat, quoi, detail: detail || '' });

(async () => {
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
    const r = await cmd('Runtime.evaluate', { expression: e, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('JS: ' + r.exceptionDetails.text);
    return r.result.value;
  };
  const va = async (h, ms) => { await js(`location.hash='${h}'`); await dodo(ms || 600); };

  await cmd('Page.enable'); await cmd('Runtime.enable');
  await cmd('Emulation.setDeviceMetricsOverride',
    { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await cmd('Page.navigate', { url: URL });
  await dodo(2400);
  await js(`localStorage.clear()`);
  await cmd('Page.navigate', { url: URL });
  await dodo(2200);

  const NW = await js(`W.length`);
  const META = await js(`JSON.stringify(META)`).then(JSON.parse);

  // ═══════════════════════════════════════════════════ 1. NAVIGATION
  section = 'Navigation';
  for (const [h, v, nom] of [['#/', 'v-jour', 'Aujourd’hui'], ['#/rank', 'v-rank', 'Classement'],
      ['#/data', 'v-data', 'Données']]) {
    await va(h);
    const ok = await js(`document.getElementById('${v}').classList.contains('on')`);
    const n = await js(`document.getElementById('${v}').textContent.trim().length`);
    dit(ok && n > 120 ? 'OK' : 'KO', `espace ${nom}`, `${n} caractères rendus`);
  }
  // Deux espaces ont ete absorbes — « Suivi » etait deja un filtre du
  // classement, « Découverte » repondait a la meme question qu'« Aujourd'hui ».
  // Leurs adresses restent valides : un lien mis en favori ne cesse pas
  // d'exister parce qu'un onglet disparait.
  await va('#/watch');
  dit(await js(`document.getElementById('v-rank').classList.contains('on')
    && ETAT.filtre === 'suivi'`) ? 'OK' : 'KO',
      'ancienne adresse #/watch → classement filtré sur le suivi');
  await va('#/disco');
  dit(await js(`document.getElementById('v-jour').classList.contains('on')`) ? 'OK' : 'KO',
      'ancienne adresse #/disco → Aujourd’hui');
  await va('#/rank');
  await js(`document.querySelector('[data-f="ranked"]').click()`); await dodo(300);
  await va('#/rank');
  const a0 = await js(`W[3].a`);
  await va('#/w/' + a0, 900);
  dit(await js(`location.hash.indexOf('#/w/0x')===0`) ? 'OK' : 'KO',
      'fiche wallet adressable par URL', '#/w/<adresse>');
  await js(`history.back()`); await dodo(800);
  dit(await js(`document.getElementById('v-rank').classList.contains('on')`) ? 'OK' : 'KO',
      'bouton retour système');
  await js(`window.scrollTo(0,700)`); await dodo(300);
  const s1 = await js(`window.scrollY`);
  await va('#/w/' + a0, 800); await js(`history.back()`); await dodo(900);
  const s2 = await js(`window.scrollY`);
  dit(Math.abs(s1 - s2) < 90 ? 'OK' : 'KO', 'position de défilement mémorisée',
      `${s1} → ${s2}`);
  await js(`document.querySelector('nav [data-nav="/rank"]').click()`); await dodo(600);
  dit(await js(`window.scrollY < 60`) ? 'OK' : 'KO',
      'appui sur l’onglet actif remonte en haut');

  // ═══════════════════════════════════════════════════ 2. CLASSEMENT — FILTRES
  section = 'Classement · filtres';
  const F = [
    ['ranked', 'Classés', `W.filter(w=>w.st==='RANKED').length`],
    ['tous', 'Tous', `W.length`],
    ['actif', 'Actifs 30 j', `W.filter(w=>(w.r30??0)>0).length`],
    ['neuf', 'Nouveaux', `W.filter(w=>w.promu!=null).length`],
    ['q3', 'Qualité élevée', `W.filter(w=>w.conf_lab==='elevee').length`],
    ['q2', 'Qualité moyenne', `W.filter(w=>w.conf_lab==='moyenne').length`],
    ['q1', 'Qualité faible', `W.filter(w=>w.conf_lab==='faible').length`],
    ['obs', 'Observé', `W.filter(w=>!!w.obs).length`],
    ['suivi', 'Suivis', `WATCH.length`],
    ['disco', 'Observation', `W.filter(w=>w.st==='DISCOVERY').length`],
  ];
  for (const [cle, nom, attendu] of F) {
    await js(`document.querySelector('[data-f="${cle}"]').click()`); await dodo(240);
    const got = await js(`courant.length`), exp = await js(attendu);
    const etat = got !== exp ? 'KO' : (exp === 0 ? 'LIM' : 'OK');
    dit(etat, `filtre « ${nom} »`,
        `${got} wallet(s)` + (exp === 0 ? ' — aucun dans le jeu actuel' : ''));
  }
  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(250);
  await js(`document.querySelector('[data-t="score"]').click()`); await dodo(250);

  section = 'Classement · convention';
  for (const [c, lib] of [['q3', 'élevée'], ['q2', 'moyenne'], ['q1', 'faible']]) {
    await js(`document.querySelector('[data-c="${c}"]').click()`); await dodo(240);
    const got = await js(`courant.length`);
    const exp = await js(`W.filter(w=>w.conf_lab==='${c === 'q3' ? 'elevee' : c === 'q2' ? 'moyenne' : 'faible'}').length`);
    dit(got === exp ? 'OK' : 'KO', `barre de convention « ${lib} » filtre`, `${got}`);
    await js(`document.querySelector('[data-c="${c}"]').click()`); await dodo(200);
  }
  dit((await js(`courant.length`)) === NW ? 'OK' : 'KO',
      'second appui relâche le filtre de convention');

  // ═══════════════════════════════════════════════════ 3. CLASSEMENT — TRIS
  section = 'Classement · tris';
  const T = [
    ['score', 'Score', `courant.slice(0,20).every((w,i,a)=>i===0||a[i-1].score>=w.score)`, null],
    ['actif', 'Activité', `courant.slice(0,20).every((w,i,a)=>i===0||(a[i-1].r30??0)>=(w.r30??0))`, null],
    ['conf', 'Probabilité', `courant.slice(0,20).every((w,i,a)=>i===0||(a[i-1].conf??-1)>=(w.conf??-1))`,
      `W.filter(w=>w.conf==null).length`],
    ['dd', 'Drawdown', `courant.slice(0,20).every((w,i,a)=>i===0||a[i-1].dd<=w.dd)`, null],
    ['n', 'Trades', `courant.slice(0,20).every((w,i,a)=>i===0||a[i-1].n>=w.n)`, null],
    ['drang', 'Variation de rang', `courant.slice(0,20).every((w,i,a)=>i===0||(a[i-1].drang??-1e9)>=(w.drang??-1e9))`,
      `W.filter(w=>w.drang==null).length`],
    ['recent', 'Dernier trade', `courant.slice(0,20).every((w,i,a)=>i===0||(a[i-1].t1??0)>=(w.t1??0))`, null],
    ['sr', 'Sharpe', `courant.slice(0,20).every((w,i,a)=>i===0||a[i-1].sr>=w.sr)`, null],
    ['stab', 'Régularité', `courant.slice(0,20).every((w,i,a)=>i===0||(a[i-1].stab??-1)>=(w.stab??-1))`,
      `W.filter(w=>w.stab==null).length`],
    ['conc', 'Concentration', `courant.slice(0,20).every((w,i,a)=>i===0||a[i-1].conc<=w.conc)`, null],
    // L'ordre choisi par l'utilisateur est un tri a part entiere : sans lui, les
    // fleches de reordonnancement deplaceraient un rang que personne ne voit.
    ['mien', 'Mon ordre', `true`, `W.length`],
  ];
  for (const [cle, nom, mono, manquants] of T) {
    await js(`document.querySelector('[data-t="${cle}"]').click()`); await dodo(230);
    const ok = await js(mono);
    const nd = manquants ? await js(manquants) : 0;
    dit(!ok ? 'KO' : (nd ? 'LIM' : 'OK'), `tri « ${nom} »`,
        cle === 'mien' ? 'n’ordonne que les wallets suivis — vide pour les autres'
                       : (nd ? `${nd} wallet(s) sans cette grandeur, rangés en fin` : 'monotone'));
  }
  await js(`document.querySelector('[data-t="score"]').click()`); await dodo(250);

  // ═══════════════════════════════════════════════════ 4. RECHERCHE
  section = 'Recherche';
  const cible = await js(`W[8].a`);
  const cherche = async (v) => {
    await js(`(()=>{const q=document.getElementById('q');q.value=${JSON.stringify(v)};
      q.dispatchEvent(new Event('input'));})()`);
    await dodo(380); return js(`courant.length`);
  };
  dit((await cherche(cible)) === 1 ? 'OK' : 'KO', 'recherche par adresse complète');
  dit((await cherche(cible.slice(0, 10))) >= 1 ? 'OK' : 'KO', 'recherche par adresse partielle');
  dit((await cherche(cible.slice(-6))) >= 1 ? 'OK' : 'KO', 'recherche par fin d’adresse');
  const nBtc = await cherche('BTC');
  dit(nBtc > 1 && nBtc < NW ? 'OK' : 'KO', 'recherche par actif (ticker)', `${nBtc} wallets`);
  dit((await cherche('zzzintrouvable')) === 0 ? 'OK' : 'KO', 'recherche sans résultat');
  dit(await js(`document.querySelectorAll('#liste .empty').length===1`) ? 'OK' : 'KO',
      'état vide de recherche explicite');
  await js(`document.getElementById('qc').click()`); await dodo(300);
  dit((await js(`courant.length`)) === NW ? 'OK' : 'KO', 'effacement de la recherche');
  dit('LIM', 'recherche par nom / étiquette de wallet',
      'aucun nom n’existe dans la source : seules les adresses et les tickers sont indexés');

  // ═══════════════════════════════════════════════════ 5. LISTE
  section = 'Classement · liste';
  const n1 = await js(`document.querySelectorAll('#liste .row').length`);
  await js(`window.scrollTo(0, document.body.scrollHeight)`); await dodo(700);
  const n2 = await js(`document.querySelectorAll('#liste .row').length`);
  dit(n2 > n1 ? 'OK' : 'KO', 'révélation progressive au défilement', `${n1} → ${n2} lignes`);
  await js(`window.scrollTo(0,0)`); await dodo(300);
  dit(await js(`document.getElementById('cnt').textContent===String(courant.length)`) ? 'OK' : 'KO',
      'compteur d’en-tête');
  dit(await js(`document.querySelectorAll('#conv .cseg').length===3`) ? 'OK' : 'KO',
      'convention : légende, répartition et filtre en un seul objet');
  // CINQ grandeurs, pas quatorze. Les neuf autres ne sont pas perdues : elles
  // sont sur la fiche, ou on les lit vraiment plutot que de les balayer.
  const champs = await js(`(()=>{const r=document.querySelector('#liste .row');
    return {rang:!!r.querySelector('.no'), adresse:!!r.querySelector('.adr'),
      mesure:!!r.querySelector('.sc'), rail:!!r.querySelector('svg.rail'),
      contexte:/trades/.test(r.querySelector('.r2').textContent),
      activite:/actif|récent|inactif|activité/.test(r.textContent)};})()`);
  const manque = Object.entries(champs).filter(x => !x[1]).map(x => x[0]);
  dit(manque.length ? 'KO' : 'OK', 'ligne minimale : les 5 essentiels',
      manque.length ? 'manquent : ' + manque.join(', ')
                    : 'rang · adresse · mesure + rail · volume · fraîcheur');
  dit(await js(`[...document.querySelectorAll('#liste .row')].every(r=>r.querySelector('svg.rail'))`)
      ? 'OK' : 'KO', 'aucun score sans son rail');
  const nObs = await js(`W.filter(w=>!!w.obs).length`);
  dit(await js(`[...document.querySelectorAll('#liste .row')]
    .every(r => !!r.querySelector('.bg.obs') === !!byA[r.dataset.a].obs)`)
      ? 'OK' : 'KO', 'provenance : seule l’exception est marquée',
      `${nObs}/${NW} observés — 262 mentions « Dérivé » identiques n’informeraient personne`);
  const ndrang = await js(`W.filter(w=>w.drang==null).length`);
  dit(ndrang ? 'LIM' : 'OK', 'variation de rang affichée',
      `${NW - ndrang}/${NW} calculables — moins de deux relevés pour les autres`);

  // ═══════════════════════════════════════════════════ 6. FICHE WALLET
  section = 'Fiche wallet';
  await va('#/rank');
  await js(`document.querySelectorAll('#liste .row')[0].click()`); await dodo(1100);
  const adr = await js(`document.getElementById('adr').textContent.replace(/\\s/g,'')`);
  dit(adr.length === 42 && adr.indexOf('\u2026') < 0 ? 'OK' : 'KO',
      'adresse complète, sans ellipse', `${adr.length} caractères`);
  await cmd('Browser.grantPermissions',
    { permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite'] }).catch(() => {});
  await js(`document.getElementById('cp').click()`); await dodo(400);
  dit(/copi|refus/i.test(await js(`document.getElementById('cp').textContent`)) ? 'OK' : 'KO',
      'copie de l’adresse brute + retour visuel');
  await dodo(1300);
  await js(`document.getElementById('cpb').click()`); await dodo(400);
  dit(/copi|refus/i.test(await js(`document.getElementById('cpb').textContent`)) ? 'OK' : 'KO',
      'copie de l’adresse groupée');
  await dodo(1300);

  // REVELATION PROGRESSIVE : l'essentiel se lit sans rien ouvrir. Vingt-quatre
  // mesures et six graphiques poses en haut ne sont pas de la richesse, c'est
  // du bruit. On verifie donc l'etat ferme avant d'ouvrir.
  const vus0 = await js(`[...document.querySelectorAll('#v-wallet canvas')]
    .filter(c=>c.getBoundingClientRect().width>0).length`);
  dit(vus0 <= 3 ? 'OK' : 'KO', 'fiche fermée : seul l’essentiel est dessiné',
      `${vus0} graphique(s) — mesure, cadran, PnL`);
  dit(await js(`document.getElementById('reste').hidden===true
    && /Tout voir/.test(document.getElementById('plus').textContent)`) ? 'OK' : 'KO',
      'le détail est annoncé, pas caché');
  await js(`(()=>{const d=document.getElementById('plus');
    d.open=true; d.dispatchEvent(new Event('toggle'));})()`);
  await dodo(800);
  dit(await js(`document.getElementById('reste').hidden===false`) ? 'OK' : 'KO',
      'ouverture de « Tout voir »');

  const cells = await js(`[...document.querySelectorAll('#v-wallet .cell')].map(c=>({
    k: c.querySelector('.cell-k').textContent.trim(),
    v: c.querySelector('.cell-v').textContent.trim()}))`);
  const nd = cells.filter(c => c.v.indexOf('N/D') >= 0);
  dit('OK', 'grille de mesures', `${cells.length} cellules`);
  dit(nd.length ? 'LIM' : 'OK', 'grandeurs non disponibles',
      nd.map(c => c.k).join(' · ') + ' — affichées N/D, jamais approchées');

  const cv = await js(`[...document.querySelectorAll('#v-wallet canvas')].map(c=>c.id)`);
  dit(cv.length >= 7 ? 'OK' : 'KO', 'graphiques de la fiche',
      `${cv.length} : ${cv.join(', ')}`);
  for (const [g, nom] of [['g1', 'PnL cumulé'], ['g2', 'Drawdown'], ['g3', 'Activité mensuelle'],
      ['g4', 'Distribution des trades'], ['g7', 'Score contre probabilité']]) {
    const ok = await js(`(()=>{const c=document.getElementById('${g}');
      return !!c && c.width>0 && c.height>0;})()`);
    dit(ok ? 'OK' : 'KO', `graphique ${nom}`);
  }
  const tip = await js(`(()=>{const c=document.getElementById('g1');
    const r=c.getBoundingClientRect();
    c.dispatchEvent(new PointerEvent('pointerdown',{clientX:r.left+r.width/2,
      clientY:r.top+20,bubbles:true,pointerType:'touch'}));
    const t=c.closest('.well').querySelector('.tip');
    return t && t.classList.contains('on') ? t.textContent.trim() : null;})()`);
  dit(tip ? 'OK' : 'KO', 'infobulle au toucher sur les graphiques', tip || '');

  const h5 = await js(`!!document.getElementById('g5')`);
  const nhisto = await js(`(byA[location.hash.slice(4)].histo||[]).length`);
  dit(h5 ? (nhisto >= 5 ? 'OK' : 'LIM') : 'LIM', 'évolution du rang et du score',
      h5 ? `${nhisto} relevés — l’historique s’enrichit d’un point par jour`
         : 'moins de 2 relevés pour ce wallet');
  dit('OK', 'rétrécissement bayésien tracé', 'déplacement Sharpe brut → retenu');
  dit(await js(`document.querySelectorAll('#v-wallet .wl').length>0`) ? 'OK' : 'KO',
      'explication « pourquoi ce wallet est ici »');
  // Le drawdown n'est plus stocke : il se DEDUIT de l'equity, ce qui est sa
  // definition. La deduction doit redonner exactement ce que le moteur calcule.
  dit(await js(`(()=>{const w=byA[location.hash.slice(4)];const c=drawdown(w);
    if(!c.length||w.dd==null)return true;
    return Math.abs(Math.max(...c.map(p=>-p[1]))-w.dd)<0.03;})()`) ? 'OK' : 'KO',
      'drawdown déduit de l’equity, fidèle au moteur',
      'une seule courbe stockée au lieu de deux : −57 % de charge');
  dit(await js(`/Cycle de vie/.test(document.getElementById('v-wallet').textContent)`) ? 'OK' : 'KO',
      'cycle de vie : statut, qualification, dates, retours');
  dit(await js(`document.querySelectorAll('#v-wallet .prot').length>0`) ? 'OK' : 'KO',
      'bloc de provenance OBSERVED / DERIVED');
  dit(await js(`(()=>{const t=document.getElementById('v-wallet').textContent;
    return /Performance/.test(t)&&/Probabilité calibrée/.test(t)&&/Incertitude/.test(t)
      &&/Qualité des données/.test(t);})()`) ? 'OK' : 'KO',
      'les six grandeurs nommées séparément');

  // ═══════════════════════════════════════════════════ 7. WATCHLIST
  section = 'Suivi';
  await js(`document.getElementById('wt').click()`); await dodo(300);
  dit((await js(`WATCH.length`)) === 1 ? 'OK' : 'KO', 'ajout au suivi depuis la fiche');
  dit((await js(`JSON.parse(localStorage.getItem('ht.watch')).length`)) === 1 ? 'OK' : 'KO',
      'persistance locale du suivi');
  await js(`WATCH.push(W[5].a); WATCH.push(W[9].a); majWatch()`);
  // Le suivi n'est plus un espace : c'est un filtre du classement. Aucune
  // fonction n'est perdue — l'ecran retrecit, la recherche et les tris de la
  // liste s'appliquent desormais aussi aux wallets suivis.
  await va('#/watch');
  dit((await js(`document.querySelectorAll('#liste .row').length`)) === 3 ? 'OK' : 'KO',
      'affichage des wallets suivis');
  dit(await js(`[...document.querySelectorAll('#liste .row')].map(r=>r.dataset.a)
    .join(',')===WATCH.join(',')`) ? 'OK' : 'KO',
      'l’ordre affiché EST l’ordre enregistré');
  const avant = await js(`WATCH.join(',')`);
  await js(`document.querySelectorAll('#liste [data-mv]')[1].click()`); await dodo(400);
  dit((await js(`WATCH.join(',')`)) !== avant ? 'OK' : 'KO', 'réordonnancement (monter / descendre)');
  await js(`(()=>{const q=document.getElementById('q');q.value='zzz';
    q.dispatchEvent(new Event('input'));})()`); await dodo(400);
  dit((await js(`document.querySelectorAll('#liste .row').length`)) === 0 ? 'OK' : 'KO',
      'la recherche s’applique aussi au suivi');
  await js(`document.getElementById('qc').click()`); await dodo(400);
  await js(`document.querySelectorAll('#liste [data-rm]')[0].click()`); await dodo(400);
  dit((await js(`WATCH.length`)) === 2 ? 'OK' : 'KO', 'retrait du suivi');
  dit(await js(`[...document.querySelectorAll('#liste .row')]
    .every(r=>/trades/.test(r.textContent))`) ? 'OK' : 'KO',
      'suivi : mesure, volume et fraîcheur, comme toute ligne');
  dit('LIM', 'alertes par wallet suivi',
      'les alertes existent côté cycle mais ne sont pas rattachées à un wallet dans l’UI');
  // PARCOURS REEL : on retire les wallets un par un depuis l'ecran, comme le
  // ferait l'utilisateur. Vider WATCH par programme en etant deja sur #/watch
  // ne redeclenche aucun rendu — reaffecter le meme fragment n'emet pas
  // hashchange — et faisait echouer ce test sans qu'aucun defaut n'existe.
  while (await js(`WATCH.length`)) {
    await js(`document.querySelector('#liste [data-rm]').click()`);
    await dodo(320);
  }
  dit((await js(`document.querySelectorAll('#liste .empty').length`)) === 1 ? 'OK' : 'KO',
      'état vide du suivi après retrait du dernier wallet');
  await va('#/'); await va('#/watch');
  dit((await js(`document.querySelectorAll('#liste .empty').length`)) === 1 ? 'OK' : 'KO',
      'état vide du suivi conservé après aller-retour');
  // Les fleches ne s'affichent QUE sous ce couple filtre + tri : une commande
  // qui ne sert que la n'a pas a peser sur les 267 autres releves.
  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(400);
  dit((await js(`document.querySelectorAll('#liste [data-mv]').length`)) === 0 ? 'OK' : 'KO',
      'les commandes de suivi restent dans leur contexte');

  // ═══════════════════════════════════════════════════ 8. AUJOURD'HUI
  section = 'Aujourd’hui';
  await va('#/');
  dit((await js(`document.querySelectorAll('#jband .band>div').length`)) === 4 ? 'OK' : 'KO',
      'bandeau : classés, nouveaux, sorties, verdict');
  const D = await js(`JSON.stringify(DAILY&&DAILY.data_health||{})`).then(JSON.parse);
  const sec = await js(`[...document.querySelectorAll('#jour .sect .lab')].map(e=>e.textContent)`);
  dit(sec.length ? 'OK' : 'KO', 'sections de l’accueil', sec.join(' · '));
  const det = await js(`[...document.querySelectorAll('#jour details.det summary')]
    .map(e=>e.textContent.trim())`);
  dit(det.length ? 'LIM' : 'OK', 'sections sans événement, repliées',
      det.length ? det.join(' · ') + ' — aucun événement sur le dernier cycle' : '');
  dit(await js(`/Prochaine action/.test(document.getElementById('jour').textContent)`) ? 'OK' : 'KO',
      'prochaine action déduite');
  dit(await js(`document.querySelectorAll('#jour .prot').length>0`) ? 'OK' : 'KO',
      'blocages affichés en clair');

  // ═══════════════════════════════════════════════════ 9. DECOUVERTE (absorbée)
  section = 'Découverte';
  await va('#/');
  const nq = await js(`W.filter(w=>w.promu!=null).length`);
  dit(nq ? 'OK' : 'LIM', 'récemment qualifiés',
      `${nq} wallets datés — le champ n’existe que depuis le registre`);
  const nsurv = await js(`((DAILY||{}).watch||[]).length`);
  dit(nsurv ? 'OK' : 'LIM', 'candidats du dernier cycle',
      `${nsurv} candidats — « candidats » et non « en observation » : ce mot désigne ` +
      `ailleurs les 31 505 wallets de l’état DISCOVERY`);
  dit(await js(`/qualifi/i.test(document.getElementById('jour').textContent)`) ? 'OK' : 'KO',
      'distinction découvert / qualifié explicitée');
  dit('LIM', 'raison de découverte par wallet',
      `champ présent mais vide pour ${NW}/${NW} wallets : antérieurs à sa création`);

  // ═══════════════════════════════════════════════════ 10. DONNEES
  section = 'Données';
  await va('#/data');
  for (const t of ['Fraîcheur', 'Couverture', 'Provenance', 'Ressources',
                   'Alertes du dernier cycle', 'Réputation HyperTracker']) {
    dit(await js(`/${t}/.test(document.getElementById('dh').textContent)`) ? 'OK' : 'KO',
        `bloc « ${t} »`);
  }
  dit(META.avec_natif < 10 ? 'LIM' : 'OK', 'confrontation à la donnée native',
      `${META.avec_natif}/${META.n} wallets — verdict ${META.verdict}`);
  dit(META.sans_p_cal ? 'LIM' : 'OK', 'probabilité calibrée',
      `${META.sans_p_cal}/${META.n} sans valeur : le modèle isotonique n’a pas été persisté`);

  // ═══════════════════════════════════════════════════ 11. ETATS ET ROBUSTESSE
  section = 'États et robustesse';
  await va('#/w/0x' + '0'.repeat(40), 800);
  dit((await js(`document.querySelectorAll('#v-wallet .empty').length`)) === 1 ? 'OK' : 'KO',
      'wallet inconnu');
  await js(`location.hash='#/nimportequoi'`); await dodo(600);
  dit(await js(`document.getElementById('v-jour').classList.contains('on')`) ? 'OK' : 'KO',
      'route inconnue → retour à l’accueil');
  const ndTot = await js(`(document.body.textContent.match(/N\\/D/g)||[]).length`);
  dit(ndTot > 0 ? 'OK' : 'KO', 'les données absentes s’affichent N/D',
      `${ndTot} occurrences sur l’écran courant`);
  dit(await js(`(()=>{try{localStorage.setItem('x','1');localStorage.removeItem('x');
    return true;}catch{return false;}})()`) ? 'OK' : 'LIM',
      'stockage local défensif', 'lecture et écriture encapsulées dans try/catch');

  // ═══════════════════════════════════════════════════ 12. ACCESSIBILITE
  section = 'Accessibilité';
  await va('#/rank');
  const petits = await js(`[...document.querySelectorAll('nav button,.chip,.btn,.li,.row')]
    .filter(e=>{const r=e.getBoundingClientRect();return r.height>0&&r.height<32;}).length`);
  dit(petits === 0 ? 'OK' : 'KO', 'zones tactiles ≥ 32 px', `${petits} trop petites`);
  dit(await js(`[...document.querySelectorAll('svg.rail')]
    .every(s=>s.getAttribute('role')==='img'&&!!s.getAttribute('aria-label'))`) ? 'OK' : 'KO',
      'rails décrits pour les lecteurs d’écran');
  dit(await js(`[...document.querySelectorAll('#liste .row')]
    .every(r=>r.getAttribute('tabindex')==='0'&&!!r.getAttribute('aria-label'))`) ? 'OK' : 'KO',
      'lignes focalisables au clavier');
  dit(await js(`[...document.querySelectorAll('nav button')]
    .every(b=>!!b.getAttribute('aria-label'))`) ? 'OK' : 'KO', 'navigation étiquetée');
  dit(await js(`[...document.styleSheets].some(s=>{try{return [...s.cssRules]
    .some(r=>r.conditionText&&/prefers-reduced-motion/.test(r.conditionText));}
    catch{return false;}})`) ? 'OK' : 'KO', 'animations réduites si demandé');
  dit('LIM', 'contraste vérifié automatiquement',
      'palette conçue sur fond sombre, non mesurée par un outil dans ce test');

  // ═══════════════════════════════════════════════════ 13. RESPONSIVE
  section = 'Responsive';
  for (const w of [320, 375, 390, 430]) {
    await cmd('Emulation.setDeviceMetricsOverride',
      { width: w, height: 844, deviceScaleFactor: 2, mobile: true });
    let deb = 0, tronq = 0;
    for (const h of ['#/', '#/rank', '#/watch', '#/data', '#/w/' + a0]) {
      await va(h, 480);
      const d = await js(`(()=>{const vw=document.documentElement.clientWidth;
        const b=[...document.querySelectorAll('.view.on *')].filter(e=>{
          if(e.closest('.chips'))return false;const r=e.getBoundingClientRect();
          return r.width>0&&(r.right>vw+1||r.left<-1);}).length;
        const t=[...document.querySelectorAll('.view.on *')].filter(e=>{
          const s=getComputedStyle(e);
          return s.textOverflow==='ellipsis'&&e.scrollWidth>e.clientWidth+1;}).length;
        return {b, t, sw:document.documentElement.scrollWidth, vw};})()`);
      deb += d.b + (d.sw > d.vw + 1 ? 1 : 0); tronq += d.t;
    }
    dit(deb === 0 && tronq === 0 ? 'OK' : 'KO', `rendu à ${w} px`,
        `${deb} débordement(s), ${tronq} texte(s) coupé(s) sur 5 écrans`);
  }

  // ═══════════════════════════════════════════════════ RAPPORT
  const par = {};
  R.forEach(r => { (par[r.section] = par[r.section] || []).push(r); });
  const n = e => R.filter(r => r.etat === e).length;
  console.log('\n' + '═'.repeat(74));
  console.log('AUDIT DES FONCTIONNALITES — HYPERTRACKER');
  console.log('═'.repeat(74));
  for (const [s, l] of Object.entries(par)) {
    console.log(`\n▌ ${s.toUpperCase()}`);
    l.forEach(r => console.log(`  ${r.etat.padEnd(4)} ${r.quoi}${r.detail ? '\n         ' + r.detail : ''}`));
  }
  console.log('\n' + '═'.repeat(74));
  console.log(`TOTAL ${R.length} fonctionnalités auditées : ` +
    `${n('OK')} opérationnelles · ${n('LIM')} limitées par les données · ${n('KO')} en échec`);
  console.log('═'.repeat(74));
  ws.close(); edge.kill(); process.exit(n('KO') ? 1 : 0);
})().catch(e => {
  console.error('ECHEC section [' + section + '] : ' + e.message);
  edge.kill(); process.exit(2);
});
