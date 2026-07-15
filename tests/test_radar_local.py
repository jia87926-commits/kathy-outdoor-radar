from __future__ import annotations

import base64
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "01_營運後台" / "每日戶外情報" / "radar_ig_guard.py"
LOCAL_UPDATE_PATH = ROOT / "scripts" / "update_radar_local.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


guard = load_module("radar_ig_guard", GUARD_PATH)
local_update = load_module("update_radar_local", LOCAL_UPDATE_PATH)
IMAGE = "data:image/jpeg;base64," + base64.b64encode(
    b"\xff\xd8\xff" + (b"x" * 1200)
).decode("ascii")


def valid_html(post_url: str) -> str:
    return f'''<!doctype html><style>.ig-thumb,.ig-avatar{{width:72px;height:72px}}</style>
<article class="account-card"><img class="ig-thumb" src="{IMAGE}">
<a href="{post_url}">查看貼文</a>
<a href="https://www.instagram.com/amouter/">帳號入口</a></article>'''


class InstagramUrlTests(unittest.TestCase):
    def test_photo_and_reel_urls_are_verified(self):
        urls = (
            "https://www.instagram.com/p/PHOTO123/",
            "https://www.instagram.com/reel/REEL123/",
            "https://www.instagram.com/amouter/p/PHOTO456/",
            "https://www.instagram.com/amouter/reel/REEL456/",
        )
        for url in urls:
            with self.subTest(url=url):
                card = valid_html(url)
                self.assertTrue(guard.is_verified_post(card))
                self.assertEqual(guard.validate(card)["verified_posts"], 1)

    def test_same_shortcode_reuses_thumbnail_across_url_shapes(self):
        previous = valid_html("https://www.instagram.com/p/SAME123/")
        posts, _ = guard.collect_previous_media(previous)
        self.assertEqual(
            posts[guard.post_cache_key("https://www.instagram.com/amouter/reel/SAME123/")],
            IMAGE,
        )

    def test_fallback_marker_is_not_verified(self):
        card = valid_html("https://www.instagram.com/reel/OLD123/").replace(
            "</article>", "需登入補抓 / 無法驗證</article>"
        )
        self.assertFalse(guard.is_verified_post(card))


class LocalFinalizeTests(unittest.TestCase):
    def test_valid_candidates_replace_fixed_files_and_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_html = root / "candidate.html"
            candidate_md = root / "candidate.md"
            final_html = root / "final.html"
            final_md = root / "final.md"
            candidate_html.write_text(
                valid_html("https://www.instagram.com/amouter/reel/REEL789/"),
                encoding="utf-8",
            )
            candidate_md.write_text("new markdown", encoding="utf-8")
            final_html.write_text("previous html", encoding="utf-8")
            final_md.write_text("previous markdown", encoding="utf-8")

            local_update.finalize(
                candidate_html,
                candidate_md,
                final_html=final_html,
                final_md=final_md,
                guard_path=GUARD_PATH,
            )

            self.assertIn("REEL789", final_html.read_text(encoding="utf-8"))
            self.assertEqual(final_md.read_text(encoding="utf-8"), "new markdown")
            self.assertFalse(candidate_html.exists())
            self.assertFalse(candidate_md.exists())

    def test_invalid_candidate_keeps_previous_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_html = root / "candidate.html"
            candidate_md = root / "candidate.md"
            final_html = root / "final.html"
            final_md = root / "final.md"
            candidate_html.write_text("<html>invalid</html>", encoding="utf-8")
            candidate_md.write_text("new markdown", encoding="utf-8")
            final_html.write_text("previous html", encoding="utf-8")
            final_md.write_text("previous markdown", encoding="utf-8")

            with self.assertRaises(Exception):
                local_update.finalize(
                    candidate_html,
                    candidate_md,
                    final_html=final_html,
                    final_md=final_md,
                    guard_path=GUARD_PATH,
                )

            self.assertEqual(final_html.read_text(encoding="utf-8"), "previous html")
            self.assertEqual(final_md.read_text(encoding="utf-8"), "previous markdown")

    def test_github_actions_is_blocked(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaisesRegex(RuntimeError, "local-only"):
                local_update.finalize(Path("missing.html"), Path("missing.md"))


if __name__ == "__main__":
    unittest.main()
