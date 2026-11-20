"""Hierarchie d'erreurs du projet.

Regle : toute erreur remontee par le framework derive de :class:`AgentError` et
porte un ``hint`` actionnable. Les erreurs destinees a etre reessayees
(:class:`RetryableProviderError`) sont isolees pour que la couche de retry ne
reessaye jamais une erreur de programmation.
"""

from __future__ import annotations


class AgentError(Exception):
    """Erreur de base du framework."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.message} (hint: {self.hint})" if self.hint else self.message


class ProviderError(AgentError):
    """Le fournisseur LLM a renvoye une reponse inutilisable."""


class RetryableProviderError(ProviderError):
    """Erreur transitoire du fournisseur (429, 5xx, timeout reseau)."""


class BudgetExceeded(AgentError):
    """Le budget de tokens, d'appels ou de temps est epuise."""


class ToolError(AgentError):
    """Un outil a echoue pendant son execution."""


class ToolValidationError(ToolError):
    """Les arguments fournis a un outil ne respectent pas son schema."""


class PlanningError(AgentError):
    """Le plan produit est invalide (identifiants, dependances, cycle)."""


class PolicyError(AgentError):
    """Une action est refusee par la politique de securite (sandbox, chemin, taille)."""
