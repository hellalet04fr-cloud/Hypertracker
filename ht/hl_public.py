#!/usr/bin/env python3
"""
Client de l'API PUBLIQUE Hyperliquid (https://api.hyperliquid.xyz/info).

Gratuite, non authentifiee, sans rapport avec le quota HyperTracker. Ce module ne
doit JAMAIS appeler ht-api.coinmarketman.com — la separation est le point du dispositif.

Limitation de debit : Hyperliquid applique un budget de poids par IP (de l'ordre de
1200/minute, `userFills` pesant 20, soit ~60 requetes/minute au plafond theorique).
On se tient volontairement en dessous : rien ne presse ici, et se faire bannir une IP
couterait bien plus que quelques secondes d'attente.

Profondeur : l'API n'expose que les ~10 000 derniers fills par wallet, avec 2000 par
reponse. Ce n'est PAS une fenetre temporelle. La profondeur en jours est donc
inversement proportionnelle a l'activite du wallet — mesure : 304 jours pour un wallet
a 3 fills/jour, environ 2 heures pour un wallet a 32 000 fills/jour.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .schema import InsufficientData

BASE = "https://api.hyperliquid.xyz/info"

# Plafond conservateur : la moitie du debit theorique.
REQUETES_PAR_MINUTE = 30
MAX_FILLS_PAR_REPONSE = 2000
MAX_FUNDING_PAR_REPONSE = 500   # plafond serveur mesure sur userFunding
# Budget de pages PROPRE au funding. Le funding est horaire ET par coin : un wallet
# multi-coins sur 90 jours depasse largement les 8 pages des fills. Mesure : un wallet
# rendait exactement 4000 evenements, soit 8 x 500 — donc tronque, ce qui laissait
# 18 trades sans aucun paiement dans leur fenetre alors qu'un perp ouvert 18 h en
# recoit forcement. La boucle sort d'elle-meme des qu'une page est incomplete ou que
# la fenetre est couverte : ce plafond n'est qu'un garde-fou, pas une cible.
PAGES_MAX_FUNDING = 60
PAGES_MAX = 8               # 8 x 2000 = 16 000, au-dela du plafond serveur de ~10 000


class LimiteDebit:
    """Seau a jetons simple, partage entre threads."""

    def __init__(self, par_minute: int = REQUETES_PAR_MINUTE):
        self.intervalle = 60.0 / max(1, par_minute)
        self._lock = threading.Lock()
        self._prochain = 0.0

    def attendre(self) -> None:
        with self._lock:
            maintenant = time.monotonic()
            if maintenant < self._prochain:
                time.sleep(self._prochain - maintenant)
                maintenant = time.monotonic()
            self._prochain = maintenant + self.intervalle


_limite = LimiteDebit()


@dataclass
class Stats:
    requetes: int = 0
    fills: int = 0
    erreurs: int = 0
    secondes: float = 0.0
    par_wallet: dict = field(default_factory=dict)


STATS = Stats()


def _post(corps: dict[str, Any], *, timeout: float = 60.0, tentatives: int = 3) -> Any:
    """POST avec limitation de debit et back-off borne. Aucun retry agressif."""
    dernier = None
    for essai in range(tentatives):
        _limite.attendre()
        req = urllib.request.Request(
            BASE, data=json.dumps(corps).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                brut = r.read()
            STATS.requetes += 1
            STATS.secondes += time.monotonic() - t0
            return json.loads(brut)
        except urllib.error.HTTPError as e:
            dernier = f"HTTP {e.code}"
            STATS.erreurs += 1
            if e.code == 429:
                time.sleep(min(30.0, 2.0 * (2 ** essai)))
                continue
            if 500 <= e.code < 600:
                time.sleep(min(10.0, 2 ** essai))
                continue
            raise InsufficientData(f"Hyperliquid {corps.get('type')} -> HTTP {e.code}")
        except Exception as e:
            dernier = f"{type(e).__name__}: {e}"
            STATS.erreurs += 1
            time.sleep(min(10.0, 2 ** essai))
    raise InsufficientData(
        f"Hyperliquid {corps.get('type')} injoignable apres {tentatives} tentatives "
        f"({dernier})"
    )


def _valide_adresse(address: str) -> str:
    a = (address or "").strip()
    if not (a.startswith("0x") and len(a) == 42):
        raise InsufficientData(
            f"adresse EVM invalide: {a[:12]!r} (42 caracteres attendus). "
            "La pseudo-adresse TWAP a 64 chiffres hexadecimaux n'est pas un wallet."
        )
    return a.lower()


def user_fills(address: str, *, poster=None) -> list[dict]:
    """Les fills les plus recents (plafond serveur 2000)."""
    a = _valide_adresse(address)
    p = poster or _post
    r = p({"type": "userFills", "user": a})
    return list(r) if isinstance(r, list) else []


def user_fills_by_time(address: str, *, start_ms: int = 0, end_ms: int | None = None,
                       pages_max: int = PAGES_MAX, poster=None) -> list[dict]:
    """
    Tous les fills accessibles pour une adresse dans la fenetre [start_ms, end_ms].

    SENS DE PAGINATION — le point qui a coute une journee de validation. Le serveur
    rend les fills les PLUS ANCIENS de la plage demandee, pas les plus recents :
    verifie sur les donnees collectees, un wallet plafonne a 2000 fills voyait sa
    couverture s'arreter des mois avant aujourd'hui, tandis qu'un wallet a 488 fills
    (sous le plafond) remontait bien jusqu'au jour meme.

    La pagination doit donc AVANCER `startTime` au-dela du fill le plus recent recu.
    L'ancienne version reculait `endTime`, ce qui s'eloignait du present a chaque page
    et rendait tout recouvrement avec des donnees recentes impossible.
    """
    a = _valide_adresse(address)
    p = poster or _post
    fin = end_ms if end_ms is not None else int(time.time() * 1000)
    debut = int(start_ms)
    vus: dict[Any, dict] = {}
    for _ in range(max(1, pages_max)):
        lot = p({"type": "userFillsByTime", "user": a,
                 "startTime": debut, "endTime": int(fin)})
        if not isinstance(lot, list) or not lot:
            break
        avant = len(vus)
        for f in lot:
            # `tid` identifie un fill de facon unique ; il sert de cle de deduplication
            # entre pages, dont les bornes se chevauchent d'une milliseconde.
            vus[f.get("tid", (f.get("time"), f.get("oid"), f.get("sz")))] = f
        if len(vus) == avant:
            break                                   # page entierement redondante
        if len(lot) < MAX_FILLS_PAR_REPONSE:
            break                                   # derniere page
        plus_recent = max(int(f["time"]) for f in lot)
        if plus_recent >= fin:
            break
        debut = plus_recent + 1
    fills = sorted(vus.values(), key=lambda f: (int(f["time"]), f.get("tid") or 0))
    STATS.fills += len(fills)
    STATS.par_wallet[a] = len(fills)
    return fills


def user_funding(address: str, *, start_ms: int = 0, end_ms: int | None = None,
                 pages_max: int = PAGES_MAX_FUNDING, poster=None) -> list[dict]:
    """
    Paiements de funding d'un wallet.

    Forme constatee : {"time": ms, "hash": "0x…",
                       "delta": {"type": "funding", "coin": "BTC", "usdc": "-0.0349",
                                 "szi": "0.0258", "fundingRate": "0.0000125",
                                 "nSamples": 1}}

    `usdc` porte le SIGNE du point de vue du wallet : negatif = funding paye, positif =
    funding recu. C'est ce qui permet de le sommer directement sans deviner le sens.

    MEME PLAFOND, MEME SENS que `userFillsByTime`, et le meme piege. La reponse est
    bornee a 500 evenements et le serveur rend les PLUS ANCIENS de la plage. Sans
    pagination, interroger 90 jours ne rendait que les tout premiers jours : mesure sur
    5 wallets, 4,4 % seulement du funding reellement paye etait capte (-3,74 USD
    rapportes contre -84,73 constates cote natif), ce qui suffisait a faire echouer la
    concordance de PnL du gate de segmentation.
    """
    a = _valide_adresse(address)
    p = poster or _post
    fin = end_ms if end_ms is not None else int(time.time() * 1000)
    debut = int(start_ms)
    vus: dict[Any, dict] = {}
    for _ in range(max(1, pages_max)):
        lot = p({"type": "userFunding", "user": a,
                 "startTime": debut, "endTime": int(fin)})
        if not isinstance(lot, list) or not lot:
            break
        avant = len(vus)
        for e in lot:
            d = e.get("delta") or {}
            # un wallet recoit au plus un paiement par coin et par horodatage :
            # (time, coin) est donc une cle de deduplication sure entre pages.
            vus[(e.get("time"), d.get("coin"))] = e
        if len(vus) == avant:
            break
        if len(lot) < MAX_FUNDING_PAR_REPONSE:
            break
        plus_recent = max(int(e["time"]) for e in lot)
        if plus_recent >= fin:
            break
        debut = plus_recent + 1
    return sorted(vus.values(), key=lambda e: int(e.get("time") or 0))


def meta_and_asset_ctxs(*, poster=None) -> Any:
    """Contexte des actifs perp (volume 24 h, open interest, prix). Sert au contexte
    de marche, pas a la reconstruction."""
    return (poster or _post)({"type": "metaAndAssetCtxs"})


def reinit_stats() -> None:
    global STATS
    STATS = Stats()
