"""
Integration package for the Secure AI Executive Assistant.

Provides factory functions for assembling fully-wired component graphs
for both production use and integration testing.
"""

from src.integration.factory import create_orchestrator

__all__ = ["create_orchestrator"]
