"""Règlement fictif d'un pari à partir du score final. Aucune exécution réelle."""
from __future__ import annotations


def settle(market: str, selection: str, line: float | None, rule: str, hs: int, as_: int) -> str:
    """Retourne 'win' | 'loss' | 'push'.

    1x2          : temps réglementaire, trois issues (home/draw/away).
    moneyline    : 2 issues ; nul -> remboursé si rule='tie_refund', perdant si 'tie_loss'/'standard'.
    total        : score cumulé vs ligne ; égalité (ligne entière) -> push.
    spread       : handicap `line` appliqué à la sélection ; égalité -> push.
    """
    m = hs - as_
    if market == "1x2":
        res = "home" if m > 0 else "away" if m < 0 else "draw"
        return "win" if selection == res else "loss"
    if market == "moneyline":
        if m == 0:
            return "push" if rule == "tie_refund" else "loss"
        return "win" if (m > 0) == (selection == "home") else "loss"
    if market == "total":
        d = (hs + as_) - float(line)
        if d == 0:
            return "push"
        return "win" if (d > 0) == (selection == "over") else "loss"
    if market == "spread":
        adj = (m if selection == "home" else -m) + float(line)
        return "push" if adj == 0 else "win" if adj > 0 else "loss"
    raise ValueError(f"marché inconnu : {market}")


def profit_units(outcome: str, odds: float, stake: float = 1.0) -> float:
    """Profit net en unités : gain = mise*(cote-1), perte = -mise, remboursement = 0."""
    return {"win": stake * (odds - 1.0), "loss": -stake, "push": 0.0}[outcome]
