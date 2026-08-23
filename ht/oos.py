#!/usr/bin/env python3
"""
Decoupage hors echantillon strict : train -> calibration -> test.

Trois exigences, chacune verifiee et non negociable :

1. ORDRE TEMPOREL. train precede calibration qui precede test. Un decoupage
   aleatoire melangerait passe et futur ; sur des donnees de marche c'est la fuite
   la plus banale et la plus destructrice.

2. PURGE ET EMBARGO ENTRE CHAQUE BLOC. Un trade ouvert avant une frontiere et clos
   apres appartient aux deux cotes. La purge retire ces chevauchants ; l'embargo
   ecarte en plus une bande de securite apres la frontiere, parce que l'information
   d'un trade se propage au-dela de sa cloture.

3. DISJONCTION VERIFIEE, pas supposee. Les trois blocs sont compares par identifiant :
   une intersection, meme d'un seul trade, invalide la mesure et leve.

Le module ne produit AUCUNE probabilite : il decoupe. Le calcul d'ECE reste dans
ht.gate.ece_certifiee, qui refusera de toute facon toute classification non OBSERVED.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from .schema import OBSERVED, InsufficientData, require

MIN_PAR_BLOC = 50            # aligne sur ht.calibration.MIN_OBS_CALIBRATION
PURGE_DEFAUT = timedelta(days=1)
EMBARGO_DEFAUT = timedelta(days=1)


@dataclass(frozen=True)
class Bloc:
    nom: str
    debut: datetime
    fin: datetime
    indices: tuple[int, ...]
    n: int

    def as_dict(self) -> dict:
        d = asdict(self)
        d["debut"] = self.debut.isoformat()
        d["fin"] = self.fin.isoformat()
        d["indices"] = list(self.indices)
        return d


@dataclass
class DecoupageTemporel:
    train: Bloc
    calibration: Bloc
    test: Bloc
    n_purges: int
    n_total: int
    classification: str

    @property
    def blocs(self) -> tuple[Bloc, Bloc, Bloc]:
        return (self.train, self.calibration, self.test)

    def resume(self) -> str:
        l = [f"decoupage OOS ({self.classification}) — {self.n_total} trades, "
             f"{self.n_purges} purges"]
        for b in self.blocs:
            l.append(f"  {b.nom:<12} {b.debut:%Y-%m-%d} -> {b.fin:%Y-%m-%d}  n={b.n}")
        return "\n".join(l)

    def as_dict(self) -> dict:
        return {"train": self.train.as_dict(), "calibration": self.calibration.as_dict(),
                "test": self.test.as_dict(), "n_purges": self.n_purges,
                "n_total": self.n_total, "classification": self.classification}


def _ms(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def decouper(trades: Sequence[Mapping[str, Any]],
             *,
             classification: str,
             parts: tuple[float, float, float] = (0.5, 0.25, 0.25),
             purge: timedelta = PURGE_DEFAUT,
             embargo: timedelta = EMBARGO_DEFAUT,
             min_par_bloc: int = MIN_PAR_BLOC) -> DecoupageTemporel:
    """
    Decoupe une liste de trades clos en trois blocs temporels disjoints.

    `classification` est exige explicitement : le decoupage ne devine jamais l'origine
    des donnees. Il accepte DERIVED pour permettre les repetitions a blanc, mais
    l'ECE en aval refusera tout ce qui n'est pas OBSERVED — le verrou est la, une
    seule fois, et pas duplique ici.
    """
    require(abs(sum(parts) - 1.0) < 1e-9, f"les parts doivent sommer a 1 (recu {sum(parts)})")
    require(all(p > 0 for p in parts), "chaque part doit etre strictement positive")
    require(purge >= timedelta(0) and embargo >= timedelta(0),
            "purge et embargo doivent etre positifs ou nuls")

    enrichis = []
    for i, t in enumerate(trades):
        o, c = _ms(t.get("openTime")), _ms(t.get("closeTime"))
        if o is None or c is None or c < o:
            continue
        enrichis.append((i, o, c))
    n = len(enrichis)
    require(n >= 3 * min_par_bloc,
            f"{n} trades exploitables, il en faut au moins {3 * min_par_bloc} "
            f"({min_par_bloc} par bloc)")

    enrichis.sort(key=lambda x: x[2])                 # tri sur la CLOTURE
    i1 = int(n * parts[0])
    i2 = i1 + int(n * parts[1])
    f1 = enrichis[i1 - 1][2]                          # frontiere train/calibration
    f2 = enrichis[i2 - 1][2]                          # frontiere calibration/test
    p_ms = int(purge.total_seconds() * 1000)
    e_ms = int(embargo.total_seconds() * 1000)

    def bloc(nom, lo, hi, exclure_avant=None):
        idx = []
        for i, o, c in enrichis:
            if not (lo <= c <= hi):
                continue
            # purge : un trade ouvert avant la frontiere basse chevauche le bloc precedent
            if exclure_avant is not None and o < exclure_avant:
                continue
            idx.append(i)
        return idx

    i_train = bloc("train", enrichis[0][2], f1 - p_ms)
    i_cal = bloc("calibration", f1 + e_ms, f2 - p_ms, exclure_avant=f1)
    i_test = bloc("test", f2 + e_ms, enrichis[-1][2], exclure_avant=f2)

    for nom, idx in (("train", i_train), ("calibration", i_cal), ("test", i_test)):
        require(len(idx) >= min_par_bloc,
                f"bloc '{nom}' : {len(idx)}/{min_par_bloc} trades apres purge et embargo")

    # Disjonction VERIFIEE, jamais supposee.
    s_tr, s_ca, s_te = set(i_train), set(i_cal), set(i_test)
    if (s_tr & s_ca) or (s_ca & s_te) or (s_tr & s_te):
        raise InsufficientData("les blocs se recouvrent : decoupage invalide")

    dt = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc)
    faire = lambda nom, idx: Bloc(
        nom=nom, debut=dt(min(enrichis[k][2] for k in range(len(enrichis))
                              if enrichis[k][0] in set(idx))),
        fin=dt(max(enrichis[k][2] for k in range(len(enrichis))
                   if enrichis[k][0] in set(idx))),
        indices=tuple(idx), n=len(idx))

    train, cal, test = (faire("train", i_train), faire("calibration", i_cal),
                        faire("test", i_test))
    if not (train.fin <= cal.debut and cal.fin <= test.debut):
        raise InsufficientData("l'ordre temporel train < calibration < test est rompu")

    return DecoupageTemporel(train=train, calibration=cal, test=test,
                             n_purges=n - (train.n + cal.n + test.n),
                             n_total=n, classification=classification)


def vers_decoupage_oos(dec: DecoupageTemporel,
                       trades: Sequence[Mapping[str, Any]],
                       probabilites: Sequence[float]):
    """
    Convertit un decoupage temporel en `gate.DecoupageOOS` (couples y, p).

    `probabilites` doit etre alignee sur `trades`. L'issue binaire est « PnL net
    strictement positif » ; on lit `realizedPnlNetUsd` en priorite pour ne pas
    redefinir la convention etablie par RECON_V2.
    """
    from .gate import DecoupageOOS

    require(len(probabilites) == len(trades),
            f"{len(probabilites)} probabilites pour {len(trades)} trades")

    def yp(indices):
        y, p = [], []
        for i in indices:
            t = trades[i]
            v = t.get("realizedPnlNetUsd")
            if v is None:
                v = t.get("realizedPnlUsd")
            if v is None:
                continue
            pr = float(probabilites[i])
            if not (0.0 <= pr <= 1.0):
                raise InsufficientData(f"probabilite hors [0,1] a l'indice {i}: {pr}")
            y.append(1.0 if float(v) > 0 else 0.0)
            p.append(pr)
        return (y, p)

    return DecoupageOOS(train=yp(dec.train.indices),
                        calibration=yp(dec.calibration.indices),
                        test=yp(dec.test.indices))
