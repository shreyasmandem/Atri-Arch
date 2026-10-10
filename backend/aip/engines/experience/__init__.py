"""Phase 11 - Client experience.

Turns a plan into things a non-architect can actually understand: a navigable 3D
model, a VR walkthrough, an AR preview placed in the client's own room, and a
narrated summary they can listen to.

Everything here is free and standards-based. The 3D model is glTF/GLB, which
every browser, phone and headset reads natively; the walkthrough and AR run on
WebXR, which is built into the browser; the narration uses the Web Speech API on
the client device. No 3D pipeline to license, no streaming service to pay for,
nothing to install.
"""

from aip.engines.experience.model3d import (
    BuildingModel,
    export_glb,
    export_obj,
    model_statistics,
)

__all__ = ["BuildingModel", "export_glb", "export_obj", "model_statistics"]
