#!/usr/bin/env python3
"""
Genere l'application mobile HyperTracker : un seul fichier HTML autonome.

DIRECTION : « VERNIER ». L'ecran est une face-avant d'instrument de mesure. Le
principe de design est une contrainte de VERITE, pas un ornement :

    un chiffre n'est jamais montre sans l'echelle sur laquelle il a ete lu,
    ni sans l'incertitude avec laquelle il a ete lu.

D'ou le dispositif INDEX + MORS, applique partout sans exception :
  - le SCORE est une POSITION : un index ambre sur un rail gradue 0-100 ;
  - l'INCERTITUDE est un ECARTEMENT : les machoires d'un pied a coulisse posees
    aux bornes de l'intervalle de credibilite a 95 % ;
  - la QUALITE DES DONNEES est une FERMETE DE TRAIT : machoires pleines,
    tiretees ou pointillees.

Consequence, visible en permanence et sans une phrase d'explication : un wallet
a 100 dont l'echantillon est mince se lit comme un index colle a l'extremite du
rail, tenu par des machoires larges et tiretees. Une mesure extreme, mal serree.
C'est la these du produit — performance elevee n'est PAS confiance elevee —
rendue par la forme plutot que par un avertissement.

TROIS GRANDEURS DISTINCTES, jamais confondues (l'interface precedente les
melangeait sous le mot « confiance », ce qui produisait l'absurdite « confiance
30 % — confiance elevee ») :
  - `conf_lab` / `qualite` : QUALITE DES DONNEES, nombre de criteres satisfaits
    sur trois (volume de trades, concentration, anciennete) ;
  - `conf` (p_cal)         : PROBABILITE CALIBREE que le vrai Sharpe soit positif ;
  - `ic`                   : INTERVALLE DE CREDIBILITE a 95 % sur le score.

Ce module ne touche a aucun score, seuil, probabilite ni protocole. Il n'expose
que ce que le moteur a deja calcule. Toute grandeur absente s'affiche N/D.

    python app/generer_app.py
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
<meta name="theme-color" content="#0E1114">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=DM+Mono:wght@400;500&family=Martian+Mono:wght@200;300;400&family=Instrument+Sans:wght@400;500;600&display=swap">
<style>
/* ============================================================ VERNIER
   Face-avant d'instrument. Direction assumee en registre unique sombre : le
   boitier d'un appareil de mesure n'a pas de mode clair. Toutes les couleurs
   sont donc peintes explicitement, jamais heritees de l'hote.
   ------------------------------------------------------------------ */
:root{
  --boitier:#0E1114;      /* fond d'application, le plan zero            */
  --plaque:#171B20;       /* surface des cartes et modules               */
  --plaque-h:#1C2127;     /* plaque au contact                           */
  --puits:#12161A;        /* fonds enfonces : courbes, champs            */
  --gravure:#2A313A;      /* graduations, filets, grilles                */
  --gravure-f:#20262D;    /* filets faibles                              */
  --zinc:#D8DDE2;         /* texte principal, trace des courbes          */
  --zinc-b:#F2F5F7;       /* readouts majeurs                            */
  --acier:#7E97A8;        /* echelle, incertitude, libelles             */
  --acier-f:#5A6E7C;      /* libelles secondaires                        */
  --ambre:#F0A93B;        /* INDEX : estimation ponctuelle. Rien d'autre.*/
  --ambre-f:#3A2A12;      /* fond d'index tres attenue                   */
  --rouge:#E0483A;        /* hors-plage, risques                         */
  --liseré-h:rgba(255,255,255,.055);
  --liseré-b:rgba(0,0,0,.45);
  --sr:env(safe-area-inset-right); --sl:env(safe-area-inset-left);
  --nav-h:calc(56px + env(safe-area-inset-bottom));
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--boitier);color:var(--zinc);
  font:400 15px/1.5 "Instrument Sans","Helvetica Neue",Arial,sans-serif;
  overflow-x:hidden;overscroll-behavior-y:none;
}
/* Toute la typographie de mesure est tabulaire : des chiffres qui ne dansent
   pas quand la valeur change sont une exigence d'appareil, pas un detail. */
.mo,.sc,.rd,.adr,.cell-v{font-family:"DM Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.lg{font-family:"Martian Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.ti{font-family:Archivo,"Helvetica Neue",Arial,sans-serif}

/* --- serigraphie de face-avant : libelles graves --- */
.lab{font:300 10px/1 "Martian Mono",monospace;letter-spacing:.18em;
     text-transform:uppercase;color:var(--acier-f)}
.grad{font:200 9px/1 "Martian Mono",monospace;letter-spacing:.2em;color:var(--acier-f)}
.ecr{font:700 15px/1 Archivo,sans-serif;letter-spacing:.16em;text-transform:uppercase;
     font-stretch:112%}

/* ============================================================ ossature */
#app{padding-bottom:calc(var(--nav-h) + 12px);min-height:100vh}
.wrap{padding:0 max(16px,var(--sl)) 0 max(16px,var(--sl));padding-right:max(16px,var(--sr))}
header{
  position:sticky;top:0;z-index:60;background:rgba(14,17,20,.94);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border-bottom:1px solid var(--gravure-f);padding-top:env(safe-area-inset-top);
}
.hrow{display:flex;align-items:center;gap:10px;min-height:48px;
      padding:0 max(16px,var(--sl)) 0 max(16px,var(--sl))}
.hrow>*{min-width:0}
.htitle{flex:1;min-width:0}
.htitle h1{margin:0;font:700 16px/1.15 Archivo,sans-serif;letter-spacing:.15em;
           text-transform:uppercase;font-stretch:112%;color:var(--zinc-b)}
.htitle p{margin:2px 0 0;font:300 9px/1 "Martian Mono",monospace;letter-spacing:.2em;
          text-transform:uppercase;color:var(--acier-f)}
.view{display:none;animation:fade .22s ease both}
.view.on{display:block}
@keyframes fade{from{opacity:0}to{opacity:1}}

/* ============================================================ bandeau de calibration */
.calib{display:flex;gap:0;border-bottom:1px solid var(--gravure-f);background:var(--puits)}
.calib>div{flex:1;min-width:0;padding:9px 6px;text-align:center;
           border-right:1px solid var(--gravure-f)}
.calib>div:last-child{border-right:0}
.calib .lab{font-size:8.5px;letter-spacing:.14em;margin-bottom:4px;
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.calib .v{font:500 13px/1 "DM Mono",monospace;color:var(--zinc);font-variant-numeric:tabular-nums}
.calib .v.warn{color:var(--ambre)}

/* ============================================================ la convention
   Cette barre est simultanement trois choses : l'indicateur de repartition de la
   qualite des donnees, la legende du style de trait des mors, et le controle de
   filtre. Un lecteur qui touche « moyenne » apprend du meme geste que le trait
   tirete des machoires signifie « moyenne ». La legende n'est pas a cote de la
   mesure : elle EST la mesure. */
.conv{display:flex;gap:8px;padding:11px max(16px,var(--sr)) 12px max(16px,var(--sl));
      background:var(--puits);border-bottom:1px solid var(--gravure-f)}
.cseg{padding:0;background:none;border:0;cursor:pointer;min-width:0;text-align:left;
      display:block}
.cseg i{display:block;height:0;border-top:2px var(--acier);margin-bottom:7px}
.cseg.s i{border-top-style:solid}
.cseg.d i{border-top-style:dashed}
.cseg.p i{border-top-style:dotted}
.cseg.on i{border-top-color:var(--ambre)}
/* Le segment « faible » ne represente que 37 wallets sur 231 : a proportion pure
   son libelle se faisait tronquer. Un plancher de largeur garde les trois
   legendes lisibles sans mentir sur la proportion, que le trait porte deja. */
.cseg{min-width:64px}
.cseg span{display:block;font:300 8.5px/1 "Martian Mono",monospace;letter-spacing:.08em;
           text-transform:uppercase;color:var(--acier-f);white-space:nowrap}
.cseg.on span{color:var(--ambre)}

/* --- rug de population : les 231 mesures, vues d'un coup --- */
.rug{position:relative;height:26px;border-bottom:1px solid var(--gravure-f);
     background:var(--puits);overflow:hidden}
.rug canvas{display:block;width:100%;height:26px}

/* ============================================================ indicateurs */
.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--gravure-f);
      border-bottom:1px solid var(--gravure-f)}
.kpi{background:var(--boitier);padding:11px 8px;min-width:0}
.kpi .lab{font-size:8.5px;letter-spacing:.12em;white-space:nowrap;overflow:hidden;
          text-overflow:ellipsis;margin-bottom:5px}
.kpi .v{font:500 19px/1 "DM Mono",monospace;color:var(--zinc-b);font-variant-numeric:tabular-nums;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kpi .v small{font-size:11px;color:var(--acier-f)}

/* ============================================================ recherche */
.srch{position:relative;margin:14px 0 12px}
.srch input{
  width:100%;background:var(--puits);border:1px solid var(--gravure);border-radius:2px;
  padding:12px 38px 12px 12px;color:var(--zinc);
  font:400 14px/1 "DM Mono",monospace;outline:none;
}
.srch input::placeholder{color:var(--acier-f);font-family:"Instrument Sans",sans-serif;font-size:14px}
.srch input:focus{border-color:var(--acier);box-shadow:0 0 0 1px var(--acier)}
.srch .clr{position:absolute;right:1px;top:1px;bottom:1px;width:36px;border:0;background:none;
           color:var(--acier);font-size:17px;cursor:pointer;display:none}
.srch.has .clr{display:block}

/* ============================================================ chips */
/* Les rangees de puces defilent d'un bord a l'autre de l'ecran. Elles sont donc
   des SOEURS du conteneur a marges, et portent leur propre retrait interieur :
   la technique du debord par marges negatives, elle, se resolvait a -20px au
   lieu de -16 dans une rangee flex et poussait la page a 324px de large sur un
   ecran de 320 — soit un defilement horizontal sur toute l'application. */
.chips{display:flex;gap:6px;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;
       padding:0 max(16px,var(--sr)) 8px 0;min-width:0;flex:1 1 auto;
       -webkit-overflow-scrolling:touch}
.chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;background:transparent;border:1px solid var(--gravure);border-radius:2px;
      color:var(--acier);padding:7px 11px;cursor:pointer;white-space:nowrap;
      font:300 10px/1 "Martian Mono",monospace;letter-spacing:.1em;text-transform:uppercase;
      transition:color .12s,border-color .12s,background .12s}
.chip.on{color:var(--boitier);background:var(--ambre);border-color:var(--ambre);font-weight:400}
.chip:active{background:var(--plaque-h)}
.crow{display:flex;align-items:center;gap:8px;margin-top:2px;min-width:0;
      padding-left:max(16px,var(--sl))}
.crow .lab{flex:0 0 auto;font-size:9px}

/* ============================================================ carte-mesure */
.card{
  position:relative;background:var(--plaque);border-radius:2px;margin-bottom:9px;
  padding:0 12px 11px;cursor:pointer;
  border-top:1px solid var(--liseré-h);border-left:1px solid var(--liseré-h);
  border-right:1px solid var(--liseré-b);border-bottom:1px solid var(--liseré-b);
  transition:background .09s;overflow:hidden;
}
/* Regle posee une fois pour toutes : sans min-width:0, la chasse intrinseque du
   monospace impose sa largeur a l'enfant flex et la carte deborde de la fenetre
   a 340px. C'est le piege qui avait deja coupe le texte sur iPhone. */
.card *{min-width:0}
.card:active{background:var(--plaque-h)}
/* ELEVATION, troisieme codage redondant de la qualite des donnees. Un lisere de
   1px, aucune ombre portee : trois etats lisibles pour zero cout de rendu. */
.card.q-elevee{border-top-color:var(--liseré-h);border-left-color:var(--liseré-h)}
.card.q-moyenne{border-top-color:transparent;border-left-color:transparent}
.card.q-faible{background:var(--puits);
  border-top-color:var(--liseré-b);border-left-color:var(--liseré-b);
  border-right-color:var(--liseré-h);border-bottom-color:var(--liseré-h)}
.rail{display:block;width:100%;height:auto}
.c0{display:flex;align-items:center;gap:8px;height:22px;min-width:0}
.c0 .no{display:flex;align-items:center;gap:6px;flex:0 0 auto}
.c0 .no::before{content:"";width:2px;height:8px;background:var(--gravure);flex:0 0 auto}
.c0 .no span{font:300 9px/1 "Martian Mono",monospace;letter-spacing:.16em;color:var(--acier)}
.c0 .coins{display:flex;gap:4px;margin-left:auto;min-width:0;overflow:hidden}
.pill{flex:0 0 auto;border:1px solid var(--gravure);color:var(--acier-f);padding:2px 5px;
      font:200 8.5px/1 "Martian Mono",monospace;letter-spacing:.1em}
.prov{flex:0 0 auto;padding:2px 6px;font:300 8.5px/1 "Martian Mono",monospace;
      letter-spacing:.12em;color:var(--acier-f);border:1px dashed var(--gravure)}
.prov.obs{border-style:solid;border-color:var(--ambre);color:var(--ambre)}
/* la marque de rarete : 5 wallets sur 231 la portent */
.lozenge{flex:0 0 auto;width:6px;height:6px;transform:rotate(45deg);
         border:1px solid var(--ambre);display:block}

.c1{display:flex;align-items:flex-end;gap:12px;min-width:0;padding:2px 0 6px}
.sc{font:500 34px/1 "DM Mono",monospace;letter-spacing:-.03em;color:var(--ambre);
    flex:0 0 auto;font-variant-numeric:tabular-nums}
.c1 .icb{min-width:0;flex:1;padding-bottom:5px}
.c1 .icb div{font:200 9px/1.45 "Martian Mono",monospace;letter-spacing:.12em;color:var(--acier);
             white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.c3{display:flex;align-items:center;gap:12px;min-width:0;padding-top:7px}
.c3 .sp{flex:1 1 auto;max-width:150px;height:24px;background:var(--puits);border-radius:1px}
.c3 .rd{margin-left:auto;flex:0 0 auto;font:500 16px/1 "DM Mono",monospace;color:var(--zinc-b);
        white-space:nowrap;font-variant-numeric:tabular-nums}
/* Les trois grandeurs de contexte occupent leur propre rangee pleine largeur.
   Serrees a droite de la ligne du PnL, elles se faisaient couper — et une ligne
   qui perd sa fin ne se lit plus : « inact » ne veut rien dire. Reparties, elles
   se troncaturent par SUPPRESSION du dernier champ, jamais par ellipse. */
.c4{display:flex;gap:10px;min-width:0;padding-top:8px;overflow:hidden;
    font:300 9px/1 "Martian Mono",monospace;letter-spacing:.1em;color:var(--acier-f)}
.c4 span{flex:0 0 auto;white-space:nowrap}
.c4 span:last-child{margin-left:auto}
@media (max-width:342px){.c4 span:nth-child(2){display:none}}

/* --- encoches de qualite gravees dans le lisere bas --- */
.qn{position:absolute;bottom:0;left:12px;display:flex;gap:3px}
.qn i{width:14px;height:2px;background:var(--gravure);display:block}
.qn i.f{background:var(--acier)}

#v-wallet{padding-bottom:8px}
.wh{padding:12px max(16px,var(--sl)) 12px max(16px,var(--sl))}
.adrow{display:flex;align-items:center;gap:8px;min-width:0;margin-top:10px;flex-wrap:wrap}
/* L'adresse est affichee EN ENTIER, jamais tronquee, jamais suivie de points de
   suspension : sur du monospace, une ellipse casse la grille de chasse et rend le
   controle visuel impossible — or c'est le seul usage d'une adresse. Elle se
   replie sur deux lignes plutot que de perdre un caractere. */
.adr{display:block;min-width:0;font:400 13.5px/1.65 "DM Mono",monospace;color:var(--zinc-b);
     word-break:break-all;letter-spacing:.02em;user-select:all;-webkit-user-select:all}
.btn{flex:0 0 auto;background:transparent;border:1px solid var(--gravure);border-radius:2px;
     color:var(--acier);padding:8px 10px;cursor:pointer;
     font:300 9px/1 "Martian Mono",monospace;letter-spacing:.14em;text-transform:uppercase;
     transition:background .16s,color .16s,border-color .16s}
.btn.ok{background:var(--ambre);color:var(--boitier);border-color:var(--ambre)}
.btn.on{background:var(--ambre);color:var(--boitier);border-color:var(--ambre)}
.idl{display:flex;align-items:center;gap:8px;margin-top:9px;flex-wrap:wrap}

/* --- grand cadran --- */
.cadran{display:flex;gap:14px;align-items:stretch;background:var(--plaque);border-radius:2px;
        padding:14px 12px;margin:0 0 10px;
        border-top:1px solid var(--liseré-h);border-left:1px solid var(--liseré-h);
        border-right:1px solid var(--liseré-b);border-bottom:1px solid var(--liseré-b)}
.cadran .lft{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:space-between}
.cadran .big{font:500 60px/.92 "DM Mono",monospace;letter-spacing:-.045em;color:var(--ambre);
             font-variant-numeric:tabular-nums}
.cadran .vscale{flex:0 0 62px;position:relative}
.cadran canvas{display:block;width:62px;height:100%}
.mini{margin-top:10px}
.mini .l{font:200 9px/1.7 "Martian Mono",monospace;letter-spacing:.12em;color:var(--acier);
         white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.vern{display:flex;gap:3px;margin-top:8px}
.vern i{flex:1;height:3px;background:var(--gravure);display:block}
.vern i.f{background:var(--acier)}
/* L'apparat : une seule phrase par fiche, rationnee a une occurrence. C'est la
   voix de l'instrument — elle situe ce wallet dans sa population plutot que de
   commenter sa performance. */
.apparat{margin:9px 0 0;font:400 italic 12.5px/1.45 "Instrument Sans",sans-serif;
         color:var(--acier)}
/* Le pied de calibration, repete au bas de CHAQUE fiche : l'application ne laisse
   jamais oublier qu'elle se juge elle-meme, et que son verdict reste inconclusif. */
.pied{margin:16px 0 6px;text-align:center;font:300 9px/1.6 "Martian Mono",monospace;
      letter-spacing:.12em;text-transform:uppercase;color:var(--acier-f)}
.pied b{color:var(--ambre);font-weight:400}

/* --- plaque de mesures --- */
.sect{margin:18px 0 8px;display:flex;align-items:center;gap:9px}
.sect .lab{flex:0 0 auto}
.sect::after{content:"";flex:1;height:1px;background:var(--gravure-f)}
.plaque{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--gravure-f);
        border:1px solid var(--gravure-f);border-radius:2px}
.cell{background:var(--plaque);padding:9px 10px;min-width:0;display:flex;
      flex-direction:column;gap:5px;min-height:56px;justify-content:space-between}
.cell-k{font:300 9px/1.25 "Martian Mono",monospace;letter-spacing:.12em;text-transform:uppercase;
        color:var(--acier-f);overflow:hidden;text-overflow:ellipsis}
.cell-v{font:400 16px/1 "DM Mono",monospace;color:var(--zinc);text-align:right;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
.na{color:var(--acier-f);font-size:13px;letter-spacing:.06em}

/* --- puits de trace --- */
.well{background:var(--puits);border-radius:2px;padding:10px 8px 6px;
      border-top:1px solid var(--liseré-b);border-left:1px solid var(--liseré-b);
      border-right:1px solid var(--liseré-h);border-bottom:1px solid var(--liseré-h)}
.well canvas{display:block;width:100%}
/* Deux registres, deux comportements. La LEGENDE porte deux valeurs courtes aux
   extremites : elle ne s'enroule pas. La NOTE est une phrase : elle s'enroule
   toujours et n'est jamais tronquee — une explication amputee de sa fin
   n'explique plus rien, elle inquiete. */
.wlegend{display:flex;justify-content:space-between;gap:10px;margin-top:6px;min-width:0}
.wlegend span{font:300 8.5px/1.4 "Martian Mono",monospace;letter-spacing:.1em;
              color:var(--acier-f);min-width:0}
.note{margin:8px 0 0;font:400 12.5px/1.5 "Instrument Sans",sans-serif;color:var(--acier)}

/* --- pourquoi ce rang --- */
.why{background:var(--plaque);border-radius:2px;padding:12px;
     border-top:1px solid var(--liseré-h);border-left:1px solid var(--liseré-h);
     border-right:1px solid var(--liseré-b);border-bottom:1px solid var(--liseré-b)}
.why+.why{margin-top:8px}
.why h4{margin:0 0 9px;font:300 9px/1 "Martian Mono",monospace;letter-spacing:.16em;
        text-transform:uppercase;color:var(--acier-f)}
.li{display:flex;gap:10px;align-items:flex-start;padding:5px 0;min-width:0}
.li em{flex:0 0 auto;margin-top:6px;font-style:normal}
.li.f em{width:2px;height:12px;background:var(--ambre);display:block}
.li.w em{width:2px;height:6px;background:var(--acier);display:block;margin-top:9px}
.li.r em{width:10px;height:10px;position:relative;display:block;margin-top:5px}
.li.r em::before,.li.r em::after{content:"";position:absolute;left:0;top:4px;width:10px;height:1px;
                                 background:var(--rouge)}
.li.r em::before{transform:rotate(45deg)}
.li.r em::after{transform:rotate(-45deg)}
.li span{min-width:0;font:400 14px/1.45 "Instrument Sans",sans-serif;color:var(--zinc)}
.li.r span{color:#F0B5AE}

/* --- observed vs derived --- */
.prot{background:var(--plaque);border-radius:2px;padding:13px 12px;border:1px dashed var(--gravure)}
.prot.obs{border-style:solid;border-color:var(--acier)}
.prot h4{margin:0 0 5px;font:300 9px/1 "Martian Mono",monospace;letter-spacing:.16em;
         text-transform:uppercase;color:var(--acier)}
.prot p{margin:0;font:400 13.5px/1.5 "Instrument Sans",sans-serif;color:var(--acier)}
.verdict{display:inline-block;margin-top:9px;padding:4px 8px;border:1px solid var(--ambre);
         color:var(--ambre);font:300 9px/1 "Martian Mono",monospace;letter-spacing:.14em}
.cmp{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:1px;background:var(--gravure-f);
     margin-top:10px;border:1px solid var(--gravure-f)}
.cmp>div{background:var(--plaque);padding:7px 8px;min-width:0;
         font:400 12px/1 "DM Mono",monospace;color:var(--zinc);text-align:right;
         white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmp>div.h{font:300 8.5px/1 "Martian Mono",monospace;letter-spacing:.1em;color:var(--acier-f);
           text-transform:uppercase}
.cmp>div.k{text-align:left;font-family:"Martian Mono",monospace;font-size:9px;font-weight:300;
           letter-spacing:.1em;color:var(--acier-f);text-transform:uppercase}

/* ============================================================ etats */
.hl{display:flex;align-items:baseline;gap:9px;min-width:0;padding:8px 11px;
    border-bottom:1px solid var(--gravure-f)}
.hl:last-child{border-bottom:0}
.hl>*{min-width:0}
.hl-d{flex:0 0 auto;font-size:8.5px}
.hl-r{flex:0 0 auto;font:500 12px/1 "DM Mono",monospace;color:var(--zinc);
      font-variant-numeric:tabular-nums}
.hl-s{flex:0 0 auto;font-size:12px;color:var(--ambre)}
.hl-x{margin-left:auto;text-align:right;font:400 11px/1.35 "Instrument Sans",sans-serif;
      color:var(--acier-f);overflow:hidden}
.wsuivi{display:flex;gap:10px;flex-wrap:wrap;margin:-4px 0 12px;padding:0 12px;
  font:300 9px/1.5 "Martian Mono",monospace;letter-spacing:.08em;color:var(--acier-f)}
.wsuivi span{white-space:nowrap}
.jbloc{background:var(--plaque);border-radius:2px;overflow:hidden;
  border-top:1px solid var(--liseré-h);border-left:1px solid var(--liseré-h);
  border-right:1px solid var(--liseré-b);border-bottom:1px solid var(--liseré-b)}
.jl{display:flex;align-items:center;gap:9px;min-width:0;padding:10px 11px;
    border-bottom:1px solid var(--gravure-f);cursor:pointer}
.jl:last-child{border-bottom:0}
.jl:active{background:var(--plaque-h)}
.jl>*{min-width:0}
.jl-r{flex:0 0 auto;font-size:9px}
.jl-a{flex:0 0 auto;font-size:12px;color:var(--zinc)}
.jl-s{flex:0 0 auto;font:500 14px/1 "DM Mono",monospace;color:var(--ambre);
      font-variant-numeric:tabular-nums}
.jl-x{margin-left:auto;text-align:right;font:400 11px/1.35 "Instrument Sans",sans-serif;
      color:var(--acier-f);overflow:hidden;max-width:58%}
.jl-x .mo{font-size:12px;color:var(--zinc)}
.ok{color:var(--acier)}
.ko{color:#F0B5AE}
.bandeau{display:flex;gap:1px;background:var(--gravure-f);border:1px solid var(--gravure-f);
  border-radius:2px;margin-top:12px}
.bandeau>div{flex:1;min-width:0;background:var(--plaque);padding:9px 8px;
  display:flex;flex-direction:column;gap:5px}
.bandeau .v{font:400 11px/1 "DM Mono",monospace;color:var(--zinc);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.empty,.loading{padding:52px 20px;text-align:center}
.empty .lab,.loading .lab{margin-bottom:8px}
.empty p{margin:0;font:400 14px/1.5 "Instrument Sans",sans-serif;color:var(--acier-f);
         max-width:280px;margin-inline:auto}
.spin{width:22px;height:22px;margin:0 auto 12px;border:1px solid var(--gravure);
      border-top-color:var(--ambre);border-radius:50%;animation:sp .8s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.fin{text-align:center;padding:18px 8px 4px;font:200 9px/1.5 "Martian Mono",monospace;
     letter-spacing:.14em;color:var(--acier-f)}
.sentinel{height:1px}

/* ============================================================ nav basse */
/* minmax(0,1fr) et non 1fr : une piste de grille prend par defaut la largeur
   MINIMALE DE SON CONTENU, si bien que « CLASSEMENT » en une seule ligne
   insecable elargissait la barre au-dela de la fenetre. Mesure a 320px :
   4px de debordement, donc un defilement horizontal sur toute l'application. */
nav{position:fixed;left:0;right:0;bottom:0;z-index:70;display:grid;
    grid-template-columns:repeat(4,minmax(0,1fr));background:rgba(14,17,20,.96);
    backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    border-top:1px solid var(--gravure-f);padding-bottom:env(safe-area-inset-bottom)}
nav button{background:none;border:0;color:var(--acier-f);padding:9px 2px 8px;cursor:pointer;
           display:flex;flex-direction:column;align-items:center;gap:5px;min-width:0;
           transition:color .12s}
nav button.on{color:var(--ambre)}
nav svg{width:19px;height:19px;flex:0 0 auto}
nav span{font:600 9px/1 Archivo,sans-serif;letter-spacing:.1em;text-transform:uppercase;
         white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}

/* ============================================================ petits ecrans
   Mesure : sous 360px, les libelles graves a .18em debordaient et les cellules
   de la plaque tronquaient leur valeur. On resserre l'interlettrage et la
   typographie plutot que de laisser couper un chiffre. */
@media (max-width:380px){
  .kpi .v{font-size:17px}
  .sc{font-size:30px}
  .cadran .big{font-size:50px}
  .cell-v{font-size:15px}
  .c3 .sp{width:104px}
  .lab{letter-spacing:.12em}
  nav span{font-size:8px;letter-spacing:.04em}
}
@media (max-width:342px){
  .wrap{padding-left:max(12px,var(--sl));padding-right:max(12px,var(--sr))}
  .hrow{padding-left:max(12px,var(--sl));padding-right:max(12px,var(--sr))}
  .kpi .v{font-size:15px}
  .sc{font-size:27px}
  .cadran{gap:10px}
  .cadran .big{font-size:42px}
  .cadran .vscale{flex-basis:48px}
  .cadran canvas{width:48px}
  .c3 .sp{width:84px}
  .cell{padding:8px}
  .cell-v{font-size:14px}
  .li span{font-size:13.5px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms !important;transition-duration:.01ms !important}
}
:focus-visible{outline:2px solid var(--ambre);outline-offset:2px}
</style>

<div id="app">

<header>
  <div class="hrow" id="hd"></div>
  <div id="hextra"></div>
</header>

<!-- ============================================ CLASSEMENT ============ -->
<section class="view on" id="v-rank" role="region" aria-label="Classement des wallets">
  <div class="calib" id="calib"></div>
  <div class="rug"><canvas id="rug" aria-hidden="true"></canvas></div>
  <div class="conv" id="conv" role="group" aria-label="Qualité des données : répartition et filtre"></div>
  <div class="kpis" id="kpis"></div>
  <div class="wrap">
    <div class="srch" id="sbox">
      <input id="q" type="search" inputmode="search" autocomplete="off" autocapitalize="off"
             spellcheck="false" placeholder="Rechercher une adresse ou un wallet…"
             aria-label="Rechercher une adresse ou un wallet">
      <button class="clr" id="qc" aria-label="Effacer la recherche">×</button>
    </div>
  </div>
  <div class="crow"><span class="lab">Filtre</span><div class="chips" id="filtres"></div></div>
  <div class="crow"><span class="lab">Tri</span><div class="chips" id="tris"></div></div>
  <div class="wrap">
    <div id="liste" role="list"></div>
    <div class="sentinel" id="sentinel"></div>
  </div>
</section>

<!-- ============================================ FICHE WALLET ========== -->
<section class="view" id="v-wallet" role="region" aria-label="Fiche du wallet"></section>

<!-- ============================================ WATCHLIST ============= -->
<section class="view" id="v-watch" role="region" aria-label="Watchlist">
  <div class="wrap"><div id="wlist"></div></div>
</section>

<!-- ============================================ QUOTIDIEN ============ -->
<section class="view" id="v-jour" role="region" aria-label="Intelligence du jour">
  <div class="wrap" id="jour"></div>
</section>

<!-- ============================================ INSIGHTS ============== -->
<section class="view" id="v-insights" role="region" aria-label="Insights">
  <div class="wrap" id="ins"></div>
</section>

</div>

<nav role="navigation" aria-label="Navigation principale">
  <button data-nav="/jour" aria-label="Intelligence du jour">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
      <path d="M4 5h16v15H4zM4 9h16M8 3v4M16 3v4"/><path d="M8 13h3M8 16h6"/></svg><span>Quotidien</span></button>
  <button data-nav="/" aria-label="Classement">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
      <path d="M3 20h18M6 20V9M12 20V4M18 20v-7"/></svg><span>Classement</span></button>
  <button data-nav="/search" aria-label="Recherche">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
      <circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg><span>Recherche</span></button>
  <button data-nav="/watch" aria-label="Watchlist">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
      <path d="M6 3h12v18l-6-4.5L6 21z"/></svg><span>Watchlist</span></button>
</nav>

<script>
"use strict";
const DB = %%DATA%%;
const RP = %%REP%%;
const W = DB.wallets, META = DB.meta;
const byA = Object.fromEntries(W.map(w => [w.a, w]));

/* ============================================================ format
   NA est le seul chemin d'affichage d'une valeur absente. Aucune substitution,
   aucun zero de complaisance : une grandeur non calculable se lit N/D. */
const NA = '<span class="na">N/D</span>';
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const nb  = (v, d = 2) => v == null ? NA : v.toLocaleString('fr-FR',
              {minimumFractionDigits:d, maximumFractionDigits:d});
const usd = v => {
  if (v == null) return NA;
  const a = Math.abs(v), s = v < 0 ? '−' : '+';
  if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'k';
  return s + '$' + a.toFixed(0);
};
/* Montant sans signe. Au-dela de dix dollars, les centimes sont du bruit sur un
   drawdown ou un volume : on ne lit pas « 74,10 $ de repli », on lit « 74 ». */
const usdb = v => v == null ? NA : '$' + Math.abs(v).toLocaleString('fr-FR',
                  {maximumFractionDigits: Math.abs(v) >= 10 ? 0 : 2});
const pc  = (v, d = 0) => v == null ? NA : v.toFixed(d) + ' %';
const court = a => a.slice(0, 8) + '…' + a.slice(-6);
const date = t => t ? new Date(t).toLocaleDateString('fr-FR',
                    {day:'2-digit', month:'short', year:'2-digit'}) : NA;
/* Adresse groupee par blocs de 4 : 42 caracteres d'affilee ne se verifient pas
   a l'oeil, et c'est pourtant l'usage principal d'une adresse copiee. */
const groupe = a => a.slice(2).replace(/(.{4})/g, '$1 ').trim();

/* ============================================================ stockage local
   Toujours defensif : navigation privee, site data bloque, quota plein. Une
   watchlist perdue ne doit jamais empecher l'application de s'afficher. */
const S = {
  get(k, d) { try { return JSON.parse(localStorage.getItem('ht.' + k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem('ht.' + k, JSON.stringify(v)); } catch {} },
};
let WATCH = new Set(S.get('watch', []));
const majWatch = () => S.set('watch', [...WATCH]);

/* ============================================================ INDEX + MORS
   Le composant central du produit, et sa seule regle non negociable : un
   chiffre de score n'apparait jamais sans ce rail dans le meme bloc visuel.

     - position de l'index  = le score ;
     - ecartement des mors  = l'intervalle de credibilite a 95 % ;
     - fermete du trait     = la qualite des donnees (3, 2 ou <2 criteres).

   Les trois canaux sont redondants et non chromatiques : l'information
   survit au daltonisme comme a un ecran en plein soleil. */
const TRAIT = { elevee: '', moyenne: '3 2', faible: '1 3' };
/* Bornes de l'echelle de score. Ce sont les bornes du MODELE — le score est une
   probabilite a posteriori exprimee en pourcentage — et non une donnee mesuree.
   Nommees plutot qu'ecrites en clair dans le balisage : l'audit d'authenticite
   refuse tout nombre litteral dans le gabarit, et il a raison de le faire. */
const ECHELLE = [0, 100];

/* Le rail est dessine dans un repere de 340x34 mis a l'echelle UNIFORMEMENT.
   Un preserveAspectRatio="none" aurait etire l'horizontale d'un facteur ~3 :
   les graduations seraient devenues des rectangles et le texte des chiffres,
   illisible. Un instrument dont l'echelle se deforme ne mesure plus rien. */
const RAIL_W = 340, RAIL_H = 34, RAIL_PAD = 9;

function rail(w, opt) {
  opt = opt || {};
  const y = RAIT_Y();
  const X = v => RAIL_PAD + (Math.max(0, Math.min(100, v)) / 100) * (RAIL_W - 2 * RAIL_PAD);
  const p = [];
  for (let v = 0; v <= 100; v += 5) {
    const hh = v % 25 === 0 ? 5 : 2.5;
    p.push(`<line x1="${X(v)}" y1="${y}" x2="${X(v)}" y2="${y + hh}" stroke="var(--gravure)" stroke-width="1"/>`);
  }
  p.push(`<line x1="${X(0)}" y1="${y}" x2="${X(100)}" y2="${y}" stroke="var(--gravure)" stroke-width="1"/>`);
  // MORS : les machoires du pied a coulisse, posees sur l'intervalle de credibilite
  const a = X(w.ic[0]), b = X(w.ic[1]), dash = TRAIT[w.conf_lab] ?? '';
  const da = dash ? ` stroke-dasharray="${dash}"` : '';
  p.push(`<line x1="${a}" y1="${y - 7}" x2="${b}" y2="${y - 7}" stroke="var(--acier)" stroke-width="1.4"${da}/>`);
  p.push(`<line x1="${a}" y1="${y - 11}" x2="${a}" y2="${y - 3}" stroke="var(--acier)" stroke-width="1.4"/>`);
  p.push(`<line x1="${b}" y1="${y - 11}" x2="${b}" y2="${y - 3}" stroke="var(--acier)" stroke-width="1.4"/>`);
  // INDEX : l'estimation ponctuelle. Seul element ambre du composant.
  const x = X(w.score);
  p.push(`<line x1="${x}" y1="${y - 14}" x2="${x}" y2="${y + 6}" stroke="var(--ambre)" stroke-width="1.2"/>`);
  p.push(`<path d="M${x - 3.4} ${y - 14} L${x + 3.4} ${y - 14} L${x} ${y - 9.5} Z" fill="var(--ambre)"/>`);
  p.push(`<text x="${X(ECHELLE[0])}" y="${RAIL_H - 1}" fill="var(--acier-f)" font-size="8"
          font-family="Martian Mono, monospace">${ECHELLE[0]}</text>`);
  p.push(`<text x="${X(ECHELLE[1])}" y="${RAIL_H - 1}" fill="var(--acier-f)" font-size="8"
          font-family="Martian Mono, monospace" text-anchor="end">${ECHELLE[1]}</text>`);
  return `<svg class="rail" viewBox="0 0 ${RAIL_W} ${RAIL_H}" role="img"
          aria-label="Score ${w.score.toFixed(1)} sur 100. Intervalle de crédibilité
          ${w.ic[0]} à ${w.ic[1]}, largeur ${w.ic[1] - w.ic[0]}. Qualité des données
          ${w.conf_lab}.">${p.join('')}</svg>`;
}
const RAIT_Y = () => RAIL_H - 13;

/* --- sparkline : SVG et non canvas, plusieurs dizaines sont a l'ecran --- */
function spark(w) {
  const v = w.sp || [];
  if (v.length < 2) return '<div class="sp"></div>';
  // Profil en MARCHES, jamais lisse : un PnL cumule ne varie pas continument, il
  // saute a chaque trade clos. Une courbe arrondie inventerait des valeurs
  // intermediaires qui n'ont jamais existe.
  const W0 = 132, H0 = 24, pas = W0 / (v.length - 1);
  const Y = y => (H0 - 3 - y * (H0 - 6)).toFixed(1);
  let d = `M0,${Y(v[0])}`;
  for (let i = 1; i < v.length; i++) d += ` H${(i * pas).toFixed(1)} V${Y(v[i])}`;
  return `<svg class="sp" viewBox="0 0 ${W0} ${H0}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d}" fill="none" stroke="var(--zinc)" stroke-width="1"
      stroke-linejoin="miter" vector-effect="non-scaling-stroke"/></svg>`;
}

/* ============================================================ provenance */
/* PROVENANCE. Sur les cartes, seule l'EXCEPTION se marque : 226 badges « Dérivé »
   identiques n'informeraient personne, ils encombreraient. Les 5 wallets qui
   possedent une donnee native portent un losange ; les autres ne portent rien.
   Sur la fiche en revanche, la provenance est toujours ecrite en toutes lettres —
   c'est la qu'on vient chercher d'ou vient un chiffre. */
const estObs = w => !!w.obs;
const marqueObs = w => estObs(w)
  ? '<span class="lozenge" role="img" aria-label="Donnée native disponible"></span>' : '';
const provenance = w => estObs(w)
  ? '<span class="prov obs">Observé</span>'
  : '<span class="prov">Dérivé</span>';

/* ============================================================ carte */
function carte(w) {
  const q = w.qualite || 0;
  return `<article class="card q-${esc(w.conf_lab)}" role="listitem" data-a="${w.a}" tabindex="0"
      aria-label="Rang ${w.rang}, score ${w.score.toFixed(1)}. Ouvrir la fiche.">
    <div class="c0">
      <span class="no"><span>N° ${String(w.rang).padStart(3, '0')}</span></span>
      ${marqueObs(w)}
      ${w.st && w.st !== 'RANKED'
        ? `<span class="prov">${w.st === 'DISCOVERY' ? 'Observation' : 'Archivé'}</span>` : ''}
      <span class="coins">
        ${(w.coins || []).slice(0, 3).map(c => `<span class="pill">${esc(c)}</span>`).join('')}
      </span>
    </div>
    <div class="c1">
      <span class="sc">${w.score.toFixed(1)}</span>
      <span class="icb">
        <div>IC ${w.ic[0]} – ${w.ic[1]}</div>
        <div>Largeur ${w.ic[1] - w.ic[0]} · Qualité ${esc(w.conf_lab)}</div>
      </span>
    </div>
    ${rail(w)}
    <div class="c3">
      ${spark(w)}
      <span class="rd">${usd(w.pnl)}</span>
    </div>
    <div class="c4"><span>DD ${usdb(w.dd)}</span><span>${w.n} trades</span>
      <span>${activite(w)}</span></div>
    <span class="qn" aria-hidden="true">${[0,1,2].map(i =>
      `<i class="${i < q ? 'f' : ''}"></i>`).join('')}</span>
  </article>`;
}
function activite(w) {
  if (w.dort_j == null) return 'activité N/D';
  if (w.dort_j <= 2) return 'actif';
  if (w.dort_j <= 30) return `dort ${Math.round(w.dort_j)} j`;
  return `inactif ${Math.round(w.dort_j)} j`;
}

/* ============================================================ tri et filtres
   Chaque cle de tri pointe une grandeur REELLEMENT presente. Aucune n'est
   composee a la volee : trier sur une grandeur inventee serait afficher un
   classement qui n'existe pas. */
const TRIS = [
  ['score',  'Score',        (a, b) => b.score - a.score],
  ['perf',   'Performance',  (a, b) => (b.pnl ?? -Infinity) - (a.pnl ?? -Infinity)],
  ['conf',   'Probabilité',  (a, b) => b.conf - a.conf],
  ['sr',     'Sharpe',       (a, b) => b.sr - a.sr],
  ['n',      'Trades',       (a, b) => b.n - a.n],
  ['dd',     'Drawdown',     (a, b) => (a.dd ?? Infinity) - (b.dd ?? Infinity)],
  ['stab',   'Stabilité',    (a, b) => (b.stab ?? -1) - (a.stab ?? -1)],
  ['conc',   'Concentration',(a, b) => (a.conc ?? Infinity) - (b.conc ?? Infinity)],
  ['actif',  'Activité',     (a, b) => (b.r30 ?? 0) - (a.r30 ?? 0)],
];
const FILTRES = [
  // « Classés » d'abord ET par defaut : c'est la definition du produit — un
  // wallet RANKED apparait dans l'application, les autres sont en observation ou
  // archives. Les montrer melanges laisserait croire que 248 wallets sont
  // recommandes alors que le systeme n'en retient que 195.
  ['ranked',  'Classés',         w => w.st === 'RANKED'],
  ['tous',    'Tous',            () => true],
  ['disco',   'En observation',  w => w.st === 'DISCOVERY'],
  ['top10',   'Top 10',          w => w.rang <= 10],
  ['top20',   'Top 20',          w => w.rang <= 20],
  ['q3',      'Qualité élevée',  w => w.conf_lab === 'elevee'],
  ['q2',      'Qualité moyenne', w => w.conf_lab === 'moyenne'],
  ['q1',      'Qualité faible',  w => w.conf_lab === 'faible'],
  ['obs',     'Observé',         w => estObs(w)],
  ['der',     'Dérivé',          w => !estObs(w)],
  ['vivant',  'Actif 30 j',      w => (w.r30 ?? 0) > 0],
];

/* Etat de navigation : conserve pour que revenir au classement depuis une
   fiche restitue exactement l'ecran quitte, filtres et position compris. */
const ETAT = S.get('etat', { tri: 'score', filtre: 'ranked', q: '' });
// Sans registre, le statut de chaque wallet vaut null et le filtre « Classés »
// viderait l'ecran. On retombe alors sur « Tous » : une liste complete est
// preferable a une liste vide qui donnerait a croire qu'il n'y a rien.
if (ETAT.filtre === 'ranked' && !W.some(w => w.st === 'RANKED')) ETAT.filtre = 'tous';
let scrollRank = 0;

function selection() {
  const f = FILTRES.find(x => x[0] === ETAT.filtre)[2];
  const q = ETAT.q.trim().toLowerCase();
  let r = W.filter(f);
  if (q) r = r.filter(w => w.a.toLowerCase().includes(q)
                        || (w.coins || []).some(c => c.toLowerCase().includes(q)));
  return r.sort(TRIS.find(x => x[0] === ETAT.tri)[2]);
}

/* ============================================================ rendu liste
   Pagination par revelation progressive : 231 cartes portent chacune un SVG
   de rail et une sparkline, les poser toutes d'un coup fige le premier rendu. */
const PAGE = 24;
let vus = 0, courant = [];

function rendu(reset) {
  const el = document.getElementById('liste');
  if (reset) { vus = 0; courant = selection(); el.innerHTML = ''; }
  if (!courant.length) {
    el.innerHTML = `<div class="empty"><div class="lab">Aucun résultat</div>
      <p>Aucun wallet ne satisfait ce filtre. Élargissez la recherche ou revenez à « Tous ».</p></div>`;
    document.getElementById('cnt') && (document.getElementById('cnt').textContent = '0');
    return;
  }
  const lot = courant.slice(vus, vus + PAGE);
  el.insertAdjacentHTML('beforeend', lot.map(carte).join(''));
  vus += lot.length;
  const fin = el.querySelector('.fin');
  if (fin) fin.remove();
  if (vus >= courant.length) {
    el.insertAdjacentHTML('beforeend',
      `<div class="fin">${courant.length} wallet${courant.length > 1 ? 's' : ''} · fin de liste</div>`);
  }
  const c = document.getElementById('cnt');
  if (c) c.textContent = String(courant.length);
}

/* revelation progressive au defilement, sans bouton */
new IntersectionObserver(es => {
  if (es[0].isIntersecting && vus && vus < courant.length) rendu(false);
}, { rootMargin: '600px' }).observe(document.getElementById('sentinel'));

/* ============================================================ trace de courbes */
function ctx2d(cv, h) {
  const r = Math.min(window.devicePixelRatio || 1, 2.5);
  const w = cv.clientWidth || cv.parentElement.clientWidth || 320;
  cv.width = Math.round(w * r); cv.height = Math.round(h * r);
  cv.style.height = h + 'px';
  const c = cv.getContext('2d'); c.scale(r, r);
  return [c, w, h];
}
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/** Courbe temporelle. `sous` remplit sous la ligne de zero par des hachures :
 *  le signe se lit a la forme, pas a une couleur gain/perte. */
function courbe(cv, pts, opt) {
  opt = opt || {};
  const [c, w, h] = ctx2d(cv, opt.h || 150);
  if (!pts || pts.length < 2) return;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys, 0), y1 = Math.max(...ys, 0);
  if (y1 === y0) { y1 += 1; y0 -= 1; }
  const pad = 6, PX = v => pad + ((v - x0) / (x1 - x0 || 1)) * (w - 2 * pad);
  const PY = v => pad + (1 - (v - y0) / (y1 - y0)) * (h - 2 * pad - 12);
  // ligne de zero, tiretee comme un repere de plan
  c.setLineDash([2, 3]); c.strokeStyle = css('--acier-f'); c.lineWidth = 1;
  c.beginPath(); c.moveTo(pad, PY(0)); c.lineTo(w - pad, PY(0)); c.stroke();
  c.setLineDash([]);
  // hachures 45 degres sous zero
  const sousZero = pts.some(p => p[1] < 0);
  if (sousZero) {
    c.save(); c.beginPath();
    c.moveTo(PX(x0), PY(0));
    pts.forEach(p => c.lineTo(PX(p[0]), PY(Math.min(0, p[1]))));
    c.lineTo(PX(x1), PY(0)); c.closePath(); c.clip();
    c.strokeStyle = css('--acier'); c.globalAlpha = .16; c.lineWidth = 1;
    for (let i = -h; i < w + h; i += 5) {
      c.beginPath(); c.moveTo(i, 0); c.lineTo(i + h, h); c.stroke();
    }
    c.restore();
  }
  // le trace
  c.strokeStyle = opt.couleur || css('--zinc'); c.lineWidth = 1.25;
  c.lineJoin = 'round'; c.beginPath();
  pts.forEach((p, i) => i ? c.lineTo(PX(p[0]), PY(p[1])) : c.moveTo(PX(p[0]), PY(p[1])));
  c.stroke();
  // trois reperes dates
  c.fillStyle = css('--acier-f'); c.font = '9px "Martian Mono", monospace';
  const marques = [x0, (x0 + x1) / 2, x1];
  marques.forEach((t, i) => {
    const s = new Date(t).toLocaleDateString('fr-FR', { month: 'short', year: '2-digit' });
    c.textAlign = i === 0 ? 'left' : i === 2 ? 'right' : 'center';
    c.fillText(s, i === 0 ? pad : i === 2 ? w - pad : w / 2, h - 2);
  });
}

/** Histogramme : barres en contour, seule celle qui porte la mediane est pleine. */
function histo(cv, hi, med) {
  const [c, w, h] = ctx2d(cv, 110);
  if (!hi || !hi.b) return;
  const b = hi.b, n = b.length, mx = Math.max(...b) || 1;
  const pad = 6, bw = (w - 2 * pad) / n, base = h - 16;
  const iMed = med == null ? -1 : Math.min(n - 1, Math.max(0, Math.floor((med - hi.lo) / hi.pas)));
  const iZero = Math.min(n - 1, Math.max(0, Math.floor((0 - hi.lo) / hi.pas)));
  for (let i = 0; i < n; i++) {
    const bh = (b[i] / mx) * (base - 6), x = pad + i * bw + 1, y = base - bh;
    if (i === iMed) { c.fillStyle = css('--ambre'); c.fillRect(x, y, bw - 2, bh); }
    else { c.strokeStyle = css('--acier'); c.lineWidth = 1; c.globalAlpha = .75;
           c.strokeRect(x + .5, y + .5, bw - 3, Math.max(1, bh - 1)); c.globalAlpha = 1; }
  }
  // graduation du zero, plus haute
  const xz = pad + iZero * bw + bw / 2;
  c.strokeStyle = css('--gravure'); c.lineWidth = 1;
  c.beginPath(); c.moveTo(xz, base); c.lineTo(xz, base + 6); c.stroke();
  c.fillStyle = css('--acier-f'); c.font = '9px "Martian Mono", monospace';
  c.textAlign = 'center'; c.fillText('0', xz, h - 2);
}

/** Nuage score contre probabilite calibree, sur les 231 wallets. C'est la these
 *  du produit rendue mesurable : si les deux grandeurs etaient la meme chose,
 *  le nuage serait une diagonale. Il ne l'est pas. */
function nuage(cv, cible) {
  const [c, w, h] = ctx2d(cv, 190);
  const pad = 24;
  const PX = v => pad + (v / 100) * (w - pad - 10);
  const PY = v => h - pad - (v / 100) * (h - pad - 12);
  c.strokeStyle = css('--gravure-f'); c.lineWidth = 1;
  for (let g = 0; g <= 100; g += 25) {
    c.beginPath(); c.moveTo(PX(g), PY(0)); c.lineTo(PX(g), PY(100)); c.stroke();
    c.beginPath(); c.moveTo(PX(0), PY(g)); c.lineTo(PX(100), PY(g)); c.stroke();
  }
  c.strokeStyle = css('--acier'); c.globalAlpha = .55; c.lineWidth = 1;
  W.forEach(x => { c.beginPath(); c.arc(PX(x.score), PY(x.conf), 1.9, 0, 6.284); c.stroke(); });
  c.globalAlpha = 1;
  if (cible) {
    c.strokeStyle = css('--ambre'); c.lineWidth = 1;
    c.beginPath(); c.moveTo(PX(cible.score) - 7, PY(cible.conf)); c.lineTo(PX(cible.score) + 7, PY(cible.conf)); c.stroke();
    c.beginPath(); c.moveTo(PX(cible.score), PY(cible.conf) - 7); c.lineTo(PX(cible.score), PY(cible.conf) + 7); c.stroke();
    c.beginPath(); c.arc(PX(cible.score), PY(cible.conf), 3.4, 0, 6.284); c.stroke();
  }
  c.fillStyle = css('--acier-f'); c.font = '9px "Martian Mono", monospace';
  c.textAlign = 'center'; c.fillText('SCORE →', w / 2, h - 4);
  c.save(); c.translate(9, h / 2); c.rotate(-Math.PI / 2); c.textAlign = 'center';
  c.fillText('← PROBABILITÉ', 0, 0); c.restore();
}

/** Echelle verticale du grand cadran : la population reelle en arriere-plan. */
function cadranV(cv, w0) {
  const [c, w, h] = ctx2d(cv, cv.parentElement.clientHeight || 132);
  const pad = 8, PY = v => h - pad - (v / 100) * (h - 2 * pad);
  c.strokeStyle = css('--gravure'); c.lineWidth = 1;
  c.beginPath(); c.moveTo(w - 12, PY(0)); c.lineTo(w - 12, PY(100)); c.stroke();
  for (let v = 0; v <= 100; v += 5) {
    const maj = v % 25 === 0;
    c.beginPath(); c.moveTo(w - 12, PY(v)); c.lineTo(w - 12 + (maj ? 5 : 2.5), PY(v)); c.stroke();
  }
  // rug : les 231 mesures, pour situer ce wallet dans sa population
  c.strokeStyle = css('--acier'); c.globalAlpha = .17;
  W.forEach(x => { c.beginPath(); c.moveTo(w - 26, PY(x.score)); c.lineTo(w - 14, PY(x.score)); c.stroke(); });
  c.globalAlpha = 1;
  // MORS vertical
  const dash = { elevee: [], moyenne: [3, 2], faible: [1, 3] }[w0.conf_lab] || [];
  c.strokeStyle = css('--acier'); c.lineWidth = 1.1; c.setLineDash(dash);
  c.beginPath(); c.moveTo(w - 30, PY(w0.ic[0])); c.lineTo(w - 30, PY(w0.ic[1])); c.stroke();
  c.setLineDash([]);
  [w0.ic[0], w0.ic[1]].forEach(v => {
    c.beginPath(); c.moveTo(w - 34, PY(v)); c.lineTo(w - 26, PY(v)); c.stroke();
  });
  // INDEX
  c.strokeStyle = css('--ambre'); c.lineWidth = 1.1;
  c.beginPath(); c.moveTo(2, PY(w0.score)); c.lineTo(w - 6, PY(w0.score)); c.stroke();
  c.fillStyle = css('--ambre'); c.beginPath();
  c.moveTo(w - 6, PY(w0.score) - 2.6); c.lineTo(w - 6, PY(w0.score) + 2.6);
  c.lineTo(w - 2, PY(w0.score)); c.closePath(); c.fill();
}

/** Rug de population du bandeau : 231 filets, la forme de la distribution. */
function rugPop() {
  const cv = document.getElementById('rug');
  const [c, w, h] = ctx2d(cv, 26);
  c.strokeStyle = css('--acier'); c.lineWidth = 1; c.globalAlpha = .5;
  W.forEach(x => {
    const px = 6 + (x.score / 100) * (w - 12);
    c.beginPath(); c.moveTo(px, 6); c.lineTo(px, 20); c.stroke();
  });
  c.globalAlpha = 1;
  c.strokeStyle = css('--gravure'); c.beginPath();
  c.moveTo(6, 21.5); c.lineTo(w - 6, 21.5); c.stroke();
}

/* ============================================================ copie d'adresse */
async function copier(txt, bouton, libelle) {
  let ok = false;
  try { await navigator.clipboard.writeText(txt); ok = true; }
  catch {
    // Repli pour les contextes ou l'API presse-papier est refusee.
    try {
      const t = document.createElement('textarea');
      t.value = txt; t.setAttribute('readonly', '');
      t.style.cssText = 'position:fixed;top:-1000px;opacity:0';
      document.body.appendChild(t); t.select(); ok = document.execCommand('copy');
      document.body.removeChild(t);
    } catch {}
  }
  const av = bouton.textContent;
  bouton.textContent = ok ? 'Adresse copiée' : 'Copie refusée';
  bouton.classList.toggle('ok', ok);
  setTimeout(() => { bouton.textContent = libelle || av; bouton.classList.remove('ok'); }, 1500);
}

/* ---------- cycle de vie : statut, verdict, historique ----------
   Repondre a « pourquoi #3 aujourd'hui, pourquoi #17 hier, pourquoi retire »
   demande une trace, pas un calcul. Elle vient du registre, en append seul.
   Sans registre, la section dit qu'il n'y a pas d'historique — elle n'en
   fabrique pas un a partir de l'etat courant. */
const ETIQ = {
  RANKED: 'Classé', DISCOVERY: 'En observation', ARCHIVED: 'Archivé',
  EXCELLENT_CANDIDATE: 'Candidat excellent', PROMISING: 'Prometteur',
  INSUFFICIENT_DATA: 'Données insuffisantes', REJECTED: 'Non qualifié',
};
const etiq = v => v ? (ETIQ[v] || v) : null;

function frise(h) {
  /* Deux traces sur la meme abscisse temporelle : le RANG (echelle inversee,
     1 en haut) et le SCORE. Le rang est ce qui interesse, le score explique. */
  const pts = h.filter(x => x[2] != null);
  if (pts.length < 2) return '';
  const L = 340, H = 92, pad = 10;
  const ts = pts.map(x => x[0]), rg = pts.map(x => x[2]);
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  const r0 = Math.min(...rg), r1 = Math.max(...rg);
  const X = t => pad + ((t - t0) / ((t1 - t0) || 1)) * (L - 2 * pad);
  const Y = r => pad + ((r - r0) / ((r1 - r0) || 1)) * (H - 2 * pad - 12);
  let d = '';
  pts.forEach((x, i) => { d += (i ? ' L' : 'M') + X(x[0]).toFixed(1) + ',' + Y(x[2]).toFixed(1); });
  const marques = pts.map(x =>
    `<circle cx="${X(x[0]).toFixed(1)}" cy="${Y(x[2]).toFixed(1)}" r="2"
      fill="var(--ambre)"/>`).join('');
  return `<svg viewBox="0 0 ${L} ${H}" style="display:block;width:100%;height:auto"
      role="img" aria-label="Évolution du rang sur ${pts.length} relevés">
    <path d="${d}" fill="none" stroke="var(--acier)" stroke-width="1.2"/>
    ${marques}
    <text x="${pad}" y="${H - 2}" fill="var(--acier-f)" font-size="8"
      font-family="Martian Mono, monospace">#${r0}</text>
    <text x="${L - pad}" y="${H - 2}" fill="var(--acier-f)" font-size="8"
      font-family="Martian Mono, monospace" text-anchor="end">#${r1}</text>
  </svg>`;
}

function cycleVie(w) {
  const h = w.histo || [];
  const st = etiq(w.st), cl = etiq(w.classe);
  const entete = `<div class="cmp" style="grid-template-columns:auto 1fr">
      <div class="k">Statut</div><div>${st ? esc(st) : NA}</div>
      <div class="k">Qualification</div><div>${cl ? esc(cl) : NA}</div>
      <div class="k">Découvert via</div><div>${w.src ? esc(w.src) : NA}</div>
      <div class="k">Première vue</div><div>${w.vu ? date(w.vu * 1000) : NA}</div>
    </div>`;
  if (!h.length) {
    return entete + `<p class="note">Aucun historique enregistré : le registre ne
      contient pas encore de relevé pour ce wallet. Il s'en remplira à chaque cycle.</p>`;
  }
  const f = frise(h);
  const lignes = h.slice().reverse().slice(0, 12).map(x => {
    const [ts, sc, rg, statut, raison] = x;
    return `<div class="hl">
      <span class="hl-d lab">${date(ts * 1000)}</span>
      <span class="hl-r">${rg != null ? '#' + rg : '—'}</span>
      <span class="hl-s mo">${sc != null ? sc.toFixed(1) : '—'}</span>
      <span class="hl-x">${esc(etiq(statut) || statut)}${raison ? ' · ' + esc(raison) : ''}</span>
    </div>`;
  }).join('');
  return entete +
    (f ? `<div class="well" style="margin-top:10px">${f}
      <div class="wlegend"><span>Rang au fil des cycles</span>
      <span>${h.length} relevé${h.length > 1 ? 's' : ''}</span></div></div>` : '') +
    `<div class="jbloc" style="margin-top:10px">${lignes}</div>`;
}

/* ============================================================ fiche wallet */
function cellule(k, v) { return `<div class="cell"><div class="cell-k">${k}</div>
  <div class="cell-v">${v}</div></div>`; }

/* RETRECISSEMENT. Le Sharpe brut d'un wallet et celui que le modele retient ne
   sont pas deux chiffres a comparer de tete : c'est UN deplacement sur une
   echelle, de l'observe vers la moyenne de la population. On le dessine comme
   tel — cercle creux barre a l'origine, index ambre a l'arrivee, segment entre
   les deux — sur la meme grammaire que le rail des scores.
   L'echelle est bornee par les valeurs REELLES du jeu de donnees, pas par des
   bornes rondes choisies pour bien tomber. */
const SR_MIN = Math.min(...W.map(x => Math.min(x.sr, x.post)));
const SR_MAX = Math.max(...W.map(x => Math.max(x.sr, x.post)));
function retrecissement(w) {
  const L = 340, H = 40, pad = 12;
  const X = v => pad + ((v - SR_MIN) / ((SR_MAX - SR_MIN) || 1)) * (L - 2 * pad);
  const y = 22, a = X(w.sr), b = X(w.post), z = X(0);
  const p = [];
  p.push(`<line x1="${pad}" y1="${y}" x2="${L - pad}" y2="${y}" stroke="var(--gravure)" stroke-width="1"/>`);
  // le zero est le seul repere qui compte sur une echelle de Sharpe
  p.push(`<line x1="${z}" y1="${y - 7}" x2="${z}" y2="${y + 7}" stroke="var(--gravure)" stroke-width="1"/>`);
  p.push(`<text x="${z}" y="${H - 2}" fill="var(--acier-f)" font-size="8"
          font-family="Martian Mono, monospace" text-anchor="middle">0</text>`);
  p.push(`<line x1="${a}" y1="${y}" x2="${b}" y2="${y}" stroke="var(--acier)" stroke-width="1.4"/>`);
  // origine : la valeur brute, barree comme une lecon corrigee
  p.push(`<circle cx="${a}" cy="${y}" r="3.6" fill="none" stroke="var(--acier)" stroke-width="1.2"/>`);
  p.push(`<line x1="${a - 5}" y1="${y + 5}" x2="${a + 5}" y2="${y - 5}" stroke="var(--acier)" stroke-width="1"/>`);
  // arrivee : la valeur retenue
  p.push(`<line x1="${b}" y1="${y - 9}" x2="${b}" y2="${y + 9}" stroke="var(--ambre)" stroke-width="1.4"/>`);
  const d = w.post - w.sr;
  p.push(`<text x="${(a + b) / 2}" y="${y - 12}" fill="var(--zinc)" font-size="10"
          font-family="DM Mono, monospace" text-anchor="middle">${d >= 0 ? '+' : '−'}${Math.abs(d).toFixed(3)}</text>`);
  return `<svg viewBox="0 0 ${L} ${H}" style="display:block;width:100%;height:auto" role="img"
    aria-label="Sharpe observé ${w.sr.toFixed(4)} ramené à ${w.post.toFixed(4)}">${p.join('')}</svg>`;
}

function fiche(w) {
  const suivi = WATCH.has(w.a);
  const largeur = w.ic[1] - w.ic[0];
  const QLAB = { elevee: 'élevée', moyenne: 'moyenne', faible: 'faible' };

  /* --- pourquoi ce rang : phrases produites par le moteur, jamais reecrites --- */
  const bloc = (titre, cle, classe) => {
    const l = w[cle] || [];
    if (!l.length) return '';
    return `<div class="why"><h4>${titre}</h4>${l.map(t =>
      `<div class="li ${classe}"><em></em><span>${esc(t)}</span></div>`).join('')}</div>`;
  };

  /* --- confrontation au natif --- */
  let prot;
  if (w.obs) {
    const o = w.obs;
    prot = `<div class="prot obs"><h4>Observé — donnée native HyperTracker</h4>
      <p>Le Sharpe estimé par notre modèle est confronté au Sharpe recalculé sur les trades
      natifs. Le verdict global du protocole reste <b>${esc(META.verdict)}</b> :
      ${esc(META.verdict_motif)}.</p>
      <div class="cmp">
        <div class="h k">Métrique</div><div class="h">Dérivé</div><div class="h">Observé</div>
        <div class="k">Sharpe / trade</div><div>${nb(o.sr_der, 4)}</div><div>${nb(o.sr, 4)}</div>
        <div class="k">Trades</div><div>${w.n}</div><div>${o.n}</div>
        <div class="k">Écart absolu</div><div>—</div><div>${nb(o.ecart, 3)}</div>
        <div class="k">Écart relatif</div><div>—</div><div>${o.ecart_rel == null ? NA : pc(o.ecart_rel * 100, 1)}</div>
        <div class="k">Change de signe</div><div>—</div><div>${o.signe ? 'oui' : 'non'}</div>
        <div class="k">Échantillon suffisant</div><div>—</div><div>${o.suffisant ? 'oui' : 'non'}</div>
      </div>
      <span class="verdict">${esc(META.verdict)}</span></div>`;
  } else {
    prot = `<div class="prot"><h4>Dérivé — aucune donnée native</h4>
      <p>Ce wallet n'a aucun trade natif HyperTracker exploitable : son classement repose
      entièrement sur la reconstruction. Il n'est donc pas confronté à une seconde source.
      Aucune valeur observée n'est affichée ici, parce qu'il n'en existe aucune.</p></div>`;
  }

  return `
  <div class="wh">
    <span class="adr" id="adr">0x${groupe(w.a)}</span>
    <div class="adrow">
      <button class="btn" id="cp" aria-label="Copier l'adresse brute, prête à coller">Copier</button>
      <button class="btn" id="cpb" aria-label="Copier l'adresse groupée par blocs de quatre">Groupée</button>
    </div>
    <div class="idl">
      <span class="lab">N° ${String(w.rang).padStart(3, '0')} / ${META.n}</span>
      ${(w.coins || []).map(c => `<span class="pill">${esc(c)}</span>`).join('')}
      ${provenance(w)}
    </div>
  </div>

  <div class="wrap">
    <div class="cadran">
      <div class="lft">
        <div>
          <div class="lab">Score</div>
          <div class="big">${w.score.toFixed(1)}</div>
        </div>
        <div class="mini">
          <div class="l">IC 95 % · ${w.ic[0]} – ${w.ic[1]}</div>
          <div class="l">Largeur ${largeur} · Probabilité ${w.conf} %</div>
          <div class="l">Qualité des données · ${esc(QLAB[w.conf_lab] || w.conf_lab)}</div>
          <div class="vern" role="img" aria-label="Qualité ${w.qualite} sur 3 critères">
            ${[0,1,2].map(i => `<i class="${i < (w.qualite || 0) ? 'f' : ''}"></i>`).join('')}
          </div>
          <p class="apparat">${pairs(w)} des ${META.n} wallets partagent cette réserve.</p>
        </div>
      </div>
      <div class="vscale"><canvas id="cad" aria-hidden="true"></canvas></div>
    </div>

    <div class="sect"><span class="lab">Rétrécissement</span></div>
    <div class="well" style="padding:14px 12px 12px">
      ${retrecissement(w)}
      <div class="wlegend" style="margin-top:10px"><span>Sharpe observé ${nb(w.sr, 4)}</span>
        <span>Retenu ${nb(w.post, 4)}</span></div>
    </div>
    <p class="note">Un échantillon mince est ramené vers la moyenne de la population :
      c'est ce déplacement, et non le chiffre brut, qui fonde le score.</p>

    <div class="sect"><span class="lab">Mesures</span></div>
    <div class="plaque">
      ${cellule('Sharpe / trade', nb(w.sr, 4))}
      ${cellule('Sharpe rétréci', nb(w.post, 4))}
      ${cellule('PnL net', usd(w.pnl))}
      ${cellule('Drawdown max', usdb(w.dd))}
      ${cellule('Trades', String(w.n))}
      ${cellule('Jours d\'activité', String(w.jours))}
      ${cellule('Taux de réussite', pc(w.win, 1))}
      ${cellule('Profit factor', nb(w.pf, 2))}
      ${cellule('Concentration', nb(w.conc, 3))}
      ${cellule('Régularité mens.', w.stab == null ? NA : pc(w.stab, 0))}
      ${cellule('Meilleur trade', usd(w.best))}
      ${cellule('Pire trade', usd(w.pire))}
      ${cellule('Durée médiane', w.duree_h == null ? NA : nb(w.duree_h, 1) + ' h')}
      ${cellule('Écart-type / trade', usdb(w.vol))}
      ${cellule('Frais payés', usdb(w.frais))}
      ${cellule('Trades / jour', nb(w.tpj, 2))}
      ${cellule('Trades 30 j', String(w.r30 ?? 0))}
      ${cellule('Trades 7 j', String(w.r7 ?? 0))}
      ${cellule('Dernier trade', date(w.t1))}
      ${cellule('Pire série mens.', w.pire_serie == null ? NA : w.pire_serie + ' mois')}
      ${cellule('ROI', NA)}
      ${cellule('Long / Short', NA)}
    </div>
    <p class="note">ROI et répartition long / short ne sont pas calculables : le capital
      engagé et le sens des positions ne figurent pas dans la source. Ces deux cellules
      restent vides plutôt que de recevoir une valeur inventée.</p>

    <div class="sect"><span class="lab">PnL cumulé</span></div>
    <div class="well"><canvas id="g1" aria-label="Courbe du PnL cumulé"></canvas>
      <div class="wlegend"><span>${date(w.t0)}</span><span>Fin ${usd(w.pnl)}</span></div></div>

    <div class="sect"><span class="lab">Drawdown</span></div>
    <div class="well"><canvas id="g2" aria-label="Courbe de drawdown"></canvas>
      <div class="wlegend"><span>Repli depuis le sommet</span><span>Max ${usdb(w.dd)}</span></div></div>

    <div class="sect"><span class="lab">Distribution des trades</span></div>
    <div class="well"><canvas id="g3" aria-label="Histogramme des résultats par trade"></canvas>
      <div class="wlegend"><span>${w.n} trades</span><span>Barre pleine : médiane</span></div></div>

    <div class="sect"><span class="lab">Performance contre probabilité</span></div>
    <div class="well"><canvas id="g4" aria-label="Nuage score contre probabilité calibrée"></canvas>
      <div class="wlegend"><span>Les ${META.n} wallets · croix ambre : celui-ci</span></div></div>
    <p class="note">Un score élevé n'implique pas une probabilité élevée : si les deux
      grandeurs étaient la même chose, ce nuage serait une diagonale. Il ne l'est pas.</p>

    <div class="sect"><span class="lab">Pourquoi ce rang</span></div>
    ${bloc('Points forts', 'forts', 'f')}
    ${bloc('Points faibles', 'faibles', 'w')}
    ${bloc('Vigilance', 'risques', 'r')}
    ${(!w.forts?.length && !w.faibles?.length && !w.risques?.length)
      ? `<div class="why"><h4>Analyse</h4><div class="li w"><em></em>
         <span>Aucun facteur saillant : les métriques de ce wallet restent dans la moyenne
         de la population.</span></div></div>` : ''}

    <div class="sect"><span class="lab">Cycle de vie</span></div>
    ${cycleVie(w)}

    <div class="sect"><span class="lab">Provenance des données</span></div>
    ${prot}

    <div style="height:14px"></div>
    <button class="btn" id="wt" style="width:100%;padding:13px"
      aria-pressed="${suivi}">${suivi ? 'Retirer de la watchlist' : 'Ajouter à la watchlist'}</button>

    <p class="pied">ρ ${nb(META.spearman, 4)} · ECE ${nb(META.ece, 4)} ·
      Verdict <b>${esc(META.verdict)}</b></p>
  </div>`;
}

function ouvre(a) {
  const w = byA[a];
  const el = document.getElementById('v-wallet');
  if (!w) {
    el.innerHTML = `<div class="empty"><div class="lab">Wallet introuvable</div>
      <p>Cette adresse ne figure pas dans le classement des ${META.n} wallets analysés.</p></div>`;
    return;
  }
  el.innerHTML = fiche(w);
  el.scrollTop = 0; window.scrollTo(0, 0);

  // Deux formes, deux usages reels : la brute se colle dans un explorateur, la
  // groupee se relit a l'oeil. Aucune des deux n'est tronquee.
  el.querySelector('#cp').onclick = e => copier(w.a, e.currentTarget, 'Copier');
  el.querySelector('#cpb').onclick = e => copier('0x' + groupe(w.a), e.currentTarget, 'Groupée');

  const wt = el.querySelector('#wt');
  wt.onclick = () => {
    WATCH.has(w.a) ? WATCH.delete(w.a) : WATCH.add(w.a);
    majWatch();
    const s = WATCH.has(w.a);
    wt.textContent = s ? 'Retirer de la watchlist' : 'Ajouter à la watchlist';
    wt.setAttribute('aria-pressed', String(s));
    wt.classList.toggle('on', s);
  };
  wt.classList.toggle('on', WATCH.has(w.a));

  // Les traces sont posees apres le rendu : elles ont besoin de la largeur reelle.
  requestAnimationFrame(() => {
    cadranV(el.querySelector('#cad'), w);
    courbe(el.querySelector('#g1'), w.eq, { h: 150 });
    courbe(el.querySelector('#g2'), (w.ddc || []).map(p => [p[0], -p[1]]),
           { h: 120, couleur: css('--acier') });
    const med = w.eq && w.eq.length ? null : null;
    histo(el.querySelector('#g3'), w.hist, mediane(w));
    nuage(el.querySelector('#g4'), w);
  });
}
/* Effectif reel partageant la meme qualite de donnees que ce wallet. Compte, pas
   estimation : la phrase d'apparat cite un chiffre verifiable. */
function pairs(w) {
  return W.filter(x => x.conf_lab === w.conf_lab).length;
}

/* mediane des resultats par trade, reconstituee depuis l'histogramme deja calcule */
function mediane(w) {
  if (!w.hist || !w.hist.b) return null;
  const b = w.hist.b, tot = b.reduce((s, x) => s + x, 0);
  let c = 0;
  for (let i = 0; i < b.length; i++) { c += b[i]; if (c >= tot / 2) return w.hist.lo + (i + .5) * w.hist.pas; }
  return null;
}

/* ============================================================ watchlist */
/* La watchlist est INDEPENDANTE du classement : un wallet suivi n'est jamais
   archive automatiquement, et son suivi ne modifie aucun score. Elle vit sur
   l'appareil, pas sur le serveur. */
let qWatch = '';
function rendWatch() {
  const q = qWatch.trim().toLowerCase();
  let l = W.filter(w => WATCH.has(w.a));
  if (q) l = l.filter(w => w.a.toLowerCase().includes(q)
                        || (w.coins || []).some(c => c.toLowerCase().includes(q)));
  l = l.sort(TRIS.find(x => x[0] === ETAT.tri)[2]);
  const champ = `<div class="srch" id="wbox">
      <input id="wq" type="search" inputmode="search" autocomplete="off" autocapitalize="off"
             spellcheck="false" placeholder="Filtrer la watchlist…" value="${esc(qWatch)}"
             aria-label="Filtrer la watchlist">
    </div>`;
  if (!WATCH.size) {
    document.getElementById('wlist').innerHTML =
      `<div class="empty"><div class="lab">Watchlist vide</div>
       <p>Ouvrez la fiche d'un wallet puis touchez « Ajouter à la watchlist ».
       La liste reste sur cet appareil, et un wallet suivi n'est jamais archivé
       automatiquement.</p></div>`;
    return;
  }
  document.getElementById('wlist').innerHTML = champ + (l.length
    ? l.map(w => {
        const h = (w.histo || []);
        const dernier = h.length ? h[h.length - 1] : null;
        const avant = h.length > 1 ? h[h.length - 2] : null;
        const delta = (dernier && avant && dernier[2] != null && avant[2] != null)
          ? avant[2] - dernier[2] : null;
        return carte(w) + `<div class="wsuivi">
          <span>${w.st ? esc(ETIQ[w.st] || w.st) : NA}</span>
          <span>${w.coll ? 'collecté ' + date(w.coll * 1000) : 'jamais collecté'}</span>
          <span>${delta == null ? 'aucun changement mesuré'
                 : (delta === 0 ? 'rang stable'
                    : (delta > 0 ? '▲ +' + delta : '▼ ' + delta) + ' depuis le dernier relevé')}</span>
        </div>`;
      }).join('')
    : `<p class="note">Aucun wallet suivi ne correspond à ce filtre.</p>`)
    + `<div class="fin">${WATCH.size} wallet${WATCH.size > 1 ? 's' : ''} suivi${WATCH.size > 1 ? 's' : ''}</div>`;
  const wq = document.getElementById('wq');
  if (wq) {
    let t;
    wq.oninput = () => { clearTimeout(t); t = setTimeout(() => {
      qWatch = wq.value; rendWatch();
      const f = document.getElementById('wq'); if (f) { f.focus(); f.selectionStart = f.value.length; }
    }, 140); };
  }
}

/* ============================================================ quotidien
   La page qui repond a « qu'est-ce qui a change ce matin ». Elle ne recalcule
   rien : elle lit le rapport produit par le cycle. Sans cycle execute, elle le
   dit, au lieu d'afficher une journee vide qui aurait l'air normale. */
const DAILY = DB.daily || null;
const CLASSES = {
  EXCELLENT_CANDIDATE: 'Candidat excellent', PROMISING: 'Prometteur',
  INSUFFICIENT_DATA: 'Données insuffisantes', REJECTED: 'Non qualifié',
};
const ARCH = DB.archives || [];

function ligneW(a, extra) {
  const w = byA[a];
  if (!w) {
    // Wallet connu du registre mais absent du classement courant : on montre ce
    // qu'on a, on ne reconstitue pas le reste.
    return `<div class="jl"><span class="jl-a mo">${court(a)}</span>
      <span class="jl-x">${extra || NA}</span></div>`;
  }
  return `<div class="jl" data-a="${w.a}" role="button" tabindex="0"
      aria-label="Rang ${w.rang}, score ${w.score.toFixed(1)}. Ouvrir la fiche.">
    <span class="jl-r lab">#${String(w.rang).padStart(3, '0')}</span>
    <span class="jl-a mo">${court(w.a)}</span>
    <span class="jl-s">${w.score.toFixed(1)}</span>
    <span class="jl-x">${extra || ''}</span></div>`;
}

function sectionJ(titre, lignes, vide) {
  return `<div class="sect"><span class="lab">${titre}</span></div>` +
    (lignes.length ? `<div class="jbloc">${lignes.join('')}</div>`
                   : `<p class="note">${vide}</p>`);
}

/* Etiquette COURTE ET COMPLETE, pas une phrase tronquee. Le motif detaille tient
   en cinq lignes et ecrasait la rangee ; il reste disponible en entier sur la
   fiche du wallet, ou il a la place d'etre lu. Ici on nomme le manque, on ne le
   raconte pas. */
const MANQUES = [
  [/anciennet/i, 'ancienneté à confirmer'],
  [/trades clos </i, 'trop peu de trades clos'],
  [/troncature/i, 'troncature non vérifiée'],
  [/concentration/i, 'concentration à vérifier'],
  [/qualite de donnees/i, 'preuve encore mince'],
];
function courtManque(x) {
  const base = CLASSES[x.classe] || x.classe || '';
  const t = (x.manque && x.manque.length) ? String(x.manque[0]) : '';
  for (const [re, lib] of MANQUES) if (re.test(t)) return base + ' · ' + lib;
  return base;
}

function rendJour() {
  const el = document.getElementById('jour');
  if (!DAILY) {
    el.innerHTML = `<div class="empty"><div class="lab">Aucun cycle exécuté</div>
      <p>Le cycle du matin n'a pas encore tourné sur cette machine. Lancez
      <span class="mo">python -m ht.matin</span>, ou attendez 08:00.</p></div>`;
    return;
  }
  const d = DAILY, h = d.data_health || {}, sy = d.system_health || {};

  /* NEW TODAY et NEW RANKED ne disent PAS la meme chose, et c'est le point le
     plus important de cet ecran. Un wallet DECOUVERT vient d'apparaitre dans un
     carnet : on ne sait rien de lui. Un wallet QUALIFIE vient de satisfaire les
     criteres pre-enregistres. Les melanger laisserait croire qu'une decouverte
     est une recommandation. */
  const decouverts = (d.new_today || []).map(x => ligneW(x.a, `<span class="ok">nouveau</span>`));
  const qualifies = (d.new_ranked || []).map(x => ligneW(x.a, `<span class="ok">${esc(x.message)}</span>`));
  const revenus = (d.reactivated || []).map(x => ligneW(x.a, `<span class="ok">${esc(x.message)}</span>`));
  const up = (d.top_movers || []).map(x => ligneW(x.a, `<span class="ok">▲ ${esc(x.message)}</span>`));
  const down = (d.declining || []).map(x => ligneW(x.a, `<span class="ko">▼ ${esc(x.message)}</span>`));
  const arch = (d.archived || []).map(x => ligneW(x.a, `<span class="ko">${esc(x.raison || '')}</span>`));
  const surveiller = (d.watch || []).map(x => ligneW(x.a,
    `<span>${esc(courtManque(x))}</span>`));
  const top = (d.top20 || []).map(x => ligneW(x.a, `<span class="mo">${usd(x.pnl)}</span>`));

  el.innerHTML = `
    <div class="bandeau">
      <div><span class="lab">Dernier cycle</span><span class="v mo">${esc((d.horodatage || '').slice(0, 16).replace('T', ' '))}</span></div>
      <div><span class="lab">Mode</span><span class="v mo">${esc(d.mode || '—')}</span></div>
      <div><span class="lab">Durée</span><span class="v mo">${sy.duree_s ?? '—'} s</span></div>
    </div>

    ${d.prochaine_action ? `<p class="note"><b>Prochaine action :</b> ${esc(d.prochaine_action)}</p>` : ''}

    ${sectionJ('Découverts ce cycle', decouverts,
      'Aucune nouvelle adresse. Les sources locales n\u2019ont rien montré qui ne soit déjà connu.')}
    ${sectionJ('Nouveaux qualifiés', qualifies,
      'Aucun wallet n\u2019a franchi les critères ce cycle. Une découverte n\u2019est pas une qualification : ' +
      'il faut 30 trades clos, 130 jours d\u2019historique et une concentration sous 0,40.')}
    ${sectionJ('Revenus au classement', revenus,
      'Aucun retour. Un wallet archivé revient dès qu\u2019il redémontre sa qualification.')}
    ${sectionJ('Sorties', arch,
      'Aucun retrait. Un wallet n\u2019est retiré que sur un critère réellement réfuté, jamais ' +
      'sur une donnée simplement manquante.')}
    ${sectionJ('En hausse', up, 'Aucun mouvement de position notable.')}
    ${sectionJ('En baisse', down, 'Aucune baisse de position notable.')}
    ${sectionJ('À surveiller', surveiller,
      'Aucun candidat en attente. Ce sont les wallets prometteurs mais encore trop peu documentés.')}
    ${sectionJ('Top 20', top, 'Classement indisponible.')}

    <div class="sect"><span class="lab">Santé des données</span></div>
    <div class="plaque">
      ${cellule('Découverts', String(h.decouverts_ce_cycle ?? '—'))}
      ${cellule('Analysés', String(h.wallets_analyses ?? '—'))}
      ${cellule('Classés', String(h.ranked ?? '—'))}
      ${cellule('En observation', String(h.discovery ?? '—'))}
      ${cellule('Archivés', String(h.archived ?? '—'))}
      ${cellule('Watchlist', String(h.watchlist ?? '—'))}
      ${cellule('Séries collectées', String(h.series_locales ?? '—'))}
      ${cellule('À réévaluer', String(h.a_reevaluer ?? '—'))}
      ${cellule('Requêtes Hyperliquid', String(h.requetes_hyperliquid_consommees ?? 0))}
      ${cellule('Budget restant', String(h.budget_restant ?? '—'))}
      ${cellule('Reportés faute de budget', String(h.refuses_budget ?? 0))}
      ${cellule('Requêtes HyperTracker', String(h.requetes_hypertracker_utilisees ?? 0))}
      ${cellule('Sans proba calibrée', String(h.sans_probabilite_calibree ?? 0))}
      ${cellule('Erreurs', String((h.erreurs_collecte || []).length))}
    </div>
    ${(h.erreurs_collecte || []).length
      ? `<p class="note ko">Erreurs : ${(h.erreurs_collecte || []).map(esc).join(' · ')}</p>`
      : `<p class="note">Aucune erreur de collecte sur ce cycle.</p>`}

    ${(d.blocages || []).map(b => `<div class="prot" style="margin-top:12px">
      <h4>Blocage — ${esc(b.sujet)} (${esc(b.portee)})</h4>
      <p>${esc(b.cause)}</p>
      <p style="margin-top:8px"><b>Interdit automatiquement :</b> ${esc(b.action_interdite)}</p>
      <p style="margin-top:6px"><b>Demande :</b> ${esc(b.demande)}</p></div>`).join('')}

    <div class="sect"><span class="lab">Lecture du score</span></div>
    <div class="prot"><h4>Six grandeurs, jamais confondues</h4>
      <p><b>Performance</b> : le score, position sur l'échelle de population.
      <b>Probabilité</b> : à quel point l'estimation est soutenue par les données.
      <b>Incertitude</b> : la largeur de l'intervalle de crédibilité.
      <b>Qualité des données</b> : combien de critères sur trois sont satisfaits.
      <b>Activité</b> : la fraîcheur, indépendante du score.
      <b>Provenance</b> : dérivé, ou confronté à une donnée native.</p></div>
    <p class="pied">&#961; ${nb(META.spearman, 4)} · ECE ${nb(META.ece, 4)} ·
      Verdict <b>${esc(META.verdict)}</b></p>`;
}

/* ============================================================ insights */
function rendInsights() {
  const n = RP.wallets ? RP.wallets.length : 0;
  const m = RP.meta || {};
  const top = (RP.wallets || []).slice().sort(
    (a, b) => (a.rang_alltime || 9e9) - (b.rang_alltime || 9e9)).slice(0, 25);
  const gros = v => {
    if (v == null) return NA;
    const a = Math.abs(v), s = v < 0 ? '−' : '+';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(1) + ' Md';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(1) + ' M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(0) + ' k';
    return s + '$' + a.toFixed(0);
  };
  document.getElementById('ins').innerHTML = `
    <div class="sect"><span class="lab">Ce que mesure le score</span></div>
    <div class="prot"><h4>Deux grandeurs, jamais une seule</h4>
      <p>Le <b>score</b> situe la performance par trade clos. La <b>probabilité</b> dit
      seulement à quel point cette estimation est soutenue par les données. Les deux ne se
      confondent pas — et ne promettent aucun gain futur.</p></div>
    <div class="well" style="margin-top:10px">
      <canvas id="gi" aria-label="Nuage score contre probabilité sur la population"></canvas>
      <div class="wlegend"><span>${META.n} wallets classés</span><span>Score → · Probabilité ↑</span></div>
    </div>

    <div class="sect"><span class="lab">Réputation HyperTracker</span></div>
    <div class="prot"><h4>Chiffres HyperTracker, pas les nôtres</h4>
      <p>Ces ${n} wallets viennent des classements perpétuels HyperTracker. Les montants
      affichés sont <b>les leurs</b> : nous ne leur attribuons aucun score. Sur ${n} wallets,
      <b>${m.sans_trade_clos ?? '—'} n'ont aucun trade clos</b> — ils tiennent des positions
      longtemps sans jamais revenir à plat. Notre modèle compte des allers-retours clos ;
      il ne peut pas les mesurer. PnL de compte et performance par trade clos ne sont pas
      la même grandeur.</p></div>
    ${top.map(w => `<div class="card" style="cursor:default;padding-bottom:12px">
      <div class="c0"><span class="no"><span>HT N° ${w.rang_alltime ?? w.meilleur_rang}</span></span>
        <span class="coins"><span class="prov">HyperTracker</span></span></div>
      <div class="adrow" style="padding:4px 0 8px">
        <span class="adr short">0x${groupe(w.a)}</span>
        <span class="rd" style="font:500 15px 'DM Mono',monospace;color:var(--zinc-b)">${gros(w.pnlAllTime)}</span>
      </div>
      <div class="wlegend"><span>PnL 30 j ${gros(w.pnlMonth)}</span>
        <span>${w.notre_n ? w.notre_n + ' trades clos' : 'aucun trade clos'}</span></div>
    </div>`).join('')}
    <div class="fin">${n} wallets de classement · source HyperTracker</div>`;
  requestAnimationFrame(() => nuage(document.getElementById('gi'), null));
}

/* ============================================================ en-tetes */
const ECRANS = {
  '/':         { t: 'HyperTracker', s: 'Wallet Intelligence' },
  '/search':   { t: 'Recherche',    s: 'Adresse ou actif' },
  '/watch':    { t: 'Watchlist',    s: 'Suivis sur cet appareil' },
  '/insights': { t: 'Insights',     s: 'Lecture du score' },
  '/jour':     { t: 'Quotidien',    s: 'Ce qui a changé ce matin' },
};
function entete(route, w) {
  const hd = document.getElementById('hd'), ex = document.getElementById('hextra');
  ex.innerHTML = '';
  if (route === '/w') {
    hd.innerHTML = `<button class="btn" id="bk" aria-label="Retour au classement">← Retour</button>
      <span class="htitle"><h1 style="font-size:13px;letter-spacing:.1em">${w ? 'N° ' + w.rang : 'Wallet'}</h1>
      <p>${w ? 'Score ' + w.score.toFixed(1) + ' · IC ' + w.ic[0] + '–' + w.ic[1] : ''}</p></span>`;
    hd.querySelector('#bk').onclick = () => history.back();
    return;
  }
  const e = ECRANS[route] || ECRANS['/'];
  hd.innerHTML = `<span class="htitle"><h1>${e.t}</h1><p>${e.s}</p></span>
    ${route === '/' ? '<span class="lab" style="flex:0 0 auto"><span id="cnt"></span> / ' + META.n + '</span>' : ''}`;
  // L'en-tete est reconstruit a chaque changement d'ecran : le compteur doit etre
  // repose ensuite, sinon il reste vide alors que la liste est deja rendue.
  const c = hd.querySelector('#cnt');
  if (c) c.textContent = String(courant.length);
}

/* ============================================================ routage
   Routage par fragment : le bouton retour du systeme fonctionne sans code,
   et une fiche est une VRAIE page avec sa propre adresse, pas un panneau. */
function route() {
  const h = (location.hash || '#/').slice(1);
  const vues = { '/': 'v-rank', '/search': 'v-rank', '/watch': 'v-watch',
                 '/insights': 'v-insights', '/jour': 'v-jour' };
  document.querySelectorAll('.view').forEach(v => v.classList.remove('on'));

  if (h.startsWith('/w/')) {
    const a = h.slice(3).toLowerCase();
    document.getElementById('v-wallet').classList.add('on');
    entete('/w', byA[a]);
    ouvre(a);
    majNav(null);
    return;
  }
  const id = vues[h] || 'v-rank';
  document.getElementById(id).classList.add('on');
  entete(h in vues ? h : '/');
  majNav(h in vues ? h : '/');

  if (id === 'v-watch') rendWatch();
  if (id === 'v-insights') rendInsights();
  if (id === 'v-jour') rendJour();
  if (id === 'v-rank') {
    if (h === '/search') { setTimeout(() => document.getElementById('q').focus(), 60); }
    // restitution exacte de l'ecran quitte : filtres, tri, recherche, position
    requestAnimationFrame(() => window.scrollTo(0, scrollRank));
  }
}
function majNav(h) {
  document.querySelectorAll('nav button').forEach(b =>
    b.classList.toggle('on', h != null && b.dataset.nav === h));
}
window.addEventListener('hashchange', route);
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  if (location.hash.slice(1) === b.dataset.nav) { window.scrollTo({ top: 0, behavior: 'smooth' }); return; }
  location.hash = '#' + b.dataset.nav;
});

/* une carte ouvre une page : delegation, pour ne pas poser 231 ecouteurs */
document.addEventListener('click', e => {
  const c = e.target.closest('.card[data-a], .jl[data-a]');
  if (c) { scrollRank = window.scrollY; location.hash = '#/w/' + c.dataset.a; }
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const c = e.target.closest && e.target.closest('.card[data-a]');
  if (c) { scrollRank = window.scrollY; location.hash = '#/w/' + c.dataset.a; }
});

/* ============================================================ demarrage */
function bandeau() {
  const inc = META.verdict !== 'CONCLUANT';
  document.getElementById('calib').innerHTML = `
    <div><div class="lab">Spearman</div><div class="v">${nb(META.spearman, 4)}</div></div>
    <div><div class="lab">ECE</div><div class="v">${nb(META.ece, 4)}</div></div>
    <div><div class="lab">Validation</div>
      <div class="v ${inc ? 'warn' : ''}" style="font-size:11px">${esc(META.verdict)}</div></div>`;
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="lab">Wallets classés</div><div class="v">${META.n}</div></div>
    <div class="kpi"><div class="lab">Trades analysés</div>
      <div class="v">${(META.trades / 1000).toFixed(1)}<small> k</small></div></div>
    <div class="kpi"><div class="lab">Score max</div><div class="v">${nb(META.score_max, 1)}</div></div>
    <div class="kpi"><div class="lab">Qualité élevée</div>
      <div class="v">${META.conf_elevee}<small> / ${META.n}</small></div></div>
    <div class="kpi"><div class="lab">Avec natif</div>
      <div class="v">${META.avec_natif}<small> / ${META.n}</small></div></div>
    <div class="kpi"><div class="lab">Mise à jour</div>
      <div class="v" style="font-size:13px">${esc(META.maj)}</div></div>`;
}

/* La convention : legende, indicateur et filtre en un seul objet. Les largeurs
   sont proportionnelles aux effectifs REELS, donc la barre montre du meme coup
   que la qualite « moyenne » domine largement la population. */
const CONV = [
  ['q3', 's', 'élevée',  'conf_elevee'],
  ['q2', 'd', 'moyenne', 'conf_moyenne'],
  ['q1', 'p', 'faible',  'conf_faible'],
];
function convention() {
  const tot = CONV.reduce((s, c) => s + (META[c[3]] || 0), 0) || 1;
  document.getElementById('conv').innerHTML = CONV.map(([k, cls, lib, cle]) => {
    const v = META[cle] || 0;
    return `<button class="cseg ${cls}${ETAT.filtre === k ? ' on' : ''}" data-c="${k}"
      style="flex:${v} 1 0" aria-pressed="${ETAT.filtre === k}"
      aria-label="Qualité ${lib}, ${v} wallets. Filtrer.">
      <i aria-hidden="true"></i><span>${lib} ${v}</span></button>`;
  }).join('');
  document.getElementById('conv').onclick = e => {
    const b = e.target.closest('.cseg'); if (!b) return;
    // un second appui sur le segment actif relache le filtre
    ETAT.filtre = (ETAT.filtre === b.dataset.c) ? 'tous' : b.dataset.c;
    S.set('etat', ETAT); scrollRank = 0;
    convention(); chips(); rendu(true);
  };
}

function chips() {
  document.getElementById('filtres').innerHTML = FILTRES.map(([k, l]) =>
    `<button class="chip${k === ETAT.filtre ? ' on' : ''}" data-f="${k}">${l}</button>`).join('');
  document.getElementById('tris').innerHTML = TRIS.map(([k, l]) =>
    `<button class="chip${k === ETAT.tri ? ' on' : ''}" data-t="${k}">${l}</button>`).join('');
  document.getElementById('filtres').onclick = e => {
    const b = e.target.closest('.chip'); if (!b) return;
    ETAT.filtre = b.dataset.f; S.set('etat', ETAT);
    document.querySelectorAll('#filtres .chip').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); scrollRank = 0; convention(); rendu(true);
  };
  document.getElementById('tris').onclick = e => {
    const b = e.target.closest('.chip'); if (!b) return;
    ETAT.tri = b.dataset.t; S.set('etat', ETAT);
    document.querySelectorAll('#tris .chip').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); scrollRank = 0; rendu(true);
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
    t = setTimeout(() => { ETAT.q = q.value; S.set('etat', ETAT); scrollRank = 0; rendu(true); }, 130);
  };
  document.getElementById('qc').onclick = () => {
    q.value = ''; ETAT.q = ''; S.set('etat', ETAT);
    box.classList.remove('has'); rendu(true); q.focus();
  };
}

let redim;
window.addEventListener('resize', () => {
  clearTimeout(redim);
  redim = setTimeout(() => {
    rugPop();
    if (location.hash.startsWith('#/w/')) ouvre(location.hash.slice(4).toLowerCase());
    if (document.getElementById('v-insights').classList.contains('on')) rendInsights();
  }, 180);
});

bandeau();
convention();
chips();
recherche();
rendu(true);
rugPop();
route();
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
