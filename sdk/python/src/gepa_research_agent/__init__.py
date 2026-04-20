"""gepa-research-agent: Lightweight reporting SDK for GEPAResearch experiments (import as gepa_research_agent)."""

from ._backend import Backend, LocalBackend
from ._gate import Gate
from ._run import Run

__all__ = ["Backend", "Gate", "LocalBackend", "Run"]
__version__ = "0.1.0"
