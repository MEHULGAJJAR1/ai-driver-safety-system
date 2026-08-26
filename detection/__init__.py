"""Detection engine for the Driver Drowsiness Detection Dashboard.

Modules
-------
landmarks   : MediaPipe FaceMesh wrapper -> EAR, MAR, head pose.
cnn_model   : Optional Keras CNN eye-state (open/closed) classifier.
drowsiness  : Combines the above into a drowsiness score + state machine.
sunglasses  : Lightweight CV sunglasses / dark-glasses detector.
alerts      : SideLook + FaceCoverage detectors and the central AlertManager.
"""

from .landmarks import LandmarkDetector          # noqa: F401
from .drowsiness import DrowsinessPipeline, DrowsinessScorer  # noqa: F401
from .sunglasses import SunglassesDetector       # noqa: F401
from .alerts import (                            # noqa: F401
    AlertManager, SideLookDetector, FaceCoverageDetector,
)

__all__ = [
    "LandmarkDetector", "DrowsinessPipeline", "DrowsinessScorer",
    "SunglassesDetector", "AlertManager", "SideLookDetector",
    "FaceCoverageDetector",
]
