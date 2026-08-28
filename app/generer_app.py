#!/usr/bin/env python3
"""
Genere l'application mobile HyperTracker : un seul fichier HTML autonome.

DIRECTION : « RELEVE ». Une feuille de mesures de laboratoire, pas une pile de
cartes. Le produit tout entier tient dans UN objet — une mesure et son
incertitude — et la mise en page consiste a le rendre parfait puis a retirer
tout ce qui lui dispute l'attention.

    un chiffre n'est jamais montre sans l'echelle sur laquelle il a ete lu,
    ni sans l'incertitude avec laquelle il a ete lu.

Le dispositif INDEX + MORS reste la seule figure de l'application :
  - le SCORE est une POSITION : un index ambre sur un rail gradue 0-100 ;
  - l'INCERTITUDE est un ECARTEMENT : les machoires d'un pied a coulisse posees
    aux bornes de l'intervalle de credibilite a 95 % ;
  - la QUALITE DES DONNEES est une FERMETE DE TRAIT : machoires pleines,
    tiretees ou pointillees.

CE QUE LA REFONTE RETIRE, ET POURQUOI

  les cartes        267 boites qui se disputent l'attention deviennent une
                    sequence de releves separes par un filet. Le rythme fait le
                    travail que faisaient les bordures.
  deux couleurs     le vert et le rouge quittent la liste. Le signe se lit au
                    glyphe. L'ambre ne designe plus QUE l'estimation ponctuelle,
                    ce qui la rend impossible a manquer.
  une police        quatre familles devenaient une texture ; trois suffisent.
  neuf grandeurs    la ligne en portait quatorze. Cinq restent : rang, adresse,
                    mesure, volume, fraicheur. Les neuf autres n'ont pas disparu
                    — elles sont sur la fiche, ou on les lit vraiment.
  deux espaces      cinq onglets deviennent trois. « Suivi » etait deja un
                    filtre du classement ; « Decouverte » repond a la meme
                    question que « Aujourd'hui ». Rien n'est perdu, la surface
                    retrecit.

SIX GRANDEURS, JAMAIS CONFONDUES — performance, probabilite calibree,
incertitude, qualite des donnees, activite, provenance. L'interface d'origine
appelait « confiance » les deux premieres, ce qui produisait « confiance 30 % —
confiance elevee ».

CE MODULE NE CALCULE AUCUNE SCIENCE. Il n'expose que ce que le moteur a produit.
Toute grandeur absente s'affiche N/D — jamais zero, jamais estimee.

    python -m app.generer_app
"""
from __future__ import annotations

import json
import os

D = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
SORTIE = os.environ.get("HT_APP_OUT", os.path.join(D, "app.html"))

DATA = json.load(open(os.path.join(D, "app_data.json")))
_rep = os.path.join(D, "reputation_data.json")
REP = json.load(open(_rep)) if os.path.exists(_rep) else {"meta": {}, "wallets": []}


