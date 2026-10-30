from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from backend.capabilities.screen_native import (
    AppInfo,
    WindowInfo,
    RectBounds,
    OCRObservation,
    NativeScreenHelperBridge,
)
from backend.capabilities.screen_accessibility import (
    NormalizedUIElement,
    AccessibilityPerceptionResult,
    NormalizedUIRole,
)

logger = logging.getLogger("cortex.screen_context")


class PerceptionSource(str, Enum):
    ACCESSIBILITY = "accessibility"
    VISION_OCR = "vision_ocr"
    SCREEN_CAPTURE = "screen_capture"
    MULTIMODAL_INFERENCE = "multimodal_inference"
    SYSTEM_METADATA = "system_metadata"


@dataclass(frozen=True)
class ObservationFact:
    source: PerceptionSource
    category: str
    detail: str
    confidence: float = 1.0
    is_inference: bool = False
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "category": self.category,
            "detail": self.detail,
            "confidence": self.confidence,
            "is_inference": self.is_inference,
            "timestamp": self.timestamp,
        }


@dataclass
class OCRBlock:
    text: str
    confidence: float
    bounds: RectBounds
    normalized_bounds: RectBounds
    reading_order_index: int = 0
    languages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "bounds": self.bounds.to_dict(),
            "normalized_bounds": self.normalized_bounds.to_dict(),
            "reading_order_index": self.reading_order_index,
            "languages": self.languages,
        }


def _rect_intersects(r1: RectBounds, r2: RectBounds) -> bool:
    return not (
        r1.x + r1.width < r2.x
        or r2.x + r2.width < r1.x
        or r1.y + r1.height < r2.y
        or r2.y + r2.height < r1.y
    )


def _rect_contains(outer: RectBounds, inner: RectBounds) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and outer.x + outer.width >= inner.x + inner.width
        and outer.y + outer.height >= inner.y + inner.height
    )


@dataclass
class ScreenContext:
    context_id: str
    app: AppInfo
    window: Optional[WindowInfo]
    elements: list[NormalizedUIElement]
    ocr_blocks: list[OCRBlock]
    screenshot_path: Optional[str]
    facts: list[ObservationFact]
    created_at_epoch: float
    created_at_iso: str
    is_valid: bool = True

    def is_fresh(self, max_age_seconds: float = 5.0) -> bool:
        if not self.is_valid:
            return False
        return (time.time() - self.created_at_epoch) <= max_age_seconds

    def invalidate(self) -> None:
        self.is_valid = False

    def get_visible_texts(self) -> list[str]:
        texts = []
        for b in self.ocr_blocks:
            if b.text and b.text.strip():
                texts.append(b.text.strip())
        for el in self.elements:
            lbl = el.inferred_label or el.title or el.value
            if lbl and lbl.strip() and lbl.strip() not in texts:
                texts.append(lbl.strip())
        return texts

    def find_text_matches(self, query: str, case_sensitive: bool = False) -> list[OCRBlock]:
        q = query.strip() if case_sensitive else query.strip().lower()
        matches = []
        for b in self.ocr_blocks:
            t = b.text if case_sensitive else b.text.lower()
            if q in t:
                matches.append(b)
        return matches

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "is_fresh": self.is_fresh(),
            "created_at": self.created_at_iso,
            "app": self.app.to_dict(),
            "window": self.window.to_dict() if self.window else None,
            "elements_count": len(self.elements),
            "ocr_blocks_count": len(self.ocr_blocks),
            "modal_dialog": any(el.is_modal for el in self.elements),
            "screenshot_path": self.screenshot_path,
            "facts_summary": [f.to_dict() for f in self.facts],
        }

    def distinguish_facts_and_inferences(self) -> dict[str, list[dict[str, Any]]]:
        observed = []
        inferred = []
        for f in self.facts:
            if f.is_inference:
                inferred.append(f.to_dict())
            else:
                observed.append(f.to_dict())
        return {
            "observed_facts": observed,
            "model_inferences": inferred,
        }


