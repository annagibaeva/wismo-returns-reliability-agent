"""Grounding gate: verifies a proposed return ruling against the KB + facts.

It is a VERIFIER, not a solver — it can BLOCK a ruling (→ handoff) but never
hands the agent a free answer. Blocks are tagged by category so the scorer can
separate the two failure types the project measures:
  - grounding  -> hallucination class (fabricated rule / condition didn't hold / no citation)
  - conclusion -> policy_error class  (precedence miss / wrong conclusion / deadlock / no covering rule)
"""
from .gate import assess, GateResult  # noqa: F401
