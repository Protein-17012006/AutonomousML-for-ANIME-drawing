"""Compatibility facade for state values moved to :mod:`inbetween_copilot.domain`.

New code must import from ``inbetween_copilot.domain.states``.  This module keeps
the historical public path stable for service consumers during migration.
"""

from inbetween_copilot.domain.states import (
    CorrectionStatus,
    PairAction,
    PlanAction,
    QAStatus,
    Route,
)

__all__ = ["CorrectionStatus", "PairAction", "PlanAction", "QAStatus", "Route"]
