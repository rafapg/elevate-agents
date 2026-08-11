"""Read-only, deterministic access to the Aula 12 synthetic incident packet."""

from .gateway import FixtureGateway
from .reader import FixtureEvidence, FixtureReader, FixtureValidationError

__all__ = ["FixtureEvidence", "FixtureGateway", "FixtureReader", "FixtureValidationError"]