TPL = r"""<title>HyperTracker</title>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,maximum-scale=5">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0B0E11">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" media="print" onload="this.media='all'"
      href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=DM+Mono:wght@400;500&family=Instrument+Sans:wght@400;500;600&display=swap">
<noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=DM+Mono:wght@400;500&family=Instrument+Sans:wght@400;500;600&display=swap"></noscript>
<style>
/* ════════════════════════════════════════════════════════ SYSTEME
   Une feuille de releves. Registre unique sombre, assume : un instrument de
   mesure n'a pas de mode clair. Toutes les couleurs sont peintes explicitement,
   jamais heritees de l'hote.
   ──────────────────────────────────────────────────────────────── */
:root{
  /* --- deux surfaces, pas quatre : le fond, et le creux d'un trace --- */
  --fond:#0B0E11;
  --creux:#10141A;
  --filet:#1C222A;          /* separateur — la seule bordure de l'application */

  /* --- encres --- */
  --texte:#E6EAED;
  --clair:#FBFCFD;          /* les mesures majeures                          */
  --gris:#6E8697;           /* echelle, incertitude, libelles                */
  --faible:#4C5D6B;         /* second plan                                   */

  /* --- UNE couleur. L'ambre ne designe QUE l'estimation ponctuelle : le
         reserver a cela seul la rend impossible a manquer. Le rouge ne sert
         qu'aux marques de vigilance, sur la fiche uniquement. --- */
  --index:#F0A93B;
  --index-f:#33260F;
  --alerte:#D9705F;

  /* --- rythme : 4px, aucune valeur hors gamme --- */
  --e1:4px; --e2:8px; --e3:12px; --e4:16px; --e5:28px; --e6:44px;
  --sr:env(safe-area-inset-right); --sl:env(safe-area-inset-left);
  --nav:calc(54px + env(safe-area-inset-bottom));
  --marge:max(20px, var(--sl));
  --marge-d:max(20px, var(--sr));
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;min-width:0}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--fond);color:var(--texte);
  font:400 15px/1.55 "Instrument Sans","Helvetica Neue",Arial,sans-serif;
  overflow-x:hidden;overscroll-behavior-y:none;
  -webkit-font-smoothing:antialiased;
}
/* Chiffres TABULAIRES partout : une valeur qui danse quand elle change n'est
   pas une mesure. */
.mo,.sc,.big,.cell-v,.dv,.sc2,.adr{font-family:"DM Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums}

/* --- le seul style de libelle de l'application --- */
.lab{font:400 10px/1.4 "DM Mono",monospace;letter-spacing:.14em;
     text-transform:uppercase;color:var(--faible)}

/* ════════════════════════════════════════════════════════ ossature */
#app{padding-bottom:calc(var(--nav) + var(--e5));min-height:100vh}
.wrap{padding-left:var(--marge);padding-right:var(--marge-d)}
header{position:sticky;top:0;z-index:60;background:rgba(11,14,17,.92);
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  padding-top:env(safe-area-inset-top)}
.hrow{display:flex;align-items:baseline;gap:var(--e3);min-height:52px;
  padding:var(--e3) var(--marge-d) var(--e3) var(--marge)}
.htitle{flex:1}
.htitle h1{margin:0;font:700 15px/1.2 Archivo,sans-serif;letter-spacing:.2em;
  text-transform:uppercase;color:var(--clair)}
.htitle p{margin:4px 0 0;font:400 10px/1.3 "DM Mono",monospace;letter-spacing:.1em;
  color:var(--faible)}
.view{display:none;animation:f .18s ease both}
.view.on{display:block}
@keyframes f{from{opacity:0}to{opacity:1}}

/* Une section = un titre discret et un filet. Aucun encadrement. */
.sect{display:flex;align-items:baseline;gap:var(--e3);margin:var(--e6) 0 var(--e3)}
.sect .lab{flex:0 0 auto}
.sect::after{content:"";flex:1;height:1px;background:var(--filet)}
.sect .cpt{flex:0 0 auto;font:400 10px/1 "DM Mono",monospace;color:var(--faible)}

/* ════════════════════════════════════════════════════════ le releve
   PAS DE CARTE. Une sequence de mesures separees par un filet : le rythme fait
   le travail que faisaient 267 bordures. */
#liste{margin-top:var(--e2)}
.row{position:relative;display:block;padding:var(--e4) 0 var(--e4);cursor:pointer;
  border-bottom:1px solid var(--filet);transition:opacity .12s}
.row:active{opacity:.55}
.r0{display:flex;align-items:baseline;gap:var(--e2)}
.r0 .no{flex:0 0 auto;font:400 10px/1 "DM Mono",monospace;color:var(--faible);
  letter-spacing:.06em}
.r0 .adr{flex:0 0 auto;font-size:12px;color:var(--gris)}
.r0 .fin{margin-left:auto;display:flex;align-items:center;gap:var(--e2)}
.r1{display:flex;align-items:center;gap:var(--e3);margin-top:var(--e2)}
.sc{flex:0 0 auto;font-size:29px;font-weight:500;line-height:1;letter-spacing:-.035em;
  color:var(--index)}
.rail{flex:1 1 auto;display:block;width:100%;height:auto}
.r2{margin-top:var(--e2);font:400 11.5px/1.4 "Instrument Sans",sans-serif;
  color:var(--faible)}

/* --- provenance : un POINT, pas un badge. 262 badges identiques seraient du
       bruit ; seule l'exception — 5 wallets sur 267 — se marque. --- */
.bg{flex:0 0 auto;font:400 9.5px/1.4 "DM Mono",monospace;letter-spacing:.1em;
  text-transform:uppercase;color:var(--faible)}
.bg.obs{color:var(--index)}
.bg.obs::before{content:"";display:inline-block;width:5px;height:5px;
  border-radius:50%;background:var(--index);margin-right:5px;vertical-align:middle}
/* --- variation : un chevron, sans couleur. Le sens se lit a la forme. --- */
.dv{flex:0 0 auto;font-size:11px;color:var(--gris);white-space:nowrap}
.dv.nul{color:var(--faible)}

/* ════════════════════════════════════════════════════════ controles */
.srch{position:relative;margin:0 0 var(--e1)}
.srch input{width:100%;background:transparent;border:0;border-bottom:1px solid var(--filet);
  padding:var(--e3) 34px var(--e3) 0;color:var(--clair);
  font:400 15px/1 "DM Mono",monospace;outline:none;min-height:48px}
.srch input::placeholder{color:var(--faible);font-family:"Instrument Sans",sans-serif}
.srch input:focus{border-bottom-color:var(--gris)}
.srch .clr{position:absolute;right:0;top:0;bottom:0;width:34px;border:0;background:none;
  color:var(--gris);font-size:20px;cursor:pointer;display:none}
.srch.has .clr{display:block}

.chips{display:flex;gap:var(--e5);overflow-x:auto;scrollbar-width:none;
  padding:var(--e2) var(--marge-d) var(--e3) var(--marge);
  -webkit-overflow-scrolling:touch}
.chips::-webkit-scrollbar{display:none}
/* Un filtre actif n'est pas une pastille : c'est un mot souligne. */
.chip{flex:0 0 auto;background:none;border:0;padding:var(--e2) 0;cursor:pointer;
  white-space:nowrap;color:var(--faible);font:400 12px/1.2 "Instrument Sans",sans-serif;
  border-bottom:1px solid transparent;transition:color .12s,border-color .12s;
  min-height:36px}
.chip.on{color:var(--clair);border-bottom-color:var(--index)}
.chips .lab{flex:0 0 auto;align-self:center;padding-right:var(--e1)}

.btn{flex:0 0 auto;background:none;border:1px solid var(--filet);border-radius:1px;
  color:var(--gris);padding:var(--e3) var(--e4);cursor:pointer;
  font:400 10px/1 "DM Mono",monospace;letter-spacing:.12em;text-transform:uppercase;
  transition:color .15s,border-color .15s,background .15s;min-height:42px}
.btn.on,.btn.ok{background:var(--index);border-color:var(--index);color:var(--fond)}
.btn:active{border-color:var(--gris)}

/* ════════════════════════════════════════════════════════ fiche */
.wh{padding:var(--e5) var(--marge-d) 0 var(--marge)}
.adr{display:block;font-size:14px;line-height:1.75;color:var(--clair);
  word-break:break-all;letter-spacing:.03em;user-select:all;-webkit-user-select:all}
.arow{display:flex;align-items:center;gap:var(--e2);margin-top:var(--e4);flex-wrap:wrap}

/* LA MESURE — le seul objet mis en avant de toute l'application. */
.mesure{padding:var(--e6) 0 var(--e5);border-bottom:1px solid var(--filet)}
.big{font-size:76px;font-weight:500;line-height:.9;letter-spacing:-.05em;
  color:var(--index);margin:var(--e2) 0 var(--e4)}
.mini{display:flex;flex-direction:column;gap:var(--e2);margin-top:var(--e4)}
.mini .kv{display:flex;align-items:baseline;gap:var(--e3)}
.mini .kv span{flex:1 1 auto;font:400 10px/1.5 "DM Mono",monospace;letter-spacing:.1em;
  text-transform:uppercase;color:var(--faible)}
.mini .kv b{flex:0 0 auto;font:400 13px/1.5 "DM Mono",monospace;color:var(--gris);
  font-variant-numeric:tabular-nums}
.vern{display:flex;gap:3px;margin-top:var(--e3);max-width:120px}
.vern i{flex:1;height:2px;background:var(--filet);display:block}
.vern i.f{background:var(--gris)}
.apparat{margin:var(--e3) 0 0;font:400 italic 13px/1.5 "Instrument Sans",sans-serif;
  color:var(--faible)}

/* --- grille de mesures : pas de cellules encadrees, deux colonnes de lignes --- */
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
  column-gap:var(--e5);margin-top:var(--e2)}
.cell{display:flex;align-items:baseline;flex-wrap:wrap;gap:2px var(--e2);
  padding:var(--e3) 0;border-bottom:1px solid var(--filet)}
.cell-k{flex:1 1 auto;min-width:0;font:400 10px/1.4 "DM Mono",monospace;
  letter-spacing:.08em;text-transform:uppercase;color:var(--faible)}
.cell-v{flex:0 0 auto;margin-left:auto;font-size:14px;color:var(--texte);
  white-space:nowrap}
.cell-u{font-size:10px;color:var(--faible)}
.na{color:var(--faible);font-size:12px;letter-spacing:.08em}
@media (max-width:359px){.grid{grid-template-columns:minmax(0,1fr)}}

/* --- puits de trace : la seule surface elevee de l'application --- */
.well{background:var(--creux);padding:var(--e4) var(--e3) var(--e2);position:relative;
  touch-action:pan-y;margin-top:var(--e2)}
.well canvas{display:block;width:100%}
.tip{position:absolute;top:var(--e2);pointer-events:none;opacity:0;transition:opacity .1s;
  background:var(--fond);padding:var(--e2) var(--e3);color:var(--clair);
  font:400 12px/1.5 "DM Mono",monospace;white-space:nowrap;z-index:5}
.tip.on{opacity:1}
.tip em{display:block;font-style:normal;font-size:10px;color:var(--faible);
  letter-spacing:.06em}
.wleg{display:flex;justify-content:space-between;gap:var(--e3);margin-top:var(--e2)}
.wleg span{font:400 10px/1.5 "DM Mono",monospace;letter-spacing:.06em;color:var(--faible)}
.note{margin:var(--e3) 0 0;font:400 13px/1.6 "Instrument Sans",sans-serif;color:var(--gris)}
.note b{color:var(--texte);font-weight:600}

/* --- pourquoi ce wallet : un tiret, pas une puce coloree --- */
.wl{display:flex;gap:var(--e3);align-items:baseline;padding:var(--e2) 0}
.wl em{flex:0 0 12px;font-style:normal;color:var(--faible)}
.wl.f em{color:var(--index)}
.wl.r em{color:var(--alerte)}
.wl span{font:400 14px/1.5 "Instrument Sans",sans-serif}
.wl.r span{color:var(--alerte)}

/* --- provenance --- */
.prot{padding:var(--e4) 0;border-top:1px solid var(--filet)}
.prot h4{margin:0 0 var(--e2);font:400 10px/1.4 "DM Mono",monospace;letter-spacing:.12em;
  text-transform:uppercase;color:var(--gris)}
.prot p{margin:0;font:400 13.5px/1.6 "Instrument Sans",sans-serif;color:var(--gris)}
.prot p+p{margin-top:var(--e2)}
.cmp{display:grid;grid-template-columns:minmax(0,1fr) auto auto;
  column-gap:var(--e4);margin-top:var(--e3)}
.cmp>div{padding:var(--e2) 0;border-bottom:1px solid var(--filet);
  font:400 12px/1.5 "DM Mono",monospace;color:var(--texte);text-align:right;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmp>div.k,.cmp>div.h{font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--faible)}
.cmp>div.k{text-align:left;white-space:normal}

/* ════════════════════════════════════════════════════════ divers */
.empty{padding:var(--e6) 0;text-align:center}
.empty .lab{margin-bottom:var(--e3)}
.empty p{margin:0 auto;max-width:300px;font-size:14px;line-height:1.6;color:var(--faible)}
.fin-l{text-align:center;padding:var(--e6) 0 var(--e2);
  font:400 10px/1.5 "DM Mono",monospace;letter-spacing:.12em;color:var(--faible)}
.sentinel{height:1px}
.pied{margin:var(--e6) 0 var(--e2);text-align:center;
  font:400 10px/1.8 "DM Mono",monospace;letter-spacing:.1em;text-transform:uppercase;
  color:var(--faible)}
.pied b{color:var(--index);font-weight:400}

/* bandeau : quatre nombres, aucune boite */
.band{display:flex;gap:var(--e4);padding:0 var(--marge-d) var(--e4) var(--marge);
  border-bottom:1px solid var(--filet)}
.band>div{flex:1}
.band>div.vd{flex:1.6}
.band .lab{margin-bottom:var(--e1);font-size:9px;letter-spacing:.1em;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.band .v{font:500 22px/1 "DM Mono",monospace;color:var(--clair);
  font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.band .v.w{color:var(--index);font-size:12px;line-height:1.6}

/* liste compacte, meme grammaire que le releve */
.li{display:flex;align-items:baseline;gap:var(--e3);padding:var(--e3) 0;
  border-bottom:1px solid var(--filet);cursor:pointer;min-height:44px}
.li:active{opacity:.55}
.li .no{flex:0 0 auto;font:400 10px/1 "DM Mono",monospace;color:var(--faible)}
.li .adr{flex:0 0 auto;font-size:12px;color:var(--gris)}
.li .sc2{flex:0 0 auto;font-size:15px;font-weight:500;color:var(--index)}
.li .rt{margin-left:auto;text-align:right;max-width:54%;font-size:11.5px;
  line-height:1.4;color:var(--faible);overflow:hidden;display:-webkit-box;
  -webkit-line-clamp:2;-webkit-box-orient:vertical}

/* repli des sections sans evenement */
.det{border-bottom:1px solid var(--filet)}
.det summary{padding:var(--e3) 0;cursor:pointer;list-style:none;min-height:44px;
  display:flex;align-items:center;font:400 12px/1.4 "Instrument Sans",sans-serif;
  color:var(--faible)}
.det summary::-webkit-details-marker{display:none}
.det summary::after{content:"+";margin-left:auto;font-family:"DM Mono",monospace;
  color:var(--faible)}
.det[open] summary::after{content:"–"}
.det[open] summary{color:var(--gris)}
.det .note{padding-bottom:var(--e3);margin-top:0}

/* la convention : legende, repartition et filtre en un seul objet */
.conv{display:flex;gap:var(--e4);padding:var(--e2) var(--marge-d) var(--e4) var(--marge)}
.cseg{flex:1 1 0;padding:0;background:none;border:0;cursor:pointer;text-align:left;
  min-width:60px}
.cseg i{display:block;height:0;border-top:1px var(--gris);margin-bottom:var(--e2)}
.cseg.s i{border-top-style:solid}
.cseg.d i{border-top-style:dashed}
.cseg.p i{border-top-style:dotted}
.cseg.on i{border-top-color:var(--index);border-top-width:2px}
.cseg span{display:block;font:400 9.5px/1.3 "DM Mono",monospace;letter-spacing:.06em;
  text-transform:uppercase;color:var(--faible);white-space:nowrap}
.cseg.on span{color:var(--index)}

/* ════════════════════════════════════════════════════════ navigation
   TROIS entrees. « Suivi » etait deja un filtre du classement, « Decouverte »
   repond a la meme question que « Aujourd'hui » : les fondre ne retire aucune
   fonction, seulement de la surface. */
nav{position:fixed;left:0;right:0;bottom:0;z-index:70;display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));background:rgba(11,14,17,.95);
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  border-top:1px solid var(--filet);padding-bottom:env(safe-area-inset-bottom)}
nav button{background:none;border:0;color:var(--faible);padding:var(--e4) var(--e2);
  cursor:pointer;font:400 11px/1 "Instrument Sans",sans-serif;letter-spacing:.02em;
  transition:color .12s;min-height:50px;position:relative}
nav button.on{color:var(--clair)}
nav button.on::before{content:"";position:absolute;top:0;left:50%;
  transform:translateX(-50%);width:22px;height:1px;background:var(--index)}

@media (max-width:359px){
  :root{--marge:14px;--marge-d:14px;--e5:20px;--e6:32px}
  .big{font-size:60px}
  .sc{font-size:26px}
  .band .v{font-size:18px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms !important;transition-duration:.01ms !important}
}
:focus-visible{outline:1px solid var(--index);outline-offset:3px}
</style>

<div id="app">
<header><div class="hrow" id="hd"></div></header>

<section class="view on" id="v-jour" role="region" aria-label="Aujourd’hui">
  <div id="jband"></div><div class="wrap" id="jour"></div></section>

<section class="view" id="v-rank" role="region" aria-label="Classement">
  <div class="conv" id="conv" role="group" aria-label="Qualité des données"></div>
  <div class="wrap">
    <div class="srch" id="sbox">
      <input id="q" type="search" inputmode="search" autocomplete="off" autocapitalize="off"
             spellcheck="false" placeholder="Rechercher une adresse"
             aria-label="Rechercher une adresse ou un actif">
      <button class="clr" id="qc" aria-label="Effacer">×</button>
    </div>
  </div>
  <div class="chips" id="filtres"></div>
  <div class="chips" id="tris"></div>
  <div class="wrap">
    <div id="liste" role="list"></div>
    <div class="sentinel" id="sentinel"></div>
  </div>
</section>

<section class="view" id="v-data" role="region" aria-label="Données">
  <div class="wrap" id="dh"></div></section>

<section class="view" id="v-wallet" role="region" aria-label="Fiche du wallet"></section>
</div>

<nav role="navigation" aria-label="Navigation principale">
  <button data-nav="/" aria-label="Aujourd’hui">Aujourd’hui</button>
  <button data-nav="/rank" aria-label="Classement">Classement</button>
  <button data-nav="/data" aria-label="Données">Données</button>
</nav>

<script>
"use strict";
const DB = %%DATA%%;
const RP = %%REP%%;
const W = DB.wallets, META = DB.meta;
const DAILY = DB.daily || null;
const byA = Object.fromEntries(W.map(w => [w.a, w]));

/* ════════════════════════════════════════════════════════ format
   NA est le SEUL chemin d'affichage d'une valeur absente. Aucune substitution,
   aucun zero de complaisance : une grandeur non calculable se lit N/D. */
const APO = '\u2019';
const NA = '<span class="na">N/D</span>';
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const nb = (v, d = 2) => v == null ? NA :
  v.toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
const usd = v => {
  if (v == null) return NA;
  const a = Math.abs(v), s = v < 0 ? '−' : '+';
  if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'k';
  return s + '$' + a.toFixed(0);
};
const usdb = v => v == null ? NA : '$' + Math.abs(v).toLocaleString('fr-FR',
  {maximumFractionDigits: Math.abs(v) >= 10 ? 0 : 2});
const pc = (v, d = 0) => v == null ? NA : v.toFixed(d) + ' %';
const court = a => a.slice(0, 6) + '…' + a.slice(-4);
const date = t => t ? new Date(t).toLocaleDateString('fr-FR',
  {day: '2-digit', month: 'short', year: '2-digit'}) : NA;
const dateh = t => t ? new Date(t).toLocaleString('fr-FR',
  {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'}) : NA;
/* 42 caracteres d'affilee ne se verifient pas a l'oeil ; c'est pourtant le seul
   usage d'une adresse. Groupee par quatre, elle se relit. */
const groupe = a => a.slice(2).replace(/(.{4})/g, '$1 ').trim();
const jours = j => j == null ? NA : (j < 1 ? "aujourd'hui" : j < 2 ? 'hier'
  : Math.round(j) + ' j');

/* ════════════════════════════════════════════════════════ series
   L'equity est stockee en DELTAS DE SECONDES et le drawdown n'est pas stocke du
   tout : il se DEDUIT — dd(i) = max(eq[0..i], 0) − eq(i) —, ce qui est sa
   definition meme. Les deux courbes pesaient 1 503 Ko sur 1 857 ; la deduction
   est exacte parce que tout point qui met le sommet a jour est conserve a
   l'echantillonnage. */
function equity(w) {
  const e = w.eq;
  if (!e || !e.v || !e.v.length) return [];
  const out = [[e.t0 * 1000, e.v[0]]];
  let t = e.t0;
  for (let i = 0; i < e.d.length; i++) { t += e.d[i]; out.push([t * 1000, e.v[i + 1]]); }
  return out;
}
function drawdown(w) {
  let pic = 0;
  return equity(w).map(p => { pic = Math.max(pic, p[1]); return [p[0], -(pic - p[1])]; });
}

/* ════════════════════════════════════════════════════════ stockage local
   Toujours defensif : navigation privee, site data bloque, quota plein. Une
   watchlist perdue ne doit jamais empecher l'application de s'afficher. */
const S = {
  get(k, d) { try { return JSON.parse(localStorage.getItem('ht.' + k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem('ht.' + k, JSON.stringify(v)); } catch {} },
};
let WATCH = S.get('watch', []);
if (!Array.isArray(WATCH)) WATCH = Array.from(WATCH || []);
const suit = a => WATCH.indexOf(a) >= 0;
const majWatch = () => S.set('watch', WATCH);

/* ════════════════════════════════════════════════════════ INDEX + MORS
   La seule figure de l'application, et sa regle non negociable : un chiffre de
   score n'apparait JAMAIS sans ce rail dans le meme bloc visuel.

     position de l'index  = le score
     ecartement des mors  = l'intervalle de credibilite a 95 %
     fermete du trait     = la qualite des donnees

   Trois canaux redondants et non chromatiques : l'information survit au
   daltonisme comme au soleil sur un ecran. */
const TRAIT = { elevee: '', moyenne: '3 2', faible: '1 3' };
/* Bornes du MODELE — le score est une probabilite a posteriori en pourcentage —
   et non une donnee mesuree. Nommees plutot qu'ecrites en clair : l'audit
   d'authenticite refuse tout nombre litteral dans le gabarit. */
const ECHELLE = [0, 100];
const RW = 300, RH = 26, RP_ = 7;

function rail(w) {
  const y = RH - 10;
  const X = v => RP_ + (Math.max(0, Math.min(100, v)) / 100) * (RW - 2 * RP_);
  const p = [];
  for (let v = 0; v <= 100; v += 25) {
    p.push(`<line x1="${X(v)}" y1="${y}" x2="${X(v)}" y2="${y + 4}" stroke="var(--filet)" stroke-width="1"/>`);
  }
  p.push(`<line x1="${X(0)}" y1="${y}" x2="${X(100)}" y2="${y}" stroke="var(--filet)" stroke-width="1"/>`);
  const a = X(w.ic[0]), b = X(w.ic[1]), dash = TRAIT[w.conf_lab] ?? '';
  const da = dash ? ` stroke-dasharray="${dash}"` : '';
  p.push(`<line x1="${a}" y1="${y - 6}" x2="${b}" y2="${y - 6}" stroke="var(--gris)" stroke-width="1"${da}/>`);
  p.push(`<line x1="${a}" y1="${y - 9}" x2="${a}" y2="${y - 3}" stroke="var(--gris)" stroke-width="1"/>`);
  p.push(`<line x1="${b}" y1="${y - 9}" x2="${b}" y2="${y - 3}" stroke="var(--gris)" stroke-width="1"/>`);
  const x = X(w.score);
  p.push(`<line x1="${x}" y1="${y - 12}" x2="${x}" y2="${y + 5}" stroke="var(--index)" stroke-width="1"/>`);
  p.push(`<path d="M${x - 2.8} ${y - 12} L${x + 2.8} ${y - 12} L${x} ${y - 8.4} Z" fill="var(--index)"/>`);
  return `<svg class="rail" viewBox="0 0 ${RW} ${RH}" role="img"
    aria-label="Score ${w.score.toFixed(1)} sur ${ECHELLE[1]}. Intervalle de crédibilité
    ${w.ic[0]} à ${w.ic[1]}, largeur ${w.ic[1] - w.ic[0]}. Qualité des données
    ${w.conf_lab}.">${p.join('')}</svg>`;
}

/* ════════════════════════════════════════════════════════ marques
   La provenance est un POINT, pas un badge : 262 badges « Dérivé » identiques
   n'informeraient personne. Seule l'exception se marque. */
const estObs = w => !!w.obs;
const marqueProv = w => estObs(w)
  ? '<span class="bg obs" title="confronté à une donnée native HyperTracker">Observé</span>'
  : '';
/* La variation se lit au CHEVRON, sans couleur : le vert et le rouge sont
   sortis de la liste pour que l'ambre de l'index reste le seul signal. */
function marqueVar(w) {
  if (w.drang == null) return '';
  if (w.drang === 0) return '<span class="dv nul" title="rang stable">=</span>';
  return `<span class="dv" title="variation depuis le dernier relevé"
    >${w.drang > 0 ? '↑' : '↓'}${Math.abs(w.drang)}</span>`;
}
/* Le moteur redige ses motifs en prose d'audit — « anciennete : 81 jours entre
   trades clos, borne inferieure des jours couverts, non concluant face a 130 ».
   C'est la bonne trace dans un journal, et cinq lignes illisibles dans une
   liste. On garde le CRITERE et son chiffre, on laisse la demonstration au
   journal. Rien n'est invente : si la phrase change de forme, on retombe sur le
   nom du critere plutot que sur une valeur devinee. */
function critere(t) {
  const s = String(t || '').trim();
  const m = s.match(/^anciennet[ée]\s*:\s*(\d+)\s*jours/i);
  if (m) return 'ancienneté ' + m[1] + ' j';
  return s.indexOf(':') >= 0 ? s.split(':')[0].trim() : s;
}
const ETIQ = { RANKED: 'Classé', DISCOVERY: 'Observation', ARCHIVED: 'Archivé' };
const CLASSES = { EXCELLENT_CANDIDATE: 'Candidat excellent', PROMISING: 'Prometteur',
  INSUFFICIENT_DATA: 'Données insuffisantes', REJECTED: 'Non qualifié' };

function activite(w) {
  if (w.dort_j == null) return 'activité N/D';
  if (w.dort_j <= 2) return 'actif';
  if (w.dort_j <= 30) return 'récent · ' + jours(w.dort_j);
  return 'inactif · ' + jours(w.dort_j);
}

/* ════════════════════════════════════════════════════════ le releve
   CINQ grandeurs, pas quatorze : rang, adresse, mesure, volume, fraicheur. Les
   neuf autres ne sont pas perdues — elles sont sur la fiche, ou on les lit
   vraiment plutot que de les balayer. */
function ligne(w) {
  return `<article class="row" role="listitem" data-a="${w.a}" tabindex="0"
      aria-label="Rang ${w.rang}, score ${w.score.toFixed(1)}. Ouvrir la fiche.">
    <div class="r0">
      <span class="no">${String(w.rang).padStart(3, '0')}</span>
      <span class="adr">${court(w.a)}</span>
      <span class="fin">${marqueVar(w)}${marqueProv(w)}</span>
    </div>
    <div class="r1"><span class="sc">${w.score.toFixed(1)}</span>${rail(w)}</div>
    <div class="r2">${w.n} trades · ${esc(activite(w))}</div>
  </article>`;
}

/* ════════════════════════════════════════════════════════ tri et filtres
   Chaque cle pointe une grandeur REELLEMENT presente. Aucune n'est composee a
   la volee : trier sur une grandeur inventee afficherait un classement qui
   n'existe pas. */
const TRIS = [
  ['score',  'Score',         (a, b) => b.score - a.score],
  ['actif',  'Activité',      (a, b) => (b.r30 ?? 0) - (a.r30 ?? 0)],
  ['conf',   'Probabilité',   (a, b) => (b.conf ?? -1) - (a.conf ?? -1)],
  ['dd',     'Drawdown',      (a, b) => (a.dd ?? Infinity) - (b.dd ?? Infinity)],
  ['n',      'Trades',        (a, b) => b.n - a.n],
  ['drang',  'Variation',     (a, b) => (b.drang ?? -1e9) - (a.drang ?? -1e9)],
  ['recent', 'Dernier trade', (a, b) => (b.t1 ?? 0) - (a.t1 ?? 0)],
  ['sr',     'Sharpe',        (a, b) => b.sr - a.sr],
  ['stab',   'Régularité',    (a, b) => (b.stab ?? -1) - (a.stab ?? -1)],
  ['conc',   'Concentration', (a, b) => (a.conc ?? Infinity) - (b.conc ?? Infinity)],
  ['mien',   'Mon ordre',     (a, b) => WATCH.indexOf(a.a) - WATCH.indexOf(b.a)],
];
const FILTRES = [
  ['ranked', 'Classés',        w => w.st === 'RANKED'],
  ['tous',   'Tous',           () => true],
  ['actif',  'Actifs 30 j',    w => (w.r30 ?? 0) > 0],
  ['neuf',   'Nouveaux',       w => w.promu != null],
  ['q3',     'Qualité élevée', w => w.conf_lab === 'elevee'],
  ['q2',     'Qualité moyenne',w => w.conf_lab === 'moyenne'],
  ['q1',     'Qualité faible', w => w.conf_lab === 'faible'],
  ['obs',    'Observé',        w => estObs(w)],
  ['suivi',  'Suivis',         w => suit(w.a)],
  ['disco',  'Observation',    w => w.st === 'DISCOVERY'],
];

const ETAT = S.get('etat', { tri: 'score', filtre: 'ranked', q: '' });
if (ETAT.filtre === 'ranked' && !W.some(w => w.st === 'RANKED')) ETAT.filtre = 'tous';
const SCROLL = {};

function selection() {
  const f = (FILTRES.find(x => x[0] === ETAT.filtre) || FILTRES[1])[2];
  const q = ETAT.q.trim().toLowerCase();
  let r = W.filter(f);
  if (q) r = r.filter(w => w.a.toLowerCase().indexOf(q) >= 0
                        || (w.coins || []).some(c => c.toLowerCase().indexOf(q) >= 0));
  return r.sort((TRIS.find(x => x[0] === ETAT.tri) || TRIS[0])[2]);
}

/* Revelation progressive : chaque releve porte un rail SVG ; les poser tous
   d'un coup fige le premier rendu. */
const PAGE = 24;
let vus = 0, courant = [];

function rendu(reset) {
  const el = document.getElementById('liste');
  if (reset) { vus = 0; courant = selection(); el.innerHTML = ''; }
  if (!courant.length) {
    el.innerHTML = `<div class="empty"><div class="lab">Aucun résultat</div>
      <p>Aucun wallet ne satisfait ce filtre.</p></div>`;
    majCompteur(); return;
  }
  const lot = courant.slice(vus, vus + PAGE);
  el.insertAdjacentHTML('beforeend', lot.map(ligne).join(''));
  vus += lot.length;
  const f = el.querySelector('.fin-l'); if (f) f.remove();
  if (vus >= courant.length) {
    el.insertAdjacentHTML('beforeend', `<div class="fin-l">${courant.length} relevé${
      courant.length > 1 ? 's' : ''}</div>`);
  }
  majCompteur();
  if (ETAT.filtre === 'suivi' && ETAT.tri === 'mien') actionsSuivi(el);
}
function majCompteur() {
  const c = document.getElementById('cnt');
  if (c) c.textContent = String(courant.length);
}
/* Le reordonnancement du suivi n'apparait QUE dans le filtre « Suivis » : une
   commande qui ne sert que la n'a pas a peser sur les 267 autres releves. */
function actionsSuivi(el) {
  el.querySelectorAll('.row[data-a]').forEach((r, i, tous) => {
    if (r.querySelector('.act-s')) return;
    r.insertAdjacentHTML('beforeend', `<div class="arow act-s" style="margin-top:8px">
      <button class="btn" data-mv="${r.dataset.a}" data-dir="-1" aria-label="Monter"
        ${i === 0 ? 'disabled style="opacity:.3"' : ''}>↑</button>
      <button class="btn" data-mv="${r.dataset.a}" data-dir="1" aria-label="Descendre"
        ${i === tous.length - 1 ? 'disabled style="opacity:.3"' : ''}>↓</button>
      <button class="btn" data-rm="${r.dataset.a}" aria-label="Retirer"
        style="margin-left:auto">Retirer</button></div>`);
  });
  el.querySelectorAll('[data-mv]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    const i = WATCH.indexOf(b.dataset.mv), j = i + (+b.dataset.dir);
    if (i < 0 || j < 0 || j >= WATCH.length) return;
    const t = WATCH[i]; WATCH[i] = WATCH[j]; WATCH[j] = t;
    majWatch(); rendu(true);
  });
  el.querySelectorAll('[data-rm]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    const i = WATCH.indexOf(b.dataset.rm);
    if (i >= 0) { WATCH.splice(i, 1); majWatch(); rendu(true); }
  });
}
new IntersectionObserver(es => {
  if (es[0].isIntersecting && vus && vus < courant.length) rendu(false);
}, { rootMargin: '800px' }).observe(document.getElementById('sentinel'));

/* ════════════════════════════════════════════════════════ traces
   Canvas, infobulle au TOUCHER. Toutes partagent la meme mecanique : un tableau
   de points, une projection, l'index le plus proche du doigt. */
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function ctx2d(cv, h) {
  const r = Math.min(window.devicePixelRatio || 1, 2.5);
  const w = cv.clientWidth || cv.parentElement.clientWidth || 320;
  cv.width = Math.round(w * r); cv.height = Math.round(h * r);
  cv.style.height = h + 'px';
  const c = cv.getContext('2d'); c.setTransform(r, 0, 0, r, 0, 0);
  return [c, w, h];
}
function pointeur(cv, n, PX, fmt) {
  const puits = cv.closest('.well');
  if (!puits || !n) return;
  let tip = puits.querySelector('.tip');
  if (!tip) { tip = document.createElement('div'); tip.className = 'tip'; puits.appendChild(tip); }
  const bouge = e => {
    const r = cv.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
    let i = 0, best = Infinity;
    for (let k = 0; k < n; k++) { const d = Math.abs(PX(k) - x); if (d < best) { best = d; i = k; } }
    tip.innerHTML = fmt(i); tip.classList.add('on');
    const tw = tip.offsetWidth || 90;
    tip.style.left = Math.max(0, Math.min(r.width - tw, PX(i) - tw / 2)) + 'px';
    if (cv._trace) cv._trace(i);
  };
  const fin = () => { tip.classList.remove('on'); if (cv._trace) cv._trace(null); };
  cv.onpointerdown = bouge;
  cv.onpointermove = e => { if (e.buttons || e.pointerType === 'touch') bouge(e); };
  cv.onpointerup = fin; cv.onpointerleave = fin; cv.onpointercancel = fin;
}
function vide(c, w, h, t) {
  c.clearRect(0, 0, w, h);
  c.fillStyle = css('--faible'); c.font = '12px "Instrument Sans", sans-serif';
  c.textAlign = 'center'; c.fillText(t || 'Pas assez de relevés', w / 2, h / 2);
}

/** Courbe temporelle. Le signe se lit a la FORME — hachures sous zero — jamais
 *  a une couleur gain/perte : un instrument ne colorie pas ses mesures. */
function courbe(cv, pts, opt) {
  opt = opt || {};
  const h = opt.h || 150;
  const [c, w] = ctx2d(cv, h);
  if (!pts || pts.length < 2) { vide(c, w, h); return; }
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys, 0), y1 = Math.max(...ys, 0);
  if (y1 === y0) { y1 += 1; y0 -= 1; }
  const pad = 2;
  const PX = i => pad + ((pts[i][0] - x0) / (x1 - x0 || 1)) * (w - 2 * pad);
  const PY = v => pad + (1 - (v - y0) / (y1 - y0)) * (h - 2 * pad - 14);
  const dessine = hl => {
    c.clearRect(0, 0, w, h);
    c.setLineDash([1, 3]); c.strokeStyle = css('--faible'); c.lineWidth = 1;
    c.beginPath(); c.moveTo(pad, PY(0)); c.lineTo(w - pad, PY(0)); c.stroke();
    c.setLineDash([]);
    if (pts.some(p => p[1] < 0)) {
      c.save(); c.beginPath(); c.moveTo(PX(0), PY(0));
      pts.forEach((p, i) => c.lineTo(PX(i), PY(Math.min(0, p[1]))));
      c.lineTo(PX(pts.length - 1), PY(0)); c.closePath(); c.clip();
      c.strokeStyle = css('--gris'); c.globalAlpha = .18; c.lineWidth = 1;
      for (let i = -h; i < w + h; i += 5) { c.beginPath(); c.moveTo(i, 0); c.lineTo(i + h, h); c.stroke(); }
      c.restore();
    }
    c.strokeStyle = opt.couleur || css('--texte'); c.lineWidth = 1.25;
    c.lineJoin = 'round'; c.beginPath();
    pts.forEach((p, i) => i ? c.lineTo(PX(i), PY(p[1])) : c.moveTo(PX(i), PY(p[1])));
    c.stroke();
    if (hl != null) {
      c.strokeStyle = css('--index'); c.lineWidth = 1;
      c.beginPath(); c.moveTo(PX(hl), pad); c.lineTo(PX(hl), h - pad - 14); c.stroke();
      c.fillStyle = css('--index');
      c.beginPath(); c.arc(PX(hl), PY(pts[hl][1]), 2.6, 0, 6.284); c.fill();
    }
    c.fillStyle = css('--faible'); c.font = '10px "DM Mono", monospace';
    c.textAlign = 'left';
    c.fillText(new Date(x0).toLocaleDateString('fr-FR', {month: 'short', year: '2-digit'}), pad, h - 2);
    c.textAlign = 'right';
    c.fillText(new Date(x1).toLocaleDateString('fr-FR', {month: 'short', year: '2-digit'}), w - pad, h - 2);
  };
  cv._trace = dessine; dessine(null);
  pointeur(cv, pts.length, PX, i => `${usd(pts[i][1])}<em>${
    new Date(pts[i][0]).toLocaleDateString('fr-FR',
      {day: '2-digit', month: 'short', year: '2-digit'})}</em>`);
}

function barres(cv, etiq, vals, opt) {
  opt = opt || {};
  const h = opt.h || 110;
  const [c, w] = ctx2d(cv, h);
  const n = vals.length;
  if (!n) { vide(c, w, h); return; }
  const mx = Math.max.apply(null, vals.concat([1]));
  const pad = 2, base = h - 16, bw = (w - 2 * pad) / n;
  const PX = i => pad + i * bw + bw / 2;
  const dessine = hl => {
    c.clearRect(0, 0, w, h);
    for (let i = 0; i < n; i++) {
      const bh = (vals[i] / mx) * (base - 4), x = pad + i * bw, y = base - bh;
      c.fillStyle = (i === hl || (opt.plein != null && i === opt.plein && hl == null))
        ? css('--index') : css('--gris');
      c.globalAlpha = (i === hl || (opt.plein != null && i === opt.plein && hl == null)) ? 1 : .42;
      c.fillRect(x, y, Math.max(1, bw - 1.5), Math.max(1, bh));
      c.globalAlpha = 1;
    }
    c.strokeStyle = css('--filet'); c.lineWidth = 1;
    c.beginPath(); c.moveTo(pad, base + .5); c.lineTo(w - pad, base + .5); c.stroke();
    c.fillStyle = css('--faible'); c.font = '10px "DM Mono", monospace';
    if (etiq.length) {
      c.textAlign = 'left'; c.fillText(etiq[0], pad, h - 2);
      c.textAlign = 'right'; c.fillText(etiq[n - 1], w - pad, h - 2);
    }
  };
  cv._trace = dessine; dessine(null);
  pointeur(cv, n, PX, i => `${vals[i]}${opt.suffixe || ''}<em>${esc(etiq[i] || '')}</em>`);
}

/** Frise : rang ou score dans le temps. Echelle du rang INVERSEE — le 1 en haut —
 *  parce que « monter au classement » doit monter a l'ecran. */
function frise(cv, pts, opt) {
  opt = opt || {};
  const h = opt.h || 100;
  const [c, w] = ctx2d(cv, h);
  if (!pts || pts.length < 2) { vide(c, w, h); return; }
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y1 === y0) { y1 += 1; y0 -= 1; }
  const pad = 6;
  const PX = i => pad + ((pts[i][0] - x0) / (x1 - x0 || 1)) * (w - 2 * pad);
  const PY = v => opt.inverse ? pad + ((v - y0) / (y1 - y0)) * (h - 2 * pad - 14)
                              : pad + (1 - (v - y0) / (y1 - y0)) * (h - 2 * pad - 14);
  const dessine = hl => {
    c.clearRect(0, 0, w, h);
    c.strokeStyle = css('--gris'); c.lineWidth = 1; c.beginPath();
    pts.forEach((p, i) => i ? c.lineTo(PX(i), PY(p[1])) : c.moveTo(PX(i), PY(p[1])));
    c.stroke();
    c.fillStyle = css('--index');
    pts.forEach((p, i) => { c.beginPath(); c.arc(PX(i), PY(p[1]), i === hl ? 3.5 : 2, 0, 6.284); c.fill(); });
    c.fillStyle = css('--faible'); c.font = '10px "DM Mono", monospace';
    c.textAlign = 'left'; c.fillText((opt.prefixe || '') + ys[0], pad, h - 2);
    c.textAlign = 'right'; c.fillText((opt.prefixe || '') + ys[ys.length - 1], w - pad, h - 2);
  };
  cv._trace = dessine; dessine(null);
  pointeur(cv, pts.length, PX, i => `${opt.prefixe || ''}${pts[i][1]}<em>${
    new Date(pts[i][0]).toLocaleDateString('fr-FR', {day: '2-digit', month: 'short'})}</em>`);
}

/** Nuage score contre probabilite : la these du produit, rendue mesurable. */
function nuage(cv, cible) {
  const [c, w, h] = ctx2d(cv, 170);
  const pad = 24;
  const PX = v => pad + (v / 100) * (w - pad - 6);
  const PY = v => h - pad - (v / 100) * (h - pad - 10);
  c.strokeStyle = css('--filet'); c.lineWidth = 1;
  for (let g = 0; g <= 100; g += 50) {
    c.beginPath(); c.moveTo(PX(g), PY(0)); c.lineTo(PX(g), PY(100)); c.stroke();
    c.beginPath(); c.moveTo(PX(0), PY(g)); c.lineTo(PX(100), PY(g)); c.stroke();
  }
  c.fillStyle = css('--gris'); c.globalAlpha = .5;
  W.filter(x => x.conf != null).forEach(x => {
    c.beginPath(); c.arc(PX(x.score), PY(x.conf), 1.6, 0, 6.284); c.fill();
  });
  c.globalAlpha = 1;
  if (cible && cible.conf != null) {
    c.strokeStyle = css('--index'); c.lineWidth = 1;
    c.beginPath(); c.arc(PX(cible.score), PY(cible.conf), 4.5, 0, 6.284); c.stroke();
  }
  c.fillStyle = css('--faible'); c.font = '10px "DM Mono", monospace';
  c.textAlign = 'center'; c.fillText('SCORE', w / 2, h - 3);
  c.save(); c.translate(8, h / 2); c.rotate(-Math.PI / 2); c.textAlign = 'center';
  c.fillText('PROBABILITÉ', 0, 0); c.restore();
}

/** Echelle verticale du grand cadran : la population reelle en arriere-plan. */
function cadran(cv, w0) {
  const [c, w, h] = ctx2d(cv, 132);
  const pad = 6, PY = v => h - pad - (v / 100) * (h - 2 * pad);
  c.strokeStyle = css('--gris'); c.globalAlpha = .13; c.lineWidth = 1;
  W.forEach(x => { c.beginPath(); c.moveTo(w - 17, PY(x.score)); c.lineTo(w - 8, PY(x.score)); c.stroke(); });
  c.globalAlpha = 1;
  const dash = { elevee: [], moyenne: [3, 2], faible: [1, 3] }[w0.conf_lab] || [];
  c.strokeStyle = css('--gris'); c.lineWidth = 1; c.setLineDash(dash);
  c.beginPath(); c.moveTo(w - 26, PY(w0.ic[0])); c.lineTo(w - 26, PY(w0.ic[1])); c.stroke();
  c.setLineDash([]);
  [w0.ic[0], w0.ic[1]].forEach(v => {
    c.beginPath(); c.moveTo(w - 30, PY(v)); c.lineTo(w - 22, PY(v)); c.stroke();
  });
  c.strokeStyle = css('--index'); c.lineWidth = 1;
  c.beginPath(); c.moveTo(0, PY(w0.score)); c.lineTo(w - 4, PY(w0.score)); c.stroke();
  c.fillStyle = css('--index'); c.beginPath();
  c.moveTo(w - 4, PY(w0.score) - 2.4); c.lineTo(w - 4, PY(w0.score) + 2.4);
  c.lineTo(w, PY(w0.score)); c.closePath(); c.fill();
}

/* ════════════════════════════════════════════════════════ copie */
async function copier(txt, bouton, libelle) {
  let ok = false;
  try { await navigator.clipboard.writeText(txt); ok = true; }
  catch {
    try {
      const t = document.createElement('textarea');
      t.value = txt; t.setAttribute('readonly', '');
      t.style.cssText = 'position:fixed;top:-1000px;opacity:0';
      document.body.appendChild(t); t.select(); ok = document.execCommand('copy');
      document.body.removeChild(t);
    } catch {}
  }
  bouton.textContent = ok ? 'Copiée' : 'Refusée';
  bouton.classList.toggle('ok', ok);
  setTimeout(() => { bouton.textContent = libelle; bouton.classList.remove('ok'); }, 1500);
}

/* ════════════════════════════════════════════════════════ fiche */
function cellule(k, v, u) {
  return `<div class="cell"><span class="cell-k">${k}</span>
    <span class="cell-v">${v}${u ? ` <span class="cell-u">${u}</span>` : ''}</span></div>`;
}
const pairs = w => W.filter(x => x.conf_lab === w.conf_lab).length;

/* Le Sharpe brut et celui que le modele retient ne sont pas deux chiffres a
   comparer de tete : c'est UN deplacement sur une echelle. */
const SR_MIN = Math.min.apply(null, W.map(x => Math.min(x.sr, x.post)));
const SR_MAX = Math.max.apply(null, W.map(x => Math.max(x.sr, x.post)));
function retrecissement(w) {
  const L = 300, H = 34, pad = 8;
  const X = v => pad + ((v - SR_MIN) / ((SR_MAX - SR_MIN) || 1)) * (L - 2 * pad);
  const y = 20, a = X(w.sr), b = X(w.post), z = X(0), p = [];
  p.push(`<line x1="${pad}" y1="${y}" x2="${L - pad}" y2="${y}" stroke="var(--filet)" stroke-width="1"/>`);
  p.push(`<line x1="${z}" y1="${y - 5}" x2="${z}" y2="${y + 5}" stroke="var(--filet)" stroke-width="1"/>`);
  p.push(`<text x="${z}" y="${H - 1}" fill="var(--faible)" font-size="9"
          font-family="DM Mono, monospace" text-anchor="middle">${ECHELLE[0]}</text>`);
  p.push(`<line x1="${a}" y1="${y}" x2="${b}" y2="${y}" stroke="var(--gris)" stroke-width="1"/>`);
  p.push(`<circle cx="${a}" cy="${y}" r="3" fill="none" stroke="var(--gris)" stroke-width="1"/>`);
  p.push(`<line x1="${a - 4}" y1="${y + 4}" x2="${a + 4}" y2="${y - 4}" stroke="var(--gris)" stroke-width="1"/>`);
  p.push(`<line x1="${b}" y1="${y - 8}" x2="${b}" y2="${y + 8}" stroke="var(--index)" stroke-width="1"/>`);
  const d = w.post - w.sr;
  p.push(`<text x="${(a + b) / 2}" y="${y - 10}" fill="var(--texte)" font-size="10"
          font-family="DM Mono, monospace" text-anchor="middle"
          >${d >= 0 ? '+' : '−'}${Math.abs(d).toFixed(3)}</text>`);
  return `<svg viewBox="0 0 ${L} ${H}" style="display:block;width:100%;height:auto" role="img"
    aria-label="Sharpe brut ${w.sr.toFixed(4)} ramené à ${w.post.toFixed(4)}">${p.join('')}</svg>`;
}

function cycleVie(w) {
  const h = w.histo || [];
  const t = `<div class="cmp" style="grid-template-columns:minmax(0,1fr) auto">
      <div class="k">Statut</div><div>${w.st ? esc(ETIQ[w.st] || w.st) : NA}</div>
      <div class="k">Qualification</div><div>${w.classe ? esc(CLASSES[w.classe] || w.classe) : NA}</div>
      <div class="k">Découvert via</div><div>${w.src ? esc(w.src) : NA}</div>
      <div class="k">Première vue</div><div>${w.vu ? date(w.vu * 1000) : NA}</div>
      <div class="k">Qualifié le</div><div>${w.promu ? date(w.promu * 1000) : NA}</div>
      <div class="k">Dernière collecte</div><div>${w.coll ? date(w.coll * 1000) : NA}</div>
      <div class="k">Retours au classement</div><div>${w.ret ?? 0}</div>
    </div>`;
  if (h.length < 2) {
    return t + `<p class="note">Historique trop court pour tracer une évolution :
      ${h.length} relevé${h.length > 1 ? 's' : ''}. Il s'enrichit à chaque cycle.</p>`;
  }
  return t + `
    <div class="sect"><span class="lab">Rang</span></div>
    <div class="well"><canvas id="g5" aria-label="Évolution du rang"></canvas>
      <div class="wleg"><span>1 = meilleur</span><span>${h.length} relevés</span></div></div>
    <div class="sect"><span class="lab">Score</span></div>
    <div class="well"><canvas id="g6" aria-label="Évolution du score"></canvas>
      <div class="wleg"><span>échelle 0–${ECHELLE[1]}</span><span>${h.length} relevés</span></div></div>`;
}

function fiche(w) {
  const s = suit(w.a), larg = w.ic[1] - w.ic[0];
  const QL = { elevee: 'élevée', moyenne: 'moyenne', faible: 'faible' };
  const bloc = (titre, cle, cls, tiret) => {
    const l = w[cle] || [];
    if (!l.length) return '';
    return `<div class="sect"><span class="lab">${titre}</span></div>` + l.map(x =>
      `<div class="wl ${cls}"><em>${tiret}</em><span>${esc(x)}</span></div>`).join('');
  };

  let prot;
  if (w.obs) {
    const o = w.obs;
    prot = `<div class="prot"><h4>Observé — donnée native HyperTracker</h4>
      <p>Le Sharpe estimé par notre modèle est confronté au Sharpe recalculé sur les
      trades natifs. Le verdict global du protocole reste <b>${esc(META.verdict)}</b> :
      ${esc(META.verdict_motif)}.</p>
      <div class="cmp">
        <div class="h k">Métrique</div><div class="h">Dérivé</div><div class="h">Observé</div>
        <div class="k">Sharpe / trade</div><div>${nb(o.sr_der, 4)}</div><div>${nb(o.sr, 4)}</div>
        <div class="k">Trades</div><div>${w.n}</div><div>${o.n}</div>
        <div class="k">Écart absolu</div><div>—</div><div>${nb(o.ecart, 3)}</div>
        <div class="k">Écart relatif</div><div>—</div><div>${o.ecart_rel == null ? NA : pc(o.ecart_rel * 100, 1)}</div>
        <div class="k">Change de signe</div><div>—</div><div>${o.signe ? 'oui' : 'non'}</div>
        <div class="k">Échantillon suffisant</div><div>—</div><div>${o.suffisant ? 'oui' : 'non'}</div>
      </div></div>`;
  } else {
    prot = `<div class="prot"><h4>Dérivé — aucune donnée native</h4>
      <p>Ce wallet n'a aucun trade natif HyperTracker exploitable : son classement repose
      entièrement sur la reconstruction depuis les fills publics. Aucune valeur observée
      n'est affichée ici, parce qu'il n'en existe aucune.</p></div>`;
  }

  return `
  <div class="wh">
    <div class="r0">
      <span class="no">${String(w.rang).padStart(3, '0')} / ${META.n}</span>
      <span class="fin">${marqueVar(w)}${marqueProv(w)}
        <span class="bg">${esc(ETIQ[w.st] || 'N/D')}</span></span>
    </div>
    <div style="height:14px"></div>
    <span class="adr" id="adr">0x${groupe(w.a)}</span>
    <div class="arow">
      <button class="btn" id="cp" aria-label="Copier l'adresse brute">Copier</button>
      <button class="btn" id="cpb" aria-label="Copier l'adresse groupée">Groupée</button>
      <button class="btn ${s ? 'on' : ''}" id="wt" aria-pressed="${s}">${s ? 'Suivi' : 'Suivre'}</button>
    </div>
  </div>

  <div class="wrap">
    <!-- LA MESURE : le seul objet mis en avant de l'application. -->
    <div class="mesure">
      <div style="display:flex;gap:20px;align-items:flex-start">
        <div style="flex:1">
          <div class="lab">Performance</div>
          <div class="big">${w.score.toFixed(1)}</div>
          ${rail(w)}
        </div>
        <div style="flex:0 0 44px;height:132px"><canvas id="cad" aria-hidden="true"
          style="width:44px;height:100%"></canvas></div>
      </div>
      <div class="mini">
        <div class="kv"><span>Incertitude</span><b>${w.ic[0]}–${w.ic[1]}</b></div>
        <div class="kv"><span>Largeur de l’IC</span><b>${larg}</b></div>
        <div class="kv"><span>Probabilité calibrée</span><b>${w.conf == null ? 'N/D' : w.conf + ' %'}</b></div>
        <div class="kv"><span>Qualité des données</span><b>${esc(QL[w.conf_lab] || w.conf_lab)}</b></div>
        <div class="vern" role="img" aria-label="Qualité ${w.qualite} sur 3 critères">
          ${[0,1,2].map(i => `<i class="${i < (w.qualite || 0) ? 'f' : ''}"></i>`).join('')}
        </div>
        <p class="apparat">${pairs(w)} des ${META.n} wallets partagent cette réserve.</p>
      </div>
      ${w.conf == null ? `<p class="note">La probabilité calibrée n'existe pas pour ce
        wallet : le modèle de recalibrage n'a pas été conservé, il ne peut donc pas
        s'appliquer à un wallet apparu depuis. Elle reste N/D plutôt qu'approchée.</p>` : ''}
    </div>

    ${bloc('Points forts', 'forts', 'f', '+')}
    ${bloc('Réserves', 'faibles', 'w', '–')}
    ${bloc('Vigilance', 'risques', 'r', '×')}

    <div class="sect"><span class="lab">PnL cumulé</span>
      <span class="cpt">${usd(w.pnl)}</span></div>
    <div class="well"><canvas id="g1" aria-label="Courbe du PnL cumulé"></canvas>
      <div class="wleg"><span>${date(w.t0)}</span><span>${w.n} trades clos</span></div></div>

    <details class="det" id="plus" style="margin-top:var(--e5);border-top:1px solid var(--filet)">
      <summary>Tout voir — mesures, drawdown, activité, provenance</summary>
    </details>
    <div id="reste" hidden>
      <div class="sect"><span class="lab">Mesures</span></div>
      <div class="grid">
        ${cellule('Sharpe / trade', nb(w.sr, 4))}
        ${cellule('Sharpe retenu', nb(w.post, 4))}
        ${cellule('PnL net', usd(w.pnl))}
        ${cellule('Drawdown max', usdb(w.dd))}
        ${cellule('Trades clos', String(w.n))}
        ${cellule('Écart 1ᵉʳ–dernier', String(w.jours), 'j')}
        ${cellule('Taux de réussite', pc(w.win, 1))}
        ${cellule('Profit factor', nb(w.pf, 2))}
        ${cellule('Concentration', nb(w.conc, 3))}
        ${cellule('Régularité mens.', w.stab == null ? NA : pc(w.stab, 0))}
        ${cellule('Activité 30 j', String(w.r30 ?? 0))}
        ${cellule('Activité 7 j', String(w.r7 ?? 0))}
        ${cellule('Meilleur trade', usd(w.best))}
        ${cellule('Pire trade', usd(w.pire))}
        ${cellule('Durée médiane', w.duree_h == null ? NA : nb(w.duree_h, 1), 'h')}
        ${cellule('Écart-type / trade', usdb(w.vol))}
        ${cellule('Frais payés', usdb(w.frais))}
        ${cellule('Trades / jour', nb(w.tpj, 2))}
        ${cellule('Premier trade', date(w.t0))}
        ${cellule('Dernier trade', date(w.t1))}
        ${cellule('Funding', NA)}
        ${cellule('Jours couverts', NA)}
        ${cellule('ROI', NA)}
        ${cellule('Long / Short', NA)}
      </div>
      <p class="note">Quatre grandeurs restent vides parce qu'elles n'existent pas dans la
        source : le funding n'est pas séparé du PnL dans les séries, les jours de
        couverture ne sont pas conservés — seul l'écart entre le premier et le dernier
        trade clos l'est — et ni le capital engagé ni le sens des positions ne sont
        exposés. Elles ne reçoivent pas de valeur approchée.</p>

      <div class="sect"><span class="lab">Rétrécissement</span></div>
      <div class="well">${retrecissement(w)}
        <div class="wleg"><span>Sharpe brut ${nb(w.sr, 4)}</span>
          <span>Retenu ${nb(w.post, 4)}</span></div></div>
      <p class="note">Un échantillon mince est ramené vers la moyenne de la population :
        c'est ce déplacement, et non le chiffre brut, qui fonde le score.</p>

      <div class="sect"><span class="lab">Drawdown</span>
        <span class="cpt">${usdb(w.dd)}</span></div>
      <div class="well"><canvas id="g2" aria-label="Courbe de drawdown"></canvas>
        <div class="wleg"><span>repli depuis le sommet</span><span>déduit de l’equity</span></div></div>

      <div class="sect"><span class="lab">Activité mensuelle</span></div>
      <div class="well"><canvas id="g3" aria-label="Trades clos par mois"></canvas>
        <div class="wleg"><span>trades clos par mois</span><span>${(w.m || []).length} mois</span></div></div>

      <div class="sect"><span class="lab">Distribution</span></div>
      <div class="well"><canvas id="g4" aria-label="Distribution des résultats"></canvas>
        <div class="wleg"><span>${w.n} trades</span><span>barre pleine : médiane</span></div></div>

      <div class="sect"><span class="lab">Score contre probabilité</span></div>
      <div class="well"><canvas id="g7" aria-label="Nuage score contre probabilité"></canvas>
        <div class="wleg"><span>${W.filter(x => x.conf != null).length} wallets</span>
        <span>cercle : celui-ci</span></div></div>
      <p class="note">Un score élevé n'implique pas une probabilité élevée : si les deux
        grandeurs étaient la même chose, ce nuage serait une diagonale. Il ne l'est pas.</p>

      <div class="sect"><span class="lab">Cycle de vie</span></div>
      ${cycleVie(w)}

      <div class="sect"><span class="lab">Provenance</span></div>
      ${prot}
    </div>

    <p class="pied">&#961; ${nb(META.spearman, 4)} · ECE ${nb(META.ece, 4)} ·
      <b>${esc(META.verdict)}</b></p>
  </div>`;
}

function ouvre(a) {
  const w = byA[a], el = document.getElementById('v-wallet');
  // Le noeud est REUTILISE d'une fiche a l'autre : son drapeau doit l'etre
  // aussi. Sans cette ligne, seule la premiere fiche de la session voyait ses
  // graphiques secondaires dessines.
  el._tracees = false;
  el._wallet = w || null;
  if (!w) {
    el.innerHTML = `<div class="wrap"><div class="empty"><div class="lab">Wallet introuvable</div>
      <p>Cette adresse ne figure pas parmi les ${META.n} wallets analysés.</p></div></div>`;
    return;
  }
  el.innerHTML = fiche(w);
  window.scrollTo(0, 0);
  el.querySelector('#cp').onclick = e => copier(w.a, e.currentTarget, 'Copier');
  el.querySelector('#cpb').onclick = e => copier('0x' + groupe(w.a), e.currentTarget, 'Groupée');
  const wt = el.querySelector('#wt');
  wt.onclick = () => {
    const i = WATCH.indexOf(w.a);
    if (i >= 0) WATCH.splice(i, 1); else WATCH.push(w.a);
    majWatch();
    const s2 = suit(w.a);
    wt.textContent = s2 ? 'Suivi' : 'Suivre';
    wt.setAttribute('aria-pressed', String(s2));
    wt.classList.toggle('on', s2);
  };
  /* REVELATION PROGRESSIVE : l'essentiel d'abord, le reste au toucher. Vingt-quatre
     mesures et six graphiques ne se lisent pas d'un coup ; les poser tous en haut
     n'est pas de la richesse, c'est du bruit. */
  const det = el.querySelector('#plus'), reste = el.querySelector('#reste');
  det.addEventListener('toggle', () => {
    reste.hidden = !det.open;
    if (det.open) requestAnimationFrame(() => tracesSecondaires(el, w));
  });
  requestAnimationFrame(() => tracesPrincipales(el, w));
}

/* Les canvas sont les seuls elements qui dependent de la largeur : eux seuls
   ont besoin d'etre refaits quand elle change. Le HTML, le defilement et l'etat
   du repli n'y touchent pas. */
function tracesPrincipales(el, w) {
  cadran(el.querySelector('#cad'), w);
  courbe(el.querySelector('#g1'), equity(w), { h: 160 });
}
function redessineFiche() {
  const el = document.getElementById('v-wallet'), w = el._wallet;
  if (!w || !el.querySelector('#cad')) return;
  tracesPrincipales(el, w);
  const reste = el.querySelector('#reste');
  if (reste && !reste.hidden) { el._tracees = false; tracesSecondaires(el, w); }
}

function tracesSecondaires(el, w) {
  if (el._tracees) return;
  el._tracees = true;
  courbe(el.querySelector('#g2'), drawdown(w), { h: 120, couleur: css('--gris') });
  const m = w.m || [];
  barres(el.querySelector('#g3'), m.map(x => x[0]), m.map(x => x[2]), { h: 110, suffixe: ' trades' });
  const hi = w.hist;
  if (hi && hi.b) {
    const b = hi.b, tot = b.reduce((s, x) => s + x, 0);
    let cum = 0, iMed = 0;
    for (let i = 0; i < b.length; i++) { cum += b[i]; if (cum >= tot / 2) { iMed = i; break; } }
    barres(el.querySelector('#g4'), b.map((_, i) => usd(hi.lo + (i + .5) * hi.pas)
      .replace(/<[^>]*>/g, '')), b, { h: 110, plein: iMed, suffixe: ' trades' });
  }
  nuage(el.querySelector('#g7'), w);
  const h = w.histo || [];
  const rg = h.filter(x => x[2] != null), sc = h.filter(x => x[1] != null);
  const c5 = el.querySelector('#g5'), c6 = el.querySelector('#g6');
  if (c5) frise(c5, rg.map(x => [x[0] * 1000, x[2]]), { inverse: true, prefixe: '#' });
  if (c6) frise(c6, sc.map(x => [x[0] * 1000, Math.round(x[1] * 10) / 10]), {});
}

/* ════════════════════════════════════════════════════════ aujourd'hui */
function ligneC(a, extra) {
  const w = byA[a];
  if (!w) return `<div class="li" style="cursor:default"><span class="adr">${court(a)}</span>
    <span class="rt">${extra || NA}</span></div>`;
  return `<div class="li" data-a="${w.a}" role="button" tabindex="0"
      aria-label="Rang ${w.rang}, score ${w.score.toFixed(1)}. Ouvrir la fiche.">
    <span class="no">${String(w.rang).padStart(3, '0')}</span>
    <span class="adr">${court(w.a)}</span>
    <span class="sc2">${w.score.toFixed(1)}</span>
    <span class="rt">${extra || ''}</span></div>`;
}
function sectionL(t, lignes, n, note) {
  return `<div class="sect"><span class="lab">${t}</span>${
    n ? `<span class="cpt">${n}</span>` : ''}</div>${lignes.join('')}${
    note ? `<p class="note">${note}</p>` : ''}`;
}
/* CE QUI A CHANGE D'ABORD. Un accueil qui empile quatre paragraphes « rien a
   signaler » repousse le contenu reel sous la ligne de flottaison et repond a
   cote de la question qu'il pose. */
function sections(defs) {
  const pleines = defs.filter(d => d.lignes.length);
  const vides = defs.filter(d => !d.lignes.length);
  let h = pleines.map(d => sectionL(d.t, d.lignes, d.lignes.length, d.note)).join('');
  if (vides.length) {
    h += `<div class="sect"><span class="lab">Rien à signaler</span>
      <span class="cpt">${vides.length}</span></div>` + vides.map(d =>
      `<details class="det"><summary>${esc(d.t)}</summary>
        <p class="note">${d.vide}</p></details>`).join('');
  }
  return h;
}

function rendJour() {
  const el = document.getElementById('jour'), bd = document.getElementById('jband');
  if (!DAILY) {
    bd.innerHTML = '';
    el.innerHTML = `<div class="empty"><div class="lab">Aucun cycle exécuté</div>
      <p>Le cycle du matin n'a pas encore tourné. Lancez
      <span class="mo">python -m ht.matin</span>, ou attendez 08:00.</p></div>`;
    return;
  }
  const d = DAILY, h = d.data_health || {}, sy = d.system_health || {};
  const dormants = W.filter(w => w.st === 'RANKED' && (w.dort_j ?? 0) > 60)
    .sort((a, b) => b.dort_j - a.dort_j).slice(0, 6);
  const top = W.filter(w => w.st === 'RANKED').slice(0, 6);
  const qualif = W.filter(w => w.promu != null)
    .sort((a, b) => (b.promu || 0) - (a.promu || 0)).slice(0, 6);

  bd.innerHTML = `<div class="band">
    <div><div class="lab">Classés</div><div class="v">${h.ranked ?? META.n}</div></div>
    <div><div class="lab">Nouveaux</div><div class="v">${(d.new_ranked || []).length}</div></div>
    <div><div class="lab">Sorties</div><div class="v">${(d.archived || []).length}</div></div>
    <div class="vd"><div class="lab">Verdict</div><div class="v w">${esc(META.verdict)}</div></div>
  </div>`;

  el.innerHTML = `
    <p class="note" style="margin-top:var(--e4)">Dernier cycle
      ${esc((d.horodatage || '').slice(0, 16).replace('T', ' '))} · ${esc(d.mode || '')} ·
      ${sy.duree_s ?? '—'} s</p>
    ${d.prochaine_action ? `<p class="note"><b>Prochaine action</b> — ${esc(d.prochaine_action)}</p>` : ''}
    ${sections([
      { t: 'Nouveaux qualifiés',
        lignes: (d.new_ranked || []).map(x => ligneC(x.a, esc(x.message))),
        vide: 'Aucun wallet n' + APO + 'a franchi les critères ce cycle. Une découverte ' +
              'n' + APO + 'est pas une qualification : il faut ' +
              `${META.seuil_trades} trades clos, ${META.seuil_jours} jours ` +
              `d${APO}historique et une concentration sous ` +
              META.seuil_conc.toLocaleString('fr-FR', {minimumFractionDigits: 2}) + '.' },
      { t: 'En hausse',
        lignes: (d.top_movers || []).map(x => ligneC(x.a, '↑ ' + esc(x.message))),
        vide: 'Aucun mouvement de position notable. Une alerte de rang exige un déplacement ' +
              'de position relative : la seule arrivée de nouveaux wallets ne la déclenche pas.' },
      { t: 'En baisse',
        lignes: (d.declining || []).map(x => ligneC(x.a, '↓ ' + esc(x.message))),
        vide: 'Aucune baisse de position notable.' },
      { t: 'Sorties',
        lignes: (d.archived || []).map(x => ligneC(x.a, esc(x.raison || ''))),
        vide: 'Aucun retrait. Un wallet n\u2019est retiré que sur un critère réellement ' +
              'réfuté, jamais sur une donnée simplement manquante.' },
      { t: 'Retours au classement',
        lignes: (d.reactivated || []).map(x => ligneC(x.a, esc(x.message))),
        vide: 'Aucun retour. Un wallet archivé revient uniquement s' + APO + 'il repasse les critères.' },
      // « Candidats du dernier cycle », PAS « En observation » : ce mot désigne
      // ailleurs les 31 505 wallets de l'état DISCOVERY. Deux populations sous un
      // même mot, sur le même écran, ne se distinguent plus.
      { t: 'Candidats du dernier cycle',
        lignes: (d.watch || []).slice(0, 8).map(x => ligneC(x.a,
          esc((x.manque || [])[0] ? critere(x.manque[0])
                                  : (CLASSES[x.classe] || x.classe || '')))),
        note: 'Aucun de ces wallets n' + APO + 'est refusé : il leur manque du temps. ' +
              `La qualification demande ${META.seuil_jours} jours d${APO}historique ` +
              `et ${META.seuil_trades} trades clos.`,
        vide: 'Aucun candidat proche des critères ce cycle.' },
      { t: 'Récemment qualifiés',
        lignes: qualif.map(w => ligneC(w.a, date(w.promu * 1000))),
        vide: 'Aucune qualification datée : le champ n\u2019existe que depuis le registre.' },
      { t: 'Dormants',
        lignes: dormants.map(w => ligneC(w.a, 'dernier trade ' + jours(w.dort_j))),
        vide: 'Aucun wallet classé n\u2019est dormant depuis plus de deux mois.' },
      { t: 'Tête du classement',
        lignes: top.map(w => ligneC(w.a, usd(w.pnl) + ' cumulé')),
        vide: 'Classement indisponible.' },
    ])}
    ${(d.blocages || []).map(b => `<div class="prot" style="margin-top:var(--e5)">
      <h4>Blocage — ${esc(b.sujet)} (${esc(b.portee)})</h4>
      <p>${esc(b.cause)}</p>
      <p><b>Interdit automatiquement</b> — ${esc(b.action_interdite)}</p>
      <p><b>Demande</b> — ${esc(b.demande)}</p></div>`).join('')}
    <p class="pied">&#961; ${nb(META.spearman, 4)} · ECE ${nb(META.ece, 4)} ·
      <b>${esc(META.verdict)}</b></p>`;
}

/* ════════════════════════════════════════════════════════ donnees
   Le produit doit rendre visible QUAND IL NE SAIT PAS. */
function rendData() {
  const d = DAILY || {}, h = d.data_health || {}, sy = d.system_health || {};
  const q = h.quota || {};
  const cats = [];
  const add = (k, v) => { if (v) cats.push([k, v]); };
  add('Entrées au classement', (d.new_ranked || []).length);
  add('Retours', (d.reactivated || []).length);
  add('Fortes hausses', (d.top_movers || []).length);
  add('Fortes baisses', (d.declining || []).length);
  add('Sorties', (d.archived || []).length);
  add('Problèmes de collecte', (h.erreurs_collecte || []).length);
  add('Blocages scientifiques', (d.blocages || []).length);

  document.getElementById('dh').innerHTML = `
    <div class="sect"><span class="lab">Fraîcheur</span></div>
    <div class="grid">
      ${cellule('Dernière collecte', d.horodatage ? dateh(d.horodatage) : NA)}
      ${cellule('Page générée le', esc(META.maj))}
      ${cellule('Mode du cycle', esc(d.mode || 'N/D'))}
      ${cellule('Durée', sy.duree_s == null ? NA : String(sy.duree_s), 's')}
    </div>

    <div class="sect"><span class="lab">Couverture</span></div>
    <div class="grid">
      ${cellule('Wallets classés', String(META.ranked ?? META.n))}
      ${cellule('En observation', String(META.discovery_total ?? '—'))}
      ${cellule('Archivés', String(META.archives_total ?? 0))}
      ${cellule('Trades analysés', (META.trades / 1000).toFixed(1), 'k')}
      ${cellule('Reste à évaluer', String(h.a_reevaluer ?? '—'))}
      ${cellule('Séries fraîches', h.series_fraiches == null ? NA : (h.series_fraiches ? 'oui' : 'non'))}
    </div>

    <div class="sect"><span class="lab">Provenance</span></div>
    <div class="grid">
      ${cellule('Observé', String(META.avec_natif ?? 0), '/ ' + META.n)}
      ${cellule('Dérivé', String(META.n - (META.avec_natif ?? 0)), '/ ' + META.n)}
      ${cellule('Sans probabilité', String(META.sans_p_cal ?? 0), '/ ' + META.n)}
      ${cellule('Verdict natif', esc(META.verdict))}
    </div>
    <p class="note">Seuls <b>${META.avec_natif ?? 0} wallets sur ${META.n}</b> ont une donnée
      native permettant de confronter notre reconstruction à une seconde source. Le verdict
      du protocole reste <b>${esc(META.verdict)}</b> : ${esc(META.verdict_motif)}. Ce n'est
      pas une validation, et l'interface ne le présente jamais comme telle.</p>

    <div class="sect"><span class="lab">Ressources</span></div>
    <div class="grid">
      ${cellule('Requêtes HyperTracker', String(h.requetes_hypertracker_utilisees ?? 0))}
      ${cellule('Requêtes Hyperliquid', String(h.requetes_hyperliquid_consommees ?? 0))}
      ${cellule('Budget alloué', String(h.budget_requetes ?? 0))}
      ${cellule('Budget restant', String(h.budget_restant ?? 0))}
      ${cellule('Reportés', String(h.refuses_budget ?? 0))}
      ${cellule('Quota épuisé', q.epuise == null ? NA : (q.epuise ? 'oui' : 'non'))}
    </div>
    <p class="note">Le cycle quotidien ne dépense <b>aucune</b> requête HyperTracker : ses
      sources sont les instantanés de carnet déjà sur disque et l'API publique Hyperliquid.</p>

    <div class="sect"><span class="lab">Alertes du dernier cycle</span></div>
    ${cats.length ? cats.map(x => `<div class="li" style="cursor:default">
        <span class="adr">${esc(x[0])}</span><span class="rt">${x[1]}</span></div>`).join('')
      : `<p class="note">Aucune alerte sur le dernier cycle.</p>`}
    ${(h.erreurs_collecte || []).length
      ? `<p class="note">${(h.erreurs_collecte || []).map(esc).join(' · ')}</p>` : ''}

    ${(d.blocages || []).map(b => `<div class="prot" style="margin-top:var(--e4)">
      <h4>Blocage — ${esc(b.sujet)} (${esc(b.portee)})</h4>
      <p>${esc(b.cause)}</p>
      <p><b>Interdit automatiquement</b> — ${esc(b.action_interdite)}</p>
      <p><b>Demande</b> — ${esc(b.demande)}</p></div>`).join('')}

    <div class="sect"><span class="lab">Réputation HyperTracker</span></div>
    <div class="prot"><h4>Chiffres HyperTracker, pas les nôtres</h4>
      <p>${(RP.wallets || []).length} wallets viennent des classements perpétuels
      HyperTracker. Sur ${(RP.meta || {}).n ?? '—'},
      <b>${(RP.meta || {}).sans_trade_clos ?? '—'} n'ont aucun trade clos</b> : ils tiennent
      des positions longtemps sans revenir à plat. Notre modèle compte des allers-retours
      clos, il ne peut pas les mesurer. PnL de compte et performance par trade clos ne sont
      pas la même grandeur, et l'application ne les additionne jamais.</p></div>

    <p class="pied">&#961; ${nb(META.spearman, 4)} · ECE ${nb(META.ece, 4)} ·
      <b>${esc(META.verdict)}</b></p>`;
}

/* ════════════════════════════════════════════════════════ routage
   Par fragment : le bouton retour du systeme fonctionne sans code, et une fiche
   est une VRAIE page adressable. `/watch` et `/disco` restent valides — ils
   ouvrent l'ecran qui les a absorbes, pour qu'aucun lien ne casse. */
const ECRANS = {
  '/':     { t: 'Aujourd’hui', s: 'Ce qui a changé' },
  '/rank': { t: 'Classement',  s: 'Wallet Intelligence' },
  '/data': { t: 'Données',     s: 'Fraîcheur et provenance' },
};
const VUES = { '/': 'v-jour', '/rank': 'v-rank', '/data': 'v-data' };
const ALIAS = { '/watch': '/rank', '/disco': '/' };
let routeCourante = '/';
/* Vrai des la premiere navigation INTERNE. Sur une ouverture directe sur une
   fiche, il n'y a rien derriere : « Retour » doit mener au classement plutot
   que de sortir de l'application. */
let navInterne = false;

function entete(r, w) {
  const hd = document.getElementById('hd');
  if (r === '/w') {
    hd.innerHTML = `<button class="btn" id="bk" aria-label="Retour">← Retour</button>
      <span class="htitle" style="text-align:right"><h1 style="font-size:12px;letter-spacing:.14em"
        >${w ? String(w.rang).padStart(3, '0') : 'Wallet'}</h1>
      <p>${w ? 'score ' + w.score.toFixed(1) + ' · IC ' + w.ic[0] + '–' + w.ic[1] : ''}</p></span>`;
    hd.querySelector('#bk').onclick = () =>
      navInterne ? history.back() : (location.hash = '#/rank');
    return;
  }
  const e = ECRANS[r] || ECRANS['/'];
  hd.innerHTML = `<span class="htitle"><h1>${e.t}</h1><p>${e.s}</p></span>
    ${r === '/rank' ? `<span class="lab"><span id="cnt"></span> / ${META.n}</span>` : ''}`;
  majCompteur();
}

function route() {
  let h = (location.hash || '#/').slice(1);
  document.querySelectorAll('.view').forEach(v => v.classList.remove('on'));
  if (h.indexOf('/w/') === 0) {
    const a = h.slice(3).toLowerCase();
    document.getElementById('v-wallet').classList.add('on');
    entete('/w', byA[a]); ouvre(a); majNav(null);
    routeCourante = '/w';
    return;
  }
  if (ALIAS[h]) {
    if (h === '/watch') {
      ETAT.filtre = 'suivi';
      if (ETAT.tri === 'score') ETAT.tri = 'mien';
      S.set('etat', ETAT); chips(); rendu(true);
    }
    h = ALIAS[h];
  }
  const r = VUES[h] ? h : '/';
  document.getElementById(VUES[r]).classList.add('on');
  entete(r); majNav(r);
  routeCourante = r;
  if (r === '/') rendJour();
  if (r === '/data') rendData();
  requestAnimationFrame(() => window.scrollTo(0, SCROLL[r] || 0));
}
function majNav(h) {
  document.querySelectorAll('nav button').forEach(b =>
    b.classList.toggle('on', h != null && b.dataset.nav === h));
}
window.addEventListener('hashchange', () => { navInterne = true; route(); });
window.addEventListener('scroll', () => {
  if (routeCourante !== '/w') SCROLL[routeCourante] = window.scrollY;
}, { passive: true });
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  if (location.hash.slice(1) === b.dataset.nav) {
    window.scrollTo({ top: 0, behavior: 'smooth' }); return;
  }
  location.hash = '#' + b.dataset.nav;
});

/* un releve ouvre une page : delegation, pour ne pas poser 267 ecouteurs */
function ouvrirDepuis(e) {
  if (e.target.closest('button, input, .well, summary')) return;
  const c = e.target.closest('[data-a]');
  if (!c) return;
  if (routeCourante !== '/w') SCROLL[routeCourante] = window.scrollY;
  location.hash = '#/w/' + c.dataset.a;
}
document.addEventListener('click', ouvrirDepuis);
document.addEventListener('keydown', e => { if (e.key === 'Enter') ouvrirDepuis(e); });

/* ════════════════════════════════════════════════════════ demarrage */
const CONV = [
  ['q3', 's', 'élevée',  'conf_elevee'],
  ['q2', 'd', 'moyenne', 'conf_moyenne'],
  ['q1', 'p', 'faible',  'conf_faible'],
];
/* La convention est simultanement la LEGENDE du style de trait des mors,
   l'indicateur de repartition, et le controle de filtre : on apprend la
   grammaire en s'en servant. */
function convention() {
  const el = document.getElementById('conv');
  el.innerHTML = CONV.map(x => {
    const v = META[x[3]] || 0;
    return `<button class="cseg ${x[1]}${ETAT.filtre === x[0] ? ' on' : ''}" data-c="${x[0]}"
      aria-pressed="${ETAT.filtre === x[0]}"
      aria-label="Qualité ${x[2]}, ${v} wallets. Filtrer."><i aria-hidden="true"></i>
      <span>${x[2]} ${v}</span></button>`;
  }).join('');
  el.onclick = e => {
    const b = e.target.closest('.cseg'); if (!b) return;
    ETAT.filtre = (ETAT.filtre === b.dataset.c) ? 'tous' : b.dataset.c;
    S.set('etat', ETAT); SCROLL['/rank'] = 0;
    convention(); chips(); rendu(true);
  };
}
function chips() {
  document.getElementById('filtres').innerHTML = '<span class="lab">Filtre</span>' +
    FILTRES.map(x =>
      `<button class="chip${x[0] === ETAT.filtre ? ' on' : ''}" data-f="${x[0]}">${x[1]}</button>`).join('');
  document.getElementById('tris').innerHTML = '<span class="lab">Tri</span>' +
    TRIS.map(x =>
      `<button class="chip${x[0] === ETAT.tri ? ' on' : ''}" data-t="${x[0]}">${x[1]}</button>`).join('');
  document.getElementById('filtres').onclick = e => {
    const b = e.target.closest('.chip'); if (!b) return;
    ETAT.filtre = b.dataset.f;
    // L'ordre naturel d'une liste de suivi est celui qu'on lui a donne, pas le
    // score : sans cela les fleches deplaceraient un rang que personne ne voit.
    if (ETAT.filtre === 'suivi' && ETAT.tri === 'score') ETAT.tri = 'mien';
    S.set('etat', ETAT); SCROLL['/rank'] = 0;
    convention(); chips(); rendu(true);
  };
  document.getElementById('tris').onclick = e => {
    const b = e.target.closest('.chip'); if (!b) return;
    ETAT.tri = b.dataset.t; S.set('etat', ETAT); SCROLL['/rank'] = 0;
    document.querySelectorAll('#tris .chip').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); rendu(true);
  };
}
function recherche() {
  const q = document.getElementById('q'), box = document.getElementById('sbox');
  q.value = ETAT.q || '';
  box.classList.toggle('has', !!q.value);
  let t;
  q.oninput = () => {
    box.classList.toggle('has', !!q.value);
    clearTimeout(t);
    t = setTimeout(() => { ETAT.q = q.value; S.set('etat', ETAT); SCROLL['/rank'] = 0; rendu(true); }, 130);
  };
  document.getElementById('qc').onclick = () => {
    q.value = ''; ETAT.q = ''; S.set('etat', ETAT);
    box.classList.remove('has'); rendu(true); q.focus();
  };
}
let redim;
let LARG = window.innerWidth;
window.addEventListener('resize', () => {
  // HAUTEUR SEULE = barre d'URL qui se retracte pendant le defilement. Ce n'est
  // pas un changement de mise en page, et le traiter comme tel renvoyait le
  // lecteur en haut de fiche a chaque scroll.
  if (window.innerWidth === LARG) return;
  LARG = window.innerWidth;
  clearTimeout(redim);
  redim = setTimeout(() => {
    if (routeCourante === '/w') redessineFiche();
    if (routeCourante === '/') rendJour();
    if (routeCourante === '/data') rendData();
  }, 200);
});

convention(); chips(); recherche(); rendu(true); route();
</script>
"""


def main() -> int:
    html = (TPL.replace("%%DATA%%", json.dumps(DATA, separators=(",", ":")))
               .replace("%%REP%%", json.dumps(REP, separators=(",", ":"))))
    with open(SORTIE, "w", encoding="utf8", newline="\n") as f:
        f.write(html)
    print(f"ecrit -> {SORTIE}  ({os.path.getsize(SORTIE) / 1024:.0f} Ko)")
    print(f"  {len(DATA['wallets'])} wallets | {len(REP.get('wallets', []))} de reputation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
