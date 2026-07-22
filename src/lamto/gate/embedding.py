"""Face embedding boundary: one image in, one L2-normalized vector out.

The production implementation loads InsightFace; tests bind a deterministic
fake through ``GATE_FACE_EMBEDDER`` so CI needs no model files and no
network. Nothing outside this module knows which model is in use, which is
also what makes a model swap a configuration change plus a re-enrolment
rather than a rewrite.

The quality errors below are an IMAGE-QUALITY gate. They establish that an
image is usable. They are not identity assurance and not liveness detection,
and must never be described or relied on as either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string


class FaceQualityError(ValueError):
    """Image is unusable. ``code`` is the resident-facing machine code."""

    code = "gate_face_unusable"


class NoFaceDetected(FaceQualityError):
    code = "gate_no_face_detected"


class MultipleFacesDetected(FaceQualityError):
    code = "gate_multiple_faces"


class FaceTooSmall(FaceQualityError):
    code = "gate_face_too_small"


class FaceTooBlurry(FaceQualityError):
    code = "gate_face_too_blurry"


class FaceEmbedderUnavailable(RuntimeError):
    """The model is not configured, could not load, or failed to run."""


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model_name: str
    model_version: str
    detection_score: float


class FaceEmbedder(Protocol):
    def embed(self, image_bytes: bytes) -> EmbeddingResult: ...


def get_embedder() -> FaceEmbedder:
    path = settings.GATE_FACE_EMBEDDER
    if not path:
        raise FaceEmbedderUnavailable(
            "GATE_FACE_EMBEDDER is not set; refusing to guess a face model."
        )
    return import_string(path)()
