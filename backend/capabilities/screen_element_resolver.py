from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.capabilities.screen_context import ScreenContext, RectBounds, OCRBlock, _rect_intersects, _rect_contains
from backend.capabilities.screen_accessibility import NormalizedUIElement, NormalizedUIRole

logger = logging.getLogger("cortex.screen_element_resolver")


@dataclass
class ResolvedElementTarget:
    ok: bool
    element: Optional[NormalizedUIElement] = None
    confidence: float = 0.0
    resolution_method: str = "none"
    evidence: str = ""
    is_ambiguous: bool = False
    candidates: list[NormalizedUIElement] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "element": self.element.to_dict() if self.element else None,
            "confidence": self.confidence,
            "resolution_method": self.resolution_method,
            "evidence": self.evidence,
            "is_ambiguous": self.is_ambiguous,
            "candidates_count": len(self.candidates),
            "error": self.error,
        }


class UIElementResolver:
    """
    Intelligent UI Element Resolver enforcing:
    1. Accessibility-first matching
    2. OCR spatial correlation fallback
    3. Ambiguity resolution and target validation
    4. Never blindly executing unverified coordinates
    """

    def resolve_target(
        self,
        context: ScreenContext,
        target_description: str,
        expected_role: Optional[NormalizedUIRole] = None,
    ) -> ResolvedElementTarget:
        query = target_description.strip()
        if not query:
            return ResolvedElementTarget(ok=False, error="Target description cannot be empty.")

        q_lower = query.lower()
        # Clean common prefixes like "the ... button", "find ...", "click ..."
        clean_name = re.sub(r"^(the|find|click|press|select)\s+", "", q_lower)
        clean_name = re.sub(r"\s+(button|field|box|icon|link|menu)$", "", clean_name).strip()
        if not clean_name:
            clean_name = q_lower

        # ── Level 1: Accessibility-first matching ──────────────────────
        exact_matches: list[NormalizedUIElement] = []
        inferred_matches: list[NormalizedUIElement] = []
        partial_matches: list[NormalizedUIElement] = []

        for el in context.elements:
            if not el.is_enabled:
                continue

            # Role filter if expected
            if expected_role and el.role != expected_role and el.role != NormalizedUIRole.UNKNOWN:
                # If expecting button, skip non-buttons unless generic group
                if expected_role == NormalizedUIRole.BUTTON and not el.is_interactive:
                    continue

            title = (el.title or "").strip().lower()
            desc = (el.description or "").strip().lower()
            val = (el.value or "").strip().lower()
            inferred = (el.inferred_label or "").strip().lower()

            # Exact match on title or description
            if clean_name == title or clean_name == desc:
                exact_matches.append(el)
            # Inferred label match
            elif clean_name == inferred or clean_name in inferred.split():
                inferred_matches.append(el)
            # Partial substring match
            elif clean_name in title or clean_name in desc or clean_name in val:
                partial_matches.append(el)

        # Evaluate Level 1 matches
        if len(exact_matches) == 1:
            el = exact_matches[0]
            return ResolvedElementTarget(
                ok=True,
                element=el,
                confidence=1.0,
                resolution_method="accessibility_exact",
                evidence=f"Exact accessibility title match for '{query}' on element {el.id} (role={el.role.value})",
            )
        elif len(exact_matches) > 1:
            # Ambiguity: try to pick modal dialog child or frontmost element
            modal_children = [e for e in exact_matches if e.is_modal or e.depth > 1]
            chosen = modal_children[0] if modal_children else exact_matches[0]
            return ResolvedElementTarget(
                ok=True,
                element=chosen,
                confidence=0.85,
                resolution_method="accessibility_exact_disambiguated",
                evidence=f"Multiple exact matches found for '{query}'; prioritized {chosen.id} based on window hierarchy.",
                is_ambiguous=True,
                candidates=exact_matches,
            )

        if len(inferred_matches) == 1:
            el = inferred_matches[0]
            return ResolvedElementTarget(
                ok=True,
                element=el,
                confidence=0.90,
                resolution_method="accessibility_inferred",
                evidence=f"Inferred accessibility label match for '{query}' on element {el.id} ('{el.inferred_label}')",
            )
        elif len(inferred_matches) > 1:
            return ResolvedElementTarget(
                ok=True,
                element=inferred_matches[0],
                confidence=0.75,
                resolution_method="accessibility_inferred_disambiguated",
                evidence=f"Multiple inferred matches found for '{query}'. Selected {inferred_matches[0].id}",
                is_ambiguous=True,
                candidates=inferred_matches,
            )

        if len(partial_matches) == 1:
            el = partial_matches[0]
            return ResolvedElementTarget(
                ok=True,
                element=el,
                confidence=0.80,
                resolution_method="accessibility_partial",
                evidence=f"Partial accessibility match for '{query}' on element {el.id}",
            )

        # ── Level 2: OCR spatial correlation fallback ─────────────────
        ocr_matches = context.find_text_matches(clean_name)
        if ocr_matches:
            best_ocr = ocr_matches[0]
            # Find an AX element containing or intersecting this OCR block
            for el in context.elements:
                if el.bounds and (_rect_intersects(el.bounds, best_ocr.bounds) or _rect_contains(el.bounds, best_ocr.bounds)):
                    return ResolvedElementTarget(
                        ok=True,
                        element=el,
                        confidence=0.75,
                        resolution_method="ocr_spatial_correlation",
                        evidence=f"Correlated OCR text '{best_ocr.text}' (confidence={best_ocr.confidence}) with accessibility element {el.id}",
                    )

            # If no AX element wrapped the OCR bounds, we create a synthetic validated target
            # ONLY with bounds verified to be inside the window
            win = context.window
            if win and _rect_contains(win.bounds, best_ocr.bounds):
                synthetic = NormalizedUIElement(
                    id=f"ocr_target_{clean_name}",
                    role=expected_role or NormalizedUIRole.BUTTON,
                    raw_ax_role="AXSyntheticOCR",
                    path="ocr/0",
                    title=best_ocr.text,
                    inferred_label=best_ocr.text,
                    bounds=best_ocr.bounds,
                    is_enabled=True,
                    is_interactive=True,
                    supported_actions=["click"],
                )
                return ResolvedElementTarget(
                    ok=True,
                    element=synthetic,
                    confidence=0.70,
                    resolution_method="ocr_verified_bounds",
                    evidence=f"Resolved target via OCR text '{best_ocr.text}' inside active window bounds.",
                )

        return ResolvedElementTarget(
            ok=False,
            confidence=0.0,
            resolution_method="no_match",
            evidence=f"Could not resolve any UI element matching '{target_description}' across accessibility and OCR.",
            error=f"No matching UI element found for '{target_description}' in active interface.",
        )
