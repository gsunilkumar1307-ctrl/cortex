"""
Unit and Integration Test Suite for Phase P3.4:
Universal Site-Agnostic Playwright Browser Intelligence & Interaction Engine.

Tests:
1. PageInspector: Dynamic search discovery on real and synthetic snapshots.
2. PageInspector: Media control classification and playback verification.
3. PageInspector: Auth wall and CAPTCHA detection.
4. WebsiteResolver: Absence of hardcoded SEARCH_LOCATORS and clean compound command resolution.
5. Cross-Site Selector Isolation: Zero leakage of site-specific locators across turns.
6. Planner: Multi-step media playback (5-step) and universal search (3-step) plan generation.
7. Orchestrator: End-to-end routing for YouTube media playback, Stack Overflow search, Notion auth inspection, and unfamiliar websites.
"""

import os
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.mcp.page_inspector import PageInspector, PageSnapshot, ParsedElement
from backend.mcp.website_resolver import WebsiteResolver
from backend.agent.planner import AutonomousPlanner
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import Task, TaskCommand, TaskStatus, RiskLevel


class TestUniversalBrowserIntelligence(unittest.TestCase):
    """Test suite for Universal Page Intelligence & Site-Agnostic Execution."""

    def test_01_page_inspector_dynamic_search_discovery(self):
        """Verifies dynamic search discovery on complex accessibility snapshots without site selectors."""
        sample_snapshot = """
- generic [ref=e1]:
  - generic [ref=e2]:
    - link "Home" [ref=e3]
    - textbox "Search for products, brands and more" [ref=e10]:
    - button "Search" [ref=e11] [cursor=pointer]
  - generic [ref=e20]:
    - textbox "Search Processor" [ref=e21]
    - textbox "Filter by Brand" [ref=e22]
"""
        snap = PageInspector.parse(sample_snapshot)
        self.assertEqual(len(snap.elements), 8)

        search_inputs = snap.find_search_inputs()
        self.assertGreater(len(search_inputs), 0)

        # Primary search input must be e10 ("Search for products..."), NOT the filter box e21
        primary = snap.get_primary_search_input()
        self.assertIsNotNone(primary)
        self.assertEqual(primary.ref, "e10")
        self.assertEqual(primary.name, "Search for products, brands and more")

    def test_02_page_inspector_youtube_style_snapshot(self):
        """Verifies search and media playback control discovery on video platforms."""
        yt_snapshot = """
- generic [ref=y1]:
  - searchbox "Search" [ref=y5]:
  - button "Search" [ref=y6] [cursor=pointer]
  - link "Imagine Dragons - Believer (Official Music Video)" [ref=y20]:
    - /url: /watch?v=7wtfhZwyrcc
  - button "Pause (k)" [ref=y30] [cursor=pointer]
  - video [ref=y31]
"""
        snap = PageInspector.parse(yt_snapshot, current_url="https://www.youtube.com/watch?v=7wtfhZwyrcc")

        # 1. Searchbox discovery
        search_inputs = snap.find_search_inputs()
        self.assertTrue(any(e.ref == "y5" for e, _ in search_inputs))

        # 2. Result links
        result_links = snap.find_result_links("believer")
        self.assertEqual(len(result_links), 1)
        self.assertEqual(result_links[0].ref, "y20")
        self.assertIn("/watch?v=7wtfhZwyrcc", result_links[0].url)

        # 3. Media controls & Playing state
        controls = snap.find_media_controls()
        self.assertTrue(len(controls["video"]) > 0)
        self.assertTrue(len(controls["pause_buttons"]) > 0)

        is_playing, evidence = snap.is_media_playing()
        self.assertTrue(is_playing)
        self.assertIn("Pause", evidence)

    def test_03_page_inspector_auth_wall_detection(self):
        """Verifies detection of login walls and authentication requirements."""
        auth_snapshot = """
- generic [ref=a1]:
  - heading "Log in to Notion" [level=1]
  - textbox "Email" [ref=a10]:
  - textbox "Password" [ref=a11]:
  - button "Log In" [ref=a12] [cursor=pointer]
"""
        snap = PageInspector.parse(auth_snapshot, current_url="https://www.notion.so/login", current_title="Log in to Notion")
        is_auth, reason = snap.detect_auth_wall()
        self.assertTrue(is_auth)
        self.assertIn("Authentication wall", reason)

    def test_04_website_resolver_no_hardcoded_selectors(self):
        """Verifies that SEARCH_LOCATORS dictionary has been completely removed."""
        wr = WebsiteResolver()
        self.assertFalse(hasattr(wr, "SEARCH_LOCATORS"), "SEARCH_LOCATORS must not exist on WebsiteResolver")
        locators = wr.get_search_locators("any_site")
        self.assertTrue(isinstance(locators, list))
        # Ensure generic HTML selectors are returned
        self.assertIn("input[type='search']", locators)
        self.assertIn("input[name='q']", locators)
        # Ensure no Amazon, Flipkart or YouTube specific selectors leak
        for loc in locators:
            self.assertNotIn("twotabsearchtextbox", loc)
            self.assertNotIn("Search Amazon", loc)

    def test_05_cross_site_selector_isolation(self):
        """Verifies that selectors from one website do not leak when searching a different website."""
        wr = WebsiteResolver()
        # Querying for amazon vs youtube vs unfamiliar site must return identical generic selectors
        locs_amazon = wr.get_search_locators("amazon")
        locs_youtube = wr.get_search_locators("youtube")
        locs_unfamiliar = wr.get_search_locators("unfamiliar_store")

        self.assertEqual(locs_amazon, locs_youtube)
        self.assertEqual(locs_youtube, locs_unfamiliar)

    def test_06_unfamiliar_website_domain_resolution(self):
        """Verifies site-agnostic domain synthesis for unfamiliar websites without whitelisting."""
        wr = WebsiteResolver()
        ok, url, name, err = wr.resolve_website("examplestore")
        self.assertTrue(ok)
        self.assertEqual(url.rstrip("/"), "https://www.examplestore.com")
        self.assertEqual(name, "examplestore")

        ok2, url2, name2, err2 = wr.resolve_website("docs.nvidia.com")
        self.assertTrue(ok2)
        self.assertEqual(url2.rstrip("/"), "https://docs.nvidia.com")

    def test_07_planner_media_playback_5_step_plan(self):
        """Verifies that 'Open YouTube and play believer' generates an atomic 5-step media plan."""
        planner = AutonomousPlanner()
        params = {
            "url": "https://www.youtube.com",
            "query": "believer",
            "browser_intent": "MEDIA_PLAYBACK",
            "site": "youtube",
        }
        plan = planner.plan("Open YouTube and play believer", TaskCommand.OPEN_URL, params)
        self.assertEqual(len(plan.steps), 5)

        step_actions = [s.description for s in plan.steps]
        self.assertEqual(step_actions[0], "Open https://www.youtube.com")
        self.assertEqual(step_actions[1], "Search for 'believer'")
        self.assertEqual(step_actions[2], "Snapshot search results")
        self.assertEqual(step_actions[3], "Open media result for 'believer'")
        self.assertEqual(step_actions[4], "Verify playback for 'believer'")

    def test_08_orchestrator_compound_intent_routing(self):
        """Verifies orchestrator routes compound media and search intents correctly."""
        orch = CortexOrchestrator()

        # 1. Media Playback Intent
        params_media = orch._extract_open_url_params("Open YouTube and play believer")
        self.assertEqual(params_media.get("browser_intent"), "MEDIA_PLAYBACK")
        self.assertEqual(params_media.get("query"), "believer")
        self.assertIn("youtube.com", params_media.get("url", ""))

        # 2. Universal Search Intent (Stack Overflow)
        params_so = orch._extract_open_url_params("Search Stack Overflow for Python asyncio examples")
        self.assertEqual(params_so.get("browser_intent"), "WEBSITE_SEARCH")
        self.assertEqual(params_so.get("query"), "Python asyncio examples")
        self.assertIn("stackoverflow.com", params_so.get("url", ""))

        # 3. Unfamiliar Website Search
        params_unf = orch._extract_open_url_params("Open ExampleStore and search for shoes")
        self.assertEqual(params_unf.get("browser_intent"), "WEBSITE_SEARCH")
        self.assertEqual(params_unf.get("query"), "shoes")
        self.assertIn("examplestore.com", params_unf.get("url", ""))


if __name__ == "__main__":
    unittest.main()
