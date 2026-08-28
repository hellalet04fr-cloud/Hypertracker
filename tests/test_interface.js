/**
 * Test fonctionnel de l'interface, pilote par le protocole DevTools.
 *
 * Il verifie des PARCOURS REELS, pas la presence de balises : navigation entre
 * les trois espaces, survie des deux anciennes adresses, recherche, filtres,
 * tri, revelation progressive de la fiche, adresse complete et copiable,
 * graphiques dessines, infobulles tactiles, suivi persistant et reordonnable,
 * retour sans perte de contexte, etats vides, et absence de debordement
 * horizontal a quatre largeurs d'iPhone.
 */
const { spawn } = require('child_process');
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const URL = 'file:///C:/Users/maram/ht_data/app.html';
const PORT = 9781;

const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--no-first-run', '--no-default-browser-check', '--disable-sync',
  `--remote-debugging-port=${PORT}`, '--user-data-dir=' + process.env.TEMP + '/cdptest',
  'about:blank'], { stdio: 'ignore' });

const dodo = ms => new Promise(r => setTimeout(r, ms));
const vert = [], rouge = [];
let etape = 'demarrage';
const vrai = (nom, cond, detail) =>
  (cond ? vert : rouge).push(nom + (cond ? '' : '  << ' + detail));

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
  const cmd = (method, params) => new Promise((res, rej) => {
    const n = ++id;
    att.set(n, m => m.error ? rej(new Error(method + ' ' + m.error.message)) : res(m.result));
    ws.send(JSON.stringify({ id: n, method, params: params || {} }));
  });
  const js = async expr => {
    const r = await cmd('Runtime.evaluate',
      { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('JS: ' + r.exceptionDetails.text + ' :: ' +
      (r.exceptionDetails.exception && r.exceptionDetails.exception.description || ''));
    return r.result.value;
  };
  const va = async (h, ms) => { await js(`location.hash = '${h}'`); await dodo(ms || 700); };

  await cmd('Page.enable'); await cmd('Runtime.enable');
  await cmd('Emulation.setDeviceMetricsOverride',
    { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await cmd('Page.navigate', { url: URL });
  await dodo(2400);
  // Isolation : le profil Edge conserve le localStorage d'une execution a l'autre,
  // si bien qu'un test de watchlist RETIRAIT au lieu d'ajouter.
  await js(`localStorage.clear()`);
  await cmd('Page.navigate', { url: URL });
  await dodo(2200);

  etape = 'chargement';
  const NW = await js(`W.length`);
  vrai('population chargee', NW > 200, 'W.length=' + NW);

  // ---------------------------------------------------------- 1. LES 5 ESPACES
  etape = 'les trois espaces';
  vrai('trois entrees de navigation',
    (await js(`document.querySelectorAll('nav button').length`)) === 3, 'nav incomplete');
  for (const [h, vue] of [['#/', 'v-jour'], ['#/rank', 'v-rank'], ['#/data', 'v-data']]) {
    await va(h);
    vrai(`espace ${h} affiche`,
      await js(`document.getElementById('${vue}').classList.contains('on')`), 'vue absente');
    vrai(`espace ${h} rempli`,
      (await js(`document.getElementById('${vue}').textContent.trim().length`)) > 120, 'vide');
  }
  // Deux espaces ont ete absorbes ; leurs adresses doivent continuer d'aboutir.
  // Un lien mis en favori ne cesse pas d'exister parce qu'un onglet disparait.
  await va('#/watch');
  vrai('l ancienne adresse du suivi aboutit',
    (await js(`document.getElementById('v-rank').classList.contains('on')`))
    && (await js(`ETAT.filtre`)) === 'suivi', 'alias /watch perdu');
  await va('#/disco');
  vrai('l ancienne adresse de la decouverte aboutit',
    await js(`document.getElementById('v-jour').classList.contains('on')`), 'alias /disco perdu');
  await js(`document.querySelector('[data-f="ranked"]').click()`); await dodo(300);

  // ---------------------------------------------------------- 2. ACCUEIL
  etape = 'accueil';
  await va('#/');
  vrai('bandeau de synthese present',
    (await js(`document.querySelectorAll('#jband .band>div').length`)) === 4, 'bandeau absent');
  vrai('les sections vides sont repliees',
    (await js(`document.querySelectorAll('#jour details.det').length`)) > 0, 'pas de repli');
  vrai('le contenu reel precede les sections vides', await js(`(() => {
    const t = document.getElementById('jour').innerHTML;
    const rien = t.indexOf('Rien à signaler');
    const plein = t.indexOf('class="li"');
    return rien < 0 || (plein >= 0 && plein < rien); })()`), 'ordre incorrect');
  vrai('les sections repliees nomment ce qui est vide', await js(`
    [...document.querySelectorAll('#jour details.det')].every(d =>
      d.querySelector('summary').textContent.trim().length > 3
      && d.querySelector('.note').textContent.trim().length > 30)`), 'repli muet');

  // ---------------------------------------------------------- 3. CLASSEMENT
  etape = 'classement';
  await va('#/rank');
  const NR = await js(`W.filter(w => w.st === 'RANKED').length`);
  vrai('filtre Classes par defaut', (await js(`courant.length`)) === NR,
    'courant=' + await js(`courant.length`) + ' attendu ' + NR);
  vrai('compteur d en-tete rempli',
    (await js(`document.getElementById('cnt').textContent`)) === String(NR), 'compteur vide');
  const n0 = await js(`document.querySelectorAll('#liste .row').length`);
  vrai('premiere page rendue', n0 > 0 && n0 <= 24, 'lignes=' + n0);

  // CINQ grandeurs, pas quatorze. La refonte a deplace les neuf autres sur la
  // fiche : ce que la ligne doit prouver, c'est qu'elle porte encore le rang,
  // l'adresse, la mesure avec son rail, le volume et la fraicheur.
  vrai('chaque ligne porte les cinq essentiels', await js(`(() => {
    const r = document.querySelector('#liste .row'), t = r.textContent;
    return !!r.querySelector('.no') && !!r.querySelector('.adr')
      && !!r.querySelector('.sc') && !!r.querySelector('svg.rail')
      && !!r.querySelector('.r2') && /trades/.test(t); })()`), 'ligne incomplete');

  vrai('la ligne ne porte PLUS les grandeurs deplacees', await js(`(() => {
    const t = document.querySelector('#liste .row').textContent;
    return !/Drawdown|Profit factor|Concentration/.test(t); })()`), 'ligne encore chargee');

  vrai('un score ne parait JAMAIS sans son rail', await js(`
    [...document.querySelectorAll('#liste .row')].every(r =>
      !r.querySelector('.sc') || r.querySelector('svg.rail'))`), 'score orphelin');

  // La provenance est une exception marquee, pas un badge sur chaque ligne :
  // 262 mentions « Dérivé » identiques n'informeraient personne.
  const nObsListe = await js(`W.filter(w => !!w.obs).length`);
  vrai('la provenance ne marque que l exception', nObsListe > 0 && nObsListe < 20,
    nObsListe + ' wallets observes');

  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(350);
  vrai('filtre Tous', (await js(`courant.length`)) === NW, 'tous=' + await js(`courant.length`));
  const nObs = await js(`W.filter(w => !!w.obs).length`);
  await js(`document.querySelector('[data-f="obs"]').click()`); await dodo(300);
  vrai('filtre Observe', (await js(`courant.length`)) === nObs, 'obs incorrect');
  const nAct = await js(`W.filter(w => (w.r30 ?? 0) > 0).length`);
  await js(`document.querySelector('[data-f="actif"]').click()`); await dodo(300);
  vrai('filtre Actifs 30 j', (await js(`courant.length`)) === nAct, 'actifs incorrect');
  const nq1 = await js(`W.filter(w => w.conf_lab === 'faible').length`);
  await js(`document.querySelector('[data-c="q1"]').click()`); await dodo(300);
  vrai('la convention sert de filtre', (await js(`courant.length`)) === nq1, 'q1 incorrect');
  await js(`document.querySelector('[data-c="q1"]').click()`); await dodo(300);
  vrai('second appui relache le filtre', (await js(`courant.length`)) === NW, 'non relache');

  etape = 'tris';
  const ordres = {};
  for (const k of ['score', 'actif', 'conf', 'dd', 'n', 'drang', 'recent', 'sr', 'stab', 'conc']) {
    await js(`document.querySelector('[data-t="${k}"]').click()`); await dodo(200);
    ordres[k] = await js(`courant.slice(0,5).map(w => w.a).join(',')`);
  }
  vrai('les 10 tris produisent des ordres distincts',
    new Set(Object.values(ordres)).size >= 8,
    new Set(Object.values(ordres)).size + ' ordres distincts sur 10');
  await js(`document.querySelector('[data-t="n"]').click()`); await dodo(250);
  vrai('tri par trades decroissant',
    await js(`courant.slice(0,20).every((w,i,a) => i===0 || a[i-1].n >= w.n)`), 'non monotone');
  await js(`document.querySelector('[data-t="recent"]').click()`); await dodo(250);
  vrai('tri par dernier trade decroissant',
    await js(`courant.slice(0,20).every((w,i,a) => i===0 || (a[i-1].t1||0) >= (w.t1||0))`),
    'non monotone');
  await js(`document.querySelector('[data-t="score"]').click()`); await dodo(250);

  etape = 'recherche';
  const cible = await js(`W[8].a`);
  await js(`(() => { const q = document.getElementById('q');
    q.value = ${JSON.stringify(cible)}; q.dispatchEvent(new Event('input')); })()`);
  await dodo(400);
  vrai('recherche par adresse complete', (await js(`courant.length`)) === 1, 'resultats != 1');
  await js(`(() => { const q = document.getElementById('q');
    q.value = ${JSON.stringify(cible.slice(0, 10))}; q.dispatchEvent(new Event('input')); })()`);
  await dodo(400);
  vrai('recherche par adresse partielle', (await js(`courant.length`)) >= 1, 'aucun resultat');
  await js(`document.getElementById('qc').click()`); await dodo(350);
  vrai('effacement restaure la selection', (await js(`courant.length`)) === NW, 'non restaure');

  // ---------------------------------------------------------- 4. FICHE WALLET
  etape = 'fiche wallet';
  await js(`window.scrollTo(0, 800)`); await dodo(250);
  await js(`document.querySelectorAll('#liste .row')[2].click()`);
  await dodo(1100);
  vrai('un clic ouvre une VRAIE page',
    (await js(`location.hash`)).indexOf('#/w/0x') === 0, 'hash=' + await js(`location.hash`));
  const adr = await js(`document.getElementById('adr').textContent.replace(/\\s/g,'')`);
  const attendu = await js(`location.hash.slice(4)`);
  vrai('adresse complete : 42 caracteres', adr.length === 42, 'longueur=' + adr.length);
  vrai('adresse = celle du wallet', adr.toLowerCase() === attendu.toLowerCase(), 'discordance');
  vrai('aucune ellipse dans l adresse', adr.indexOf('\u2026') < 0, 'tronquee');

  await cmd('Browser.grantPermissions',
    { permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite'] }).catch(() => {});
  await js(`document.getElementById('cp').click()`); await dodo(450);
  vrai('la copie donne un retour visuel',
    /copi|refus/i.test(await js(`document.getElementById('cp').textContent`)), 'aucun retour');

  // REVELATION PROGRESSIVE : l'essentiel se lit sans rien ouvrir, le detail
  // vient au toucher. Il faut donc verifier les DEUX etats.
  const cvs0 = await js(`[...document.querySelectorAll('#v-wallet canvas')]
    .filter(c => c.getBoundingClientRect().width > 0).length`);
  vrai('la fiche fermee reste legere', cvs0 <= 3, cvs0 + ' graphiques dessines d emblee');
  vrai('le detail est annonce, pas cache', await js(`(() => {
    const d = document.getElementById('plus');
    return !!d && !d.open && /Tout voir/.test(d.textContent); })()`), 'repli absent');
  vrai('les mesures secondaires sont bien repliees',
    await js(`document.getElementById('reste').hidden === true`), 'deja visible');
  await js(`(() => { const d = document.getElementById('plus');
    d.open = true; d.dispatchEvent(new Event('toggle')); })()`);
  await dodo(700);
  vrai('l ouverture revele les mesures',
    await js(`document.getElementById('reste').hidden === false`), 'reste masque');
  const cvs = await js(`[...document.querySelectorAll('#v-wallet canvas')]
    .map(c => c.width + 'x' + c.height)`);
  vrai('au moins 6 graphiques dessines', cvs.length >= 6, 'canvas=' + cvs.length);
  vrai('aucun canvas de taille nulle', cvs.every(s => s.indexOf('0x') !== 0), JSON.stringify(cvs));

  vrai('les graphiques ont une infobulle au toucher', await js(`(() => {
    const cv = document.getElementById('g1');
    if (!cv) return false;
    const r = cv.getBoundingClientRect();
    cv.dispatchEvent(new PointerEvent('pointerdown', {clientX: r.left + r.width/2,
      clientY: r.top + 20, bubbles: true, pointerType: 'touch'}));
    const t = cv.closest('.well').querySelector('.tip');
    return !!t && t.classList.contains('on') && t.textContent.length > 2; })()`),
    'aucune infobulle');

  vrai('les six grandeurs sont nommees separement', await js(`(() => {
    const t = document.getElementById('v-wallet').textContent;
    return /Performance/.test(t) && /Probabilité calibrée/.test(t)
      && /Incertitude/.test(t) && /Qualité des données/.test(t); })()`),
    'grandeurs confondues');

  vrai('les donnees absentes affichent N/D', await js(`
    document.getElementById('v-wallet').textContent.indexOf('N/D') >= 0`), 'aucun N/D');
  vrai('funding et ROI restent N/D', await js(`(() => {
    const c = [...document.querySelectorAll('#v-wallet .cell')];
    const f = c.find(x => /Funding/.test(x.textContent));
    const r = c.find(x => /ROI/.test(x.textContent));
    return !!f && !!r && /N\\/D/.test(f.textContent) && /N\\/D/.test(r.textContent); })()`),
    'valeur inventee');

  vrai('la provenance est etiquetee',
    (await js(`document.querySelectorAll('#v-wallet .bg').length`)) >= 1, 'badges absents');
  vrai('la provenance est expliquee, pas seulement etiquetee', await js(`
    /Dérivé|Observé/.test(document.querySelector('#v-wallet .prot h4').textContent)`),
    'aucune explication de provenance');
  vrai('explication du classement presente',
    (await js(`document.querySelectorAll('#v-wallet .wl').length`)) > 0, 'aucune explication');
  vrai('le drawdown affiche vient de la courbe deduite', await js(`(() => {
    const w = byA[location.hash.slice(4)];
    const c = drawdown(w);
    if (!c.length || w.dd == null) return true;
    return Math.abs(Math.max(...c.map(p => -p[1])) - w.dd) < 0.03; })()`),
    'deduction infidele');
  vrai('aucun emoji dans la fiche',
    !(await js(`document.getElementById('v-wallet').innerHTML`))
      .match(/[\u{1F300}-\u{1FAFF}]/u), 'emoji trouve');

  // ---------------------------------------------------------- 5. WATCHLIST
  etape = 'watchlist';
  await js(`document.getElementById('wt').click()`); await dodo(300);
  vrai('ajout au suivi', (await js(`WATCH.length`)) === 1, 'taille=' + await js(`WATCH.length`));
  vrai('suivi persiste',
    (await js(`JSON.parse(localStorage.getItem('ht.watch')).length`)) === 1, 'non persiste');
  await js(`WATCH.push(W[0].a === WATCH[0] ? W[1].a : W[0].a); majWatch()`);
  // Le suivi n'est plus un espace : c'est un filtre du classement. Rien n'est
  // perdu — l'ecran retrecit, la fonction reste entiere.
  await va('#/rank');
  await js(`document.querySelector('[data-f="suivi"]').click()`); await dodo(450);
  vrai('le suivi est un filtre du classement',
    (await js(`document.querySelectorAll('#liste .row').length`)) === 2, 'affichage incorrect');
  vrai('le suivi s ordonne selon le choix de l utilisateur',
    (await js(`ETAT.tri`)) === 'mien', 'tri=' + await js(`ETAT.tri`));
  vrai('l ordre affiche EST l ordre enregistre',
    await js(`[...document.querySelectorAll('#liste .row')].map(r => r.dataset.a)
      .join(',') === WATCH.join(',')`), 'ordre affiche different de WATCH');
  const av = await js(`WATCH.join(',')`);
  await js(`document.querySelectorAll('#liste [data-mv]')[1].click()`); await dodo(400);
  vrai('reordonnancement du suivi', (await js(`WATCH.join(',')`)) !== av, 'ordre inchange');
  await js(`document.querySelectorAll('#liste [data-rm]')[0].click()`); await dodo(400);
  vrai('retrait du suivi', (await js(`WATCH.length`)) === 1, 'non retire');
  // Les commandes de reordonnancement n'apparaissent QUE sous ce filtre : une
  // commande qui ne sert que la n'a pas a peser sur les 267 autres releves.
  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(400);
  vrai('les commandes de suivi restent dans leur filtre',
    (await js(`document.querySelectorAll('#liste [data-mv]').length`)) === 0,
    'commandes hors contexte');

  // ---------------------------------------------------------- 6. RETOUR
  etape = 'retour sans perte de contexte';
  await va('#/rank');
  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(350);
  await js(`window.scrollTo(0, 800)`); await dodo(400);
  const sc2 = await js(`window.scrollY`);
  await js(`document.querySelectorAll('#liste .row')[1].click()`); await dodo(900);
  await js(`history.back()`); await dodo(1000);
  vrai('retour au classement',
    await js(`document.getElementById('v-rank').classList.contains('on')`), 'pas revenu');
  vrai('position de defilement restituee',
    Math.abs((await js(`window.scrollY`)) - sc2) < 90,
    sc2 + ' -> ' + await js(`window.scrollY`));
  vrai('selection conservee au retour', (await js(`courant.length`)) === NW, 'selection perdue');

  // ---------------------------------------------------------- 7. ETATS VIDES
  etape = 'etats vides';
  await js(`WATCH.length = 0; majWatch()`);
  await va('#/rank');
  await js(`document.querySelector('[data-f="suivi"]').click()`); await dodo(450);
  vrai('suivi vide explicite',
    (await js(`document.querySelectorAll('#liste .empty').length`)) === 1, 'etat vide absent');
  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(350);
  await js(`(() => { const q = document.getElementById('q');
    q.value = 'zzzzzzintrouvable'; q.dispatchEvent(new Event('input')); })()`);
  await dodo(400);
  vrai('recherche sans resultat explicite',
    (await js(`document.querySelectorAll('#liste .empty').length`)) === 1, 'etat vide absent');
  await js(`document.getElementById('qc').click()`); await dodo(300);

  etape = 'wallet inconnu';
  await va('#/w/0x' + '0'.repeat(40), 800);
  vrai('wallet inconnu gere',
    (await js(`document.querySelectorAll('#v-wallet .empty').length`)) === 1, 'pas d etat vide');

  // ---------------------------------------------------------- 8. RESPONSIVE
  etape = 'responsive';
  for (const w of [320, 375, 390, 430]) {
    await cmd('Emulation.setDeviceMetricsOverride',
      { width: w, height: 844, deviceScaleFactor: 2, mobile: true });
    for (const h of ['#/', '#/rank', '#/disco', '#/watch', '#/data',
                     '#/w/' + (await js(`W[8].a`))]) {
      await va(h, 650);
      const d = await js(`(() => { const vw = document.documentElement.clientWidth;
        const bad = [...document.querySelectorAll('*')].filter(e => {
          if (e.closest('.chips')) return false;
          const r = e.getBoundingClientRect();
          return r.width > 0 && (r.right > vw + 1 || r.left < -1);
        }).map(e => e.tagName + '.' + String(e.className||'').split(' ')[0]);
        return {sw: document.documentElement.scrollWidth, vw, bad: [...new Set(bad)].slice(0,4)};
      })()`);
      vrai(`aucun debordement ${w}px ${h.slice(0, 11)}`,
        d.sw <= d.vw + 1 && d.bad.length === 0,
        `scrollW=${d.sw} vw=${d.vw} ${JSON.stringify(d.bad)}`);
    }
  }

  // ---------------------------------------------------------- 9. ACCESSIBILITE
  etape = 'accessibilite';
  await cmd('Emulation.setDeviceMetricsOverride',
    { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await va('#/rank');
  const petits = await js(`[...document.querySelectorAll('nav button, .chip, .btn')]
    .filter(e => { const r = e.getBoundingClientRect();
      return r.height > 0 && r.height < 43.5; }).length`);
  vrai('zones tactiles >= 44px', petits === 0, petits + ' elements trop petits');
  vrai('les rails ont un role et un libelle', await js(`
    [...document.querySelectorAll('svg.rail')].every(s =>
      s.getAttribute('role') === 'img' && !!s.getAttribute('aria-label'))`), 'libelle absent');

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
