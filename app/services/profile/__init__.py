"""
Profile System - Additive, Transparent Design.

This package implements a transparent, additive user profile system.
No hidden interactions, easy to debug, powerful enough for all row types.
"""

from app.services.profile.builder import ProfileBuilder
from app.services.profile.evidence import EvidenceCalculator
from app.services.profile.integration import ProfileIntegration
from app.services.profile.sampling import SmartSampler
from app.services.profile.scorer import ProfileScorer
from app.services.profile.vectorizer import ItemVectorizer

__all__ = [
    "ProfileBuilder",
    "ProfileScorer",
    "EvidenceCalculator",
    "ItemVectorizer",
    "SmartSampler",
    "ProfileIntegration",
]
