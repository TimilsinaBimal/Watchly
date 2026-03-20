"""Compatibility wrapper for the profile service.

New code should import from `app.services.profile.service`.
"""

from app.services.profile.service import ProfileIntegration, ProfileService

__all__ = ["ProfileService", "ProfileIntegration"]
