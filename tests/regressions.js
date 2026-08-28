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
  // Les phrases repetees a l'identique sont des index dans `lib` : les resoudre
  // ici evite qu'un controle devienne muet le jour ou une phrase se repete.
  const LIB = app.lib || [];
  const phr = l => (l || []).map(x => typeof x === 'number' ? (LIB[x] || '') : x);

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
  const enForts = pfHauts.filter(w => phr(w.forts).some(x => /rofit factor/.test(x)));
  vrai('aucun profit factor > 10 n’est présenté comme un point fort',
    enForts.length === 0, enForts.length + ' wallets');
  const enRisques = pfHauts.filter(w => phr(w.risques).some(x => /dégénérée/.test(x)));
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

  // ══════════════════════════════════════════════ A1 — contraste mesure
  // Pas de jeton relu a la main : on parcourt le DOM RENDU, on remonte au
  // premier fond opaque reel et on applique la formule WCAG. Un audit qui lit
  // la feuille de style ne voit pas ce que l'oeil voit.
  etape = 'A1 contraste WCAG';
  const AUDIT_CONTRASTE = `(() => {
    const lin = c => { c /= 255; return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4); };
    const L = ([r,g,b]) => 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b);
    const rgb = s => { const m = String(s).match(/[\\d.]+/g); return m ? m.slice(0,3).map(Number) : null; };
    const alpha = s => { const m = String(s).match(/[\\d.]+/g); return m && m.length > 3 ? +m[3] : 1; };
    const melange = (fg, bg, a) => fg.map((v,i) => v*a + bg[i]*(1-a));
    const fondDe = el => {
      let n = el;
      while (n && n !== document.documentElement) {
        const s = getComputedStyle(n), c = rgb(s.backgroundColor);
        if (c && alpha(s.backgroundColor) > 0.9) return c;
        n = n.parentElement;
      }
      return rgb(getComputedStyle(document.body).backgroundColor) || [0,0,0];
    };
    const ratio = (a, b) => { const la = L(a), lb = L(b);
      return (Math.max(la,lb) + 0.05) / (Math.min(la,lb) + 0.05); };
    const mauvais = [];
    document.querySelectorAll('*').forEach(el => {
      if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') return;
      const s = getComputedStyle(el);
      if (s.visibility === 'hidden' || +s.opacity === 0) return;
      // On ne mesure QUE les elements qui portent eux-memes du texte visible.
      const propre = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      if (!propre) return;
      const fg = rgb(s.color);
      if (!fg || alpha(s.color) < 0.05) return;      // texte volontairement invisible
      const bg = fondDe(el);
      const px = parseFloat(s.fontSize), gras = +s.fontWeight >= 600;
      const seuil = (px >= 24 || (px >= 18.66 && gras)) ? 3 : 4.5;
      const r = ratio(alpha(s.color) < 1 ? melange(fg, bg, alpha(s.color)) : fg, bg);
      if (r < seuil - 0.005) mauvais.push({
        t: el.tagName.toLowerCase() + '.' + String(el.className || '').split(' ')[0],
        px: Math.round(px * 10) / 10, r: Math.round(r * 100) / 100, seuil,
        txt: el.textContent.trim().slice(0, 24) });
    });
    return mauvais;
  })()`;
  // L'audit doit d'abord prouver QU'IL MESURE. Sans cette sentinelle, une
  // expression cassee rend « 0 defaut » et se lit comme une reussite — c'est
  // exactement ce qui est arrive ici.
  const sentinelle = await js(`(() => {
    const d = document.createElement('div');
    d.style.cssText = 'color:#4C5D6B;font-size:11px;position:fixed;top:0;left:0';
    d.textContent = 'sentinelle';
    document.body.appendChild(d);
    return d; })() && ${AUDIT_CONTRASTE}.filter(x => x.txt === 'sentinelle').length`);
  await js(`[...document.querySelectorAll('div')].filter(d=>d.textContent==='sentinelle'
    && d.style.position==='fixed').forEach(d=>d.remove())`);
  vrai('l’audit de contraste sait détecter un texte fautif',
    sentinelle === 1, 'la sentinelle à 2,84:1 est passée inaperçue : audit inopérant');

  for (const h of ['#/', '#/rank', '#/data']) {
    await va(h, 800);
    const m = await js(AUDIT_CONTRASTE);
    vrai(`contraste AA sur ${h}`, m.length === 0,
      m.slice(0, 4).map(x => `${x.t} ${x.px}px ${x.r}:1 < ${x.seuil} « ${x.txt} »`).join(' | '));
  }
  await va('#/w/' + trois[0], 900);
  await js(`(()=>{const d=document.getElementById('plus');
    d.open=true; d.dispatchEvent(new Event('toggle'));})()`);
  await dodo(700);
  const mFiche = await js(AUDIT_CONTRASTE);
  vrai('contraste AA sur la fiche, panneau ouvert', mFiche.length === 0,
    mFiche.slice(0, 4).map(x => `${x.t} ${x.px}px ${x.r}:1 « ${x.txt} »`).join(' | '));

  // ══════════════════════════════════════════════ A2 — cibles tactiles
  // 44 px, pas 32 : c'est le minimum que les deux plateformes recommandent, et
  // la legende de qualite — qui est AUSSI un filtre — n'en faisait que 21.
  etape = 'A2 cibles tactiles 44 px';
  const AUDIT_CIBLES = `[...document.querySelectorAll(
      'button, input, select, [role="button"], a[href]')]
    .filter(e => { const s = getComputedStyle(e);
      if (s.visibility === 'hidden' || s.display === 'none') return false;
      const r = e.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && (r.height < 43.5 || r.width < 43.5); })
    .map(e => e.tagName.toLowerCase() + '.' + String(e.className||'').split(' ')[0]
      + ' ' + Math.round(e.getBoundingClientRect().width) + 'x'
      + Math.round(e.getBoundingClientRect().height))`;
  for (const [larg, nom] of [[320, 'iPhone SE'], [390, 'iPhone 13']]) {
    await metrique(larg, 844);
    for (const h of ['#/', '#/rank']) {
      await va(h, 700);
      const c = await js(AUDIT_CIBLES);
      vrai(`cibles tactiles ≥ 44 px — ${nom} ${h}`, c.length === 0,
        [...new Set(c)].slice(0, 5).join(' | '));
    }
  }
  await metrique(390, 844);

  // ══════════════════════════════════════════════ A4 — le défilement se voit
  etape = 'A4 affordance de défilement';
  await va('#/rank', 700);
  vrai('les bandes qui défilent le montrent',
    await js(`[...document.querySelectorAll('.chips')].every(c => {
      const s = getComputedStyle(c);
      return /gradient/.test(s.maskImage || s.webkitMaskImage || ''); })`),
    'aucun fondu au bord');
  vrai('elles débordent bien — sinon le contrôle ne prouverait rien',
    await js(`[...document.querySelectorAll('.chips')].some(c => c.scrollWidth > c.clientWidth + 4)`),
    'tout tient a l ecran');

  // ══════════════════════════════════════════════ A5 — en-tête opaque
  etape = 'A5 en-tête opaque';
  vrai('rien ne transparaît derrière l’en-tête ni la navigation',
    await js(`['header','nav'].every(t => {
      const s = getComputedStyle(document.querySelector(t)).backgroundColor;
      const m = String(s).match(/[\\d.]+/g);
      return m && (m.length < 4 || +m[3] >= 0.999); })`),
    'fond translucide : le flou n’est pas garanti par tous les moteurs');

  // ══════════════════════════════════════════════ P — la charge utile
  // Une page statique porte tout son poids au premier octet : pas de chargement
  // differe, pas de pagination serveur. Chaque kilo-octet est paye par tout le
  // monde, y compris pour des fiches que personne n'ouvrira.
  etape = 'P poids et fidélité';
  const octets = fs.statSync(path.join(DATA, 'app.html')).size;
  const ko = Math.round(octets / 1024);
  vrai('la page a fondu de moitié', ko < 700, ko + ' Ko');
  console.log(`  ·   poids de la page : ${ko} Ko`);

  // LA DECIMATION NE DOIT RIEN COUTER AU DRAWDOWN. Il n'est plus stocke : il se
  // deduit de cette courbe. Un point de sommet perdu, et le repli recalcule
  // sous-estime sans que rien ne le signale.
  const ecarts = [];
  for (const w of W) {
    if (!w.eq || !w.eq.v || w.dd == null) continue;
    let sommet = 0, pire = 0;
    for (const v of w.eq.v) { sommet = Math.max(sommet, v); pire = Math.max(pire, sommet - v); }
    ecarts.push(Math.abs(pire - w.dd));
  }
  vrai('le drawdown déduit reste exact après décimation',
    ecarts.length > 0 && Math.max(...ecarts) < 0.021,
    `${ecarts.length} wallets, écart max ${Math.max(...ecarts).toFixed(4)}`);

  // LA COURBE FINIT TOUJOURS SUR LE PnL AFFICHE. C'est le defaut qui avait
  // touche 39 wallets sur 231 ; la decimation est exactement le genre de
  // changement qui le ferait revenir.
  const fins = W.filter(w => w.eq && w.eq.v && w.eq.v.length
    && Math.abs(w.eq.v[w.eq.v.length - 1] - w.pnl) > 0.02);
  vrai('la courbe se termine sur le PnL réel', fins.length === 0,
    fins.slice(0, 3).map(w => w.a.slice(0, 10)).join(' '));

  // RIEN NE VOYAGE SANS ETRE LU. Les champs morts sont un cout paye par tout le
  // monde pour personne.
  const morts = ['prov', 'rd', 'pire_serie'].filter(k => k in W[0]);
  vrai('aucun champ mort n’est embarqué', morts.length === 0, morts.join(', '));
  vrai('les 315 fiches de réputation ne sont plus embarquées',
    await js(`typeof RP.wallets === 'undefined' && typeof RP.n_wallets === 'number'`),
    'le document complet voyage encore');

  // La serie mensuelle ne transporte plus que des comptes : les etiquettes se
  // deduisent. Encore faut-il qu'elles se deduisent JUSTE.
  await va('#/w/' + trois[0], 900);
  await js(`(()=>{const d=document.getElementById('plus');
    d.open=true; d.dispatchEvent(new Event('toggle'));})()`);
  await dodo(700);
  vrai('les étiquettes de mois se déduisent correctement',
    await js(`(()=>{const w=byA['${trois[0]}'];
      if(!w.m0||!w.m.length) return true;
      const der=moisApres(w.m0, w.m.length-1);
      const d=new Date(w.t1);
      return der === d.getUTCFullYear()+'-'+String(d.getUTCMonth()+1).padStart(2,'0');})()`),
    'le dernier mois déduit ne tombe pas sur le dernier trade');

  // ══════════════════════════════════════════════ D1 — la recherche
  // L'application propose un bouton « Groupée » qui copie « 0x F2C9 C2EB … ».
  // Recolle dans son propre champ de recherche : zero resultat. A l'inverse
  // « 1 » remontait 211 wallets, la comparaison etant un indexOf brut.
  etape = 'D1 recherche';
  await cmd('Page.navigate', { url: URL + '#/rank' });
  await dodo(2200);
  await js(`document.querySelector('[data-f="tous"]').click()`); await dodo(400);
  const cherche = async v => {
    await js(`(()=>{const q=document.getElementById('q');
      q.value=${JSON.stringify(v)}; q.dispatchEvent(new Event('input'));})()`);
    await dodo(400);
    return js(`courant.length`);
  };
  const cible = W[4];
  const groupee = '0x' + cible.a.slice(2).replace(/(.{4})/g, '$1 ').trim().toUpperCase();
  vrai('l’adresse groupée que l’application copie se retrouve',
    (await cherche(groupee)) === 1, `« ${groupee.slice(0, 24)}… » -> ` + await js(`courant.length`));
  const rang7 = W.find(w => w.rang === 7);
  vrai('une requête numérique est un rang, pas un fragment hexadécimal',
    (await cherche('7')) === 1 && (await js(`courant[0].a`)) === rang7.a,
    await js(`courant.length`) + ' résultats');
  vrai('une bande se cherche aussi',
    (await cherche('G01')) === W.filter(w => w.groupe === 1).length,
    await js(`courant.length`) + ' vs ' + W.filter(w => w.groupe === 1).length);
  await js(`document.getElementById('qc').click()`); await dodo(400);

  // ══════════════════════════════════════════════ D2 — rien ne se cache
  // La requete etait ecrite dans localStorage : on revenait trois jours plus
  // tard, le classement etait filtre, le compteur annoncait un total reduit, et
  // la seule trace vivait hors ecran des 200 px de defilement.
  etape = 'D2 la requête ne survit pas';
  await cherche('0xa');
  // « On revient trois jours plus tard » : un CHARGEMENT NEUF, pas un
  // rechargement. Recharger la meme URL fait restaurer les champs de formulaire
  // par le navigateur lui-meme, ce qui n'a rien a voir avec la persistance
  // qu'on mesure ici — et faisait echouer le controle sur un faux motif.
  vrai('la requête n’est pas écrite dans le stockage local',
    (await js(`(JSON.parse(localStorage.getItem('ht.etat')||'{}').q||'')`)) === '',
    'stockée : « ' + await js(`(JSON.parse(localStorage.getItem('ht.etat')||'{}').q||'')`) + ' »');
  await cmd('Page.navigate', { url: 'about:blank' });
  await dodo(400);
  await cmd('Page.navigate', { url: URL + '#/rank' });
  await dodo(2200);
  vrai('elle ne ressuscite pas à la visite suivante',
    (await js(`document.getElementById('q').value`)) === ''
    && (await js(`ETAT.q`)) === '',
    'requête ressuscitée : « ' + await js(`document.getElementById('q').value`) + ' »');
  vrai('le tri et le filtre, eux, restent mémorisés',
    (await js(`JSON.parse(localStorage.getItem('ht.etat')||'{}').filtre`)) === 'tous',
    'préférence perdue');

  // ══════════════════════════════════════════════ D6 — la touche Entrée
  // Le gestionnaire etait pose sur `document` : tout Entree hors d'un bouton,
  // d'un champ ou d'un summary declenchait une navigation.
  etape = 'D6 portée du clavier';
  await js(`location.hash='#/data'`); await dodo(700);
  const avantE = await js(`location.hash`);
  await js(`document.querySelector('#dh .note').dispatchEvent(
    new KeyboardEvent('keydown', {key:'Enter', bubbles:true}))`);
  await dodo(500);
  vrai('Entrée hors d’une liste ne navigue pas',
    (await js(`location.hash`)) === avantE,
    avantE + ' -> ' + await js(`location.hash`));

  // ══════════════════════════════════════════════ D7 — le geste
  etape = 'D7 le doigt ne fait pas deux choses';
  await va('#/w/' + trois[0], 900);
  vrai('un graphique prend la main sur le geste',
    await js(`getComputedStyle(document.getElementById('g1')).touchAction === 'none'`),
    'le navigateur défile pendant qu’on suit la courbe');

  // ══════════════════════════════════════════════ D8 — l’âge de la donnée
  // Dates absolues dans une page statique consultee des semaines plus tard :
  // rien ne disait que la donnee avait vieilli.
  etape = 'D8 la donnée porte son âge';
  await js(`location.hash='#/data'`); await dodo(800);
  vrai('la fraîcheur est relative, pas seulement absolue',
    (await js(`document.querySelectorAll('#dh .age').length`)) >= 2,
    await js(`document.querySelectorAll('#dh .age').length`) + ' mentions d’âge');
  vrai('l’âge sait passer en alerte', await js(`(()=>{
    const e=document.querySelector('#dh .age'); if(!e) return false;
    const av=e.className;
    // On force une donnee vieille de trois mois et on regarde si ca se voit.
    const t=Date.now()-90*24*3.6e6;
    const h=age(t,48);
    return /vieux/.test(h) && !/vieux/.test(age(Date.now()-3.6e6,48));})()`),
    'un relevé de trois mois se présente comme un relevé frais');

  // ══════════════════════════════════════════════ D4 — rien d’interne à l’écran
  // Cette page est partagee par lien : « Lancez python -m ht.matin » s'adressait
  // a l'operateur et etait lu par tout le monde, en devoilant le nom du module
  // et l'heure de la tache planifiee.
  etape = 'D4 aucune commande interne dans la page';
  const brut = fs.readFileSync(path.join(DATA, 'app.html'), 'utf8');
  const fuites = ['python -m ht.', 'ht.matin', 'HYPERTRACKER_API_TOKEN', 'registre.db']
    .filter(x => brut.indexOf(x) >= 0);
  vrai('aucune commande ni secret interne dans la page publiée',
    fuites.length === 0, fuites.join(', '));

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
