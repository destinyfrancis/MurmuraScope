"""OASIS compatibility check.

This module validates if the environment can run the OASIS simulation engine.
OASIS currently has a hard requirement on Python 3.10/3.11. If the user is running
the backend on Python 3.12+ (e.g. locally without Docker), this module will detect
the failure and gracefully degrade the UI capabilities rather than crashing.
"""

import sys
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("oasis_compatibility")

SIMULATION_ENGINE_AVAILABLE: bool = True

def check_oasis_compatibility() -> None:
    """Check if the current environment can import and run OASIS."""
    global SIMULATION_ENGINE_AVAILABLE
    
    # 1. Check Python version
    major, minor = sys.version_info[:2]
    if major == 3 and minor > 11:
        logger.warning(
            "Python %s.%s detected. OASIS simulation engine requires Python 3.10 or 3.11. "
            "Simulation features will be disabled. Use Docker for full functionality.",
            major, minor
        )
        SIMULATION_ENGINE_AVAILABLE = False
        return

    # 2. Check if OASIS is importable
    try:
        import importlib.util
        if importlib.util.find_spec('oasis') is None:
            # Maybe the submodules are not available
            logger.warning("OASIS framework could not be found.")
            # Note: We won't strictly disable it here to avoid false negatives
            # if they just haven't pip installed everything but want to use the 
            # binary runner we built in L5.
    except Exception as e:
        logger.warning("OASIS compatibility check failed: %s", e)
        # We don't disable for generic import errors just in case, only on known version constraint

def get_capabilities() -> dict[str, Any]:
    """Return backend capabilities for the frontend."""
    return {
        "simulation": SIMULATION_ENGINE_AVAILABLE,
        "kg_generation": True, # Always available
        "report_generation": True, # LLM-based, Python independent
    }

# Run the check on import
check_oasis_compatibility()