class ScreenContextFusionEngine:
    """
    Fuses multi-source perception (System State, Accessibility Hierarchy,
    Apple Vision OCR, and Screen Capture) into a canonical ScreenContext.
    """

    def __init__(self, bridge: Optional[NativeScreenHelperBridge] = None) -> None:
        self.bridge = bridge or NativeScreenHelperBridge()

    def fuse(
        self,
        ax_result: AccessibilityPerceptionResult,
        screenshot_path: Optional[str] = None,
        ocr_observations: Optional[list[OCRObservation]] = None,
        task_context: Optional[dict[str, Any]] = None,
    ) -> ScreenContext:
        ctx_id = str(uuid4())
        now_epoch = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        facts: list[ObservationFact] = []

        # App & Window facts
        app = ax_result.app or AppInfo(name="Unknown", pid=0)
        facts.append(
            ObservationFact(
                source=PerceptionSource.SYSTEM_METADATA,
                category="active_app",
                detail=f"Frontmost application: {app.name} (PID {app.pid})",
                confidence=1.0,
                is_inference=False,
                timestamp=now_iso,
            )
        )

        window = ax_result.window
        if window:
            facts.append(
                ObservationFact(
                    source=PerceptionSource.SYSTEM_METADATA,
                    category="active_window",
                    detail=f"Active window: '{window.title or 'Untitled'}' bounds={window.bounds.width}x{window.bounds.height}",
                    confidence=1.0,
                    is_inference=False,
                    timestamp=now_iso,
                )
            )

        # Accessibility facts
        facts.append(
            ObservationFact(
                source=PerceptionSource.ACCESSIBILITY,
                category="accessibility_tree",
                detail=f"Parsed {len(ax_result.elements)} accessible elements; modal={ax_result.modal_dialog_detected}",
                confidence=1.0,
                is_inference=False,
                timestamp=now_iso,
            )
        )

        # Process OCR observations if present or run on screenshot
        raw_ocr = ocr_observations
        if raw_ocr is None and screenshot_path and Path(screenshot_path).exists():
            raw_ocr = self.bridge.run_ocr(screenshot_path)

        ocr_blocks: list[OCRBlock] = []
        if raw_ocr:
            # Sort raw OCR top-to-bottom (y ascending), left-to-right (x ascending)
            sorted_ocr = sorted(raw_ocr, key=lambda b: (round(b.bounds.y / 20.0), b.bounds.x))
            for idx, o in enumerate(sorted_ocr):
                block = OCRBlock(
                    text=o.text,
                    confidence=o.confidence,
                    bounds=o.bounds,
                    normalized_bounds=o.normalized_bounds,
                    reading_order_index=idx,
                    languages=o.languages or [],
                )
                ocr_blocks.append(block)

            facts.append(
                ObservationFact(
                    source=PerceptionSource.VISION_OCR,
                    category="ocr_extraction",
                    detail=f"Extracted {len(ocr_blocks)} text blocks via Apple Vision OCR",
                    confidence=0.95,
                    is_inference=False,
                    timestamp=now_iso,
                )
            )

            # Correlate OCR text with accessibility elements lacking clean titles
            self._correlate_ocr_with_elements(ax_result.elements, ocr_blocks)

        # Task context inference
        if task_context:
            goal = task_context.get("goal") or task_context.get("intent") or "user operation"
            facts.append(
                ObservationFact(
                    source=PerceptionSource.MULTIMODAL_INFERENCE,
                    category="task_intent",
                    detail=f"Context aligned with task objective: {goal}",
                    confidence=0.85,
                    is_inference=True,
                    timestamp=now_iso,
                )
            )

        return ScreenContext(
            context_id=ctx_id,
            app=app,
            window=window,
            elements=ax_result.elements,
            ocr_blocks=ocr_blocks,
            screenshot_path=screenshot_path,
            facts=facts,
            created_at_epoch=now_epoch,
            created_at_iso=now_iso,
            is_valid=True,
        )

    def _correlate_ocr_with_elements(
        self,
        elements: list[NormalizedUIElement],
        ocr_blocks: list[OCRBlock],
    ) -> None:
        """Enrich elements with missing or weak labels using overlapping OCR text."""
        for el in elements:
            if not el.bounds:
                continue
            # If label is generic (like button_AXButton_0_1), look for overlapping OCR text
            if not el.title or el.inferred_label.startswith(el.role.value + "_"):
                matched_texts = []
                for b in ocr_blocks:
                    if _rect_intersects(el.bounds, b.bounds) or _rect_contains(el.bounds, b.bounds):
                        matched_texts.append(b.text.strip())
                if matched_texts:
                    combined = " ".join(matched_texts)
                    el.inferred_label = combined
                    logger.debug(f"Enriched element {el.id} with OCR text: '{combined}'")
