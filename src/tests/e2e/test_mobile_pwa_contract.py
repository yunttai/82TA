from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WEB_ROOT = REPOSITORY_ROOT / "src/apps/web"


class MobilePwaContractTests(unittest.TestCase):
    def test_manifest_is_installable_on_android_and_ios_assets_exist(self) -> None:
        manifest = json.loads((WEB_ROOT / "public/manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "/")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        icons = {(icon["sizes"], icon["purpose"]) for icon in manifest["icons"]}
        self.assertIn(("192x192", "any"), icons)
        self.assertIn(("512x512", "any maskable"), icons)
        self.assertTrue((WEB_ROOT / "public/icons/apple-touch-icon.png").is_file())
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn("viewport-fit=cover", html)

    def test_service_worker_caches_shell_but_never_api_or_post(self) -> None:
        worker = (WEB_ROOT / "public/sw.js").read_text(encoding="utf-8")
        self.assertIn('request.method !== "GET"', worker)
        self.assertIn('url.pathname.startsWith("/api/")', worker)
        self.assertIn('caches.match("/")', worker)
        shell_match = re.search(r"const SHELL = \[(.*?)\];", worker, re.DOTALL)
        self.assertIsNotNone(shell_match)
        shell = shell_match.group(1) if shell_match else ""
        self.assertNotIn("/api/", shell)
        self.assertNotIn("route-search", shell)

    def test_pwa_update_requires_user_confirmation_before_reload(self) -> None:
        component = (
            WEB_ROOT / "src/features/pwa/PwaStatus.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("window.confirm", component)
        self.assertIn('postMessage({ type: "SKIP_WAITING" })', component)
        self.assertIn("updateRequested.current", component)
        self.assertIn("window.location.reload()", component)

    def test_mobile_css_covers_safe_area_touch_reflow_and_reduced_motion(self) -> None:
        css = (WEB_ROOT / "src/styles.css").read_text(encoding="utf-8")
        for required in (
            "safe-area-inset-top",
            "safe-area-inset-bottom",
            "100dvh",
            "min-height: 44px",
            ":focus-visible",
            "prefers-reduced-motion: reduce",
        ):
            self.assertIn(required, css)


if __name__ == "__main__":
    unittest.main()
