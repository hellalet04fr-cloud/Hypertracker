"""
Contrat de données — source unique de vérité pour tous les moteurs.

Chaque schéma est marqué OBSERVED (constaté sur une réponse réelle) ou DOCUMENTED
(annoncé par la doc, jamais encore vu). Aucun moteur ne doit calculer sur un champ
DOCUMENTED sans avoir vérifié sa présence à l'exécution : la doc s'est déjà révélée
fausse (address « optionnel » sur /fills est en réalité obligatoire).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --------------------------------------------------------------------------- statuts
OBSERVED = "OBSERVED"        # constate sur une reponse reelle de l'API HyperTracker
DOCUMENTED = "DOCUMENTED"    # annonce par la doc, jamais encore vu
DERIVED = "DERIVED"          # RECONSTRUIT par nous depuis une autre source publique.
#                              Jamais interchangeable avec OBSERVED : une donnee derivee
#                              porte les erreurs de notre reconstruction en plus de
#                              celles de la source.


@dataclass(frozen=True)
class Source:
    name: str
    status: str
    columns: tuple[str, ...]
    key: tuple[str, ...]
    valid_time: str | None          # colonne portant l'instant où le fait était vrai
    notes: str = ""
    post_hoc: frozenset[str] = field(default_factory=frozenset)  # champs contaminés par le futur


# --------------------------------------------------------------------------- sources
ORDERS_5M = Source(
    name="orders_5m", status=OBSERVED,
    columns=("snapshotTime", "timestamp", "height", "address", "coin", "side", "limitPx",
             "sz", "oid", "triggerCondition", "isTrigger", "triggerPx", "children",
             "isPositionTpsl", "reduceOnly", "orderType", "origSz", "tif", "cloid",
             "status", "builder", "builderFee", "untriggered"),
    key=("snapshotTime", "oid"),
    valid_time="snapshotTime",
    notes="355k ordres/snapshot, 308 actifs. snapshotTime/height/status/builder/builderFee "
          "sont constants dans un snapshot donné.",
)

WALLETS = Source(
    name="wallets", status=OBSERVED,
    columns=("address", "xUserId", "displayName", "emoji", "verified", "segments",
             "favoriteCount", "totalEquity", "earliestActivityAt", "perpPnl", "perpEquity",
             "exposureRatio", "perpBias", "openValue", "sumUpnl", "vault", "closestLiq",
             "observed_at"),
    key=("address", "observed_at"),
    valid_time="observed_at",
    notes="totalCount=296781. AUCUN champ asOf côté API : l'instant de capture est "
          "estampillé par nous. segments = [cohorte_taille, cohorte_perf], recalculées "
          "toutes les 3-4h en amont, donc à figer à l'ingestion.",
)

SEGMENTS = Source(
    name="segments", status=OBSERVED,
    columns=("id", "name", "category", "criteria", "emoji", "observed_at"),
    key=("id", "observed_at"), valid_time="observed_at",
    notes="16 cohortes : 8 par perp equity, 8 par PnL perp all-time.",
)

CLOSED_TRADES = Source(
    name="closed_trades", status=DOCUMENTED,
    columns=("address", "coin", "side", "hash", "realizedPnlUsd", "avgEntry", "avgExit",
             "openTime", "closeTime", "duration", "fee", "feeUsd", "fundingUsd",
             "countFills", "partial"),
    key=("hash",), valid_time="closeTime",
    notes="address OBLIGATOIRE, fenêtre max 30 jours/requête, historique depuis juillet 2025. "
          "Ni version ni updatedAt : la dérive d'étiquettes est indétectable sans re-tirage.",
    post_hoc=frozenset({"partial"}),
)

FILLS = Source(
    name="fills", status=OBSERVED,
    columns=("address", "coin", "side", "px", "sz", "time", "oid", "fee", "closedPnl"),
    key=("oid", "time"), valid_time="time",
    notes="address OBLIGATOIRE (tableau de 1 à 10) — la doc le donnait pour optionnel, "
          "c'est FAUX. Un seul jour calendaire par requête. Pas d'accès exchange-wide.",
)

LEADERBOARDS = Source(
    name="leaderboards", status=DOCUMENTED,
    columns=("address", "pnlDay", "pnlWeek", "pnlMonth", "pnlAllTime", "_rank", "_rankBy", "observed_at"),
    key=("address", "_rankBy", "observed_at"), valid_time="observed_at",
    notes="AUCUN paramètre as-of, aucun historique. Non reconstituable : ce qui n'est pas "
          "capturé aujourd'hui est perdu. Sélectionne mécaniquement les survivants.",
)

RECONSTRUCTED_CLOSED_TRADES = Source(
    name="reconstructed_closed_trades", status=DERIVED,
    columns=("address", "coin", "side", "trade_id", "realizedPnlUsd", "avgEntry",
             "avgExit", "openTime", "closeTime", "duration", "feeUsd", "countFills",
             "source", "classification", "tronque", "position_ouverte",
             "n_fills_ouverture", "n_fills_fermeture"),
    key=("trade_id",), valid_time="closeTime",
    notes="RECONSTRUIT depuis l'API PUBLIQUE Hyperliquid (userFillsByTime), pas obtenu "
          "de HyperTracker. Hyperliquid n'expose que les ~10 000 derniers fills par "
          "wallet : la profondeur est donc inversement proportionnelle a l'activite "
          "(304 jours pour 3 fills/jour, ~2 heures pour 32 000 fills/jour). "
          "fundingUsd est ABSENT des fills et n'est donc pas reconstruit. "
          "INTERDIT pour un classement definitif ; autorise pour developpement, tests, "
          "exploration, variables, comportement, simulation et comparaison.",
    post_hoc=frozenset({"position_ouverte"}),
)

SOURCES = {s.name: s for s in (ORDERS_5M, WALLETS, SEGMENTS, CLOSED_TRADES, FILLS,
                               LEADERBOARDS, RECONSTRUCTED_CLOSED_TRADES)}

# Seules ces sources peuvent alimenter un classement DEFINITIF. La liste est ici,
# en un seul endroit, pour qu'aucun appelant ne puisse l'elargir par inadvertance.
SOURCES_POUR_CLASSEMENT_DEFINITIF = frozenset({CLOSED_TRADES.name})


def est_derive(source_name: str) -> bool:
    s = SOURCES.get(source_name)
    return bool(s and s.status == DERIVED)


# --------------------------------------------------------------------------- les trois horloges
@dataclass(frozen=True)
class Clocks:
    """
    valid_time   : quand le fait était vrai dans le monde.
    knowable_at  : premier instant où l'API aurait pu le servir. SEUL axe qui borne un backtest.
    ingest_time  : quand nous avons récupéré les octets. Provenance et audit uniquement.
    """
    valid_time: datetime
    knowable_at: datetime
    ingest_time: datetime

    def __post_init__(self):
        for f in ("valid_time", "knowable_at", "ingest_time"):
            v = getattr(self, f)
            if v.tzinfo is None:
                raise ValueError(f"{f} doit être timezone-aware (UTC)")


def knowable_at_for(source: str, valid_time: datetime, publication_lag_s: float | None = None) -> datetime:
    """
    Latence de publication. Défauts prudents tant qu'elle n'est pas mesurée sur le flux
    courant : mieux vaut surestimer (donc exclure des données) que sous-estimer (donc fuiter).
    """
    from datetime import timedelta
    if publication_lag_s is not None:
        return valid_time + timedelta(seconds=publication_lag_s)
    defaults = {
        "orders_5m": 300.0,        # borne de 5 min + traitement ; à mesurer
        "wallets": 1200.0,         # état amont rafraîchi toutes les 15-20 min
        "segments": 1200.0,
        "closed_trades": 10.0,     # « fill catcher » ~10 s selon la doc
        "fills": 2.0,
        "leaderboards": 1200.0,
    }
    return valid_time + timedelta(seconds=defaults.get(source, 1200.0))


class InsufficientData(Exception):
    """Levée dès qu'un calcul manquerait de données réelles. Ne JAMAIS retourner
    une valeur par défaut à la place : un résultat fabriqué est pire qu'une erreur."""


def require(condition: bool, msg: str):
    if not condition:
        raise InsufficientData(msg)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
