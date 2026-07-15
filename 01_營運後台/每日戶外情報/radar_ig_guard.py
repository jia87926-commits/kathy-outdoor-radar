#!/usr/bin/env python3
"""Repair and validate embedded IG thumbnails in Kathy Outdoor Radar."""

from __future__ import annotations

import argparse
import base64
import html
import re
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path


ACCOUNT_CARD_RE = re.compile(
    r'<article\b[^>]*class="[^"]*\baccount-card\b[^"]*"[^>]*>.*?</article>',
    re.DOTALL,
)
POST_URL_RE = re.compile(
    r'href="(https://www\.instagram\.com/'
    r'(?:(?:[A-Za-z0-9._]+)/)?(?:p|reel)/[^"/?#]+/?)"'
)
POST_ID_RE = re.compile(
    r'https://www\.instagram\.com/'
    r'(?:(?:[A-Za-z0-9._]+)/)?(?:p|reel)/([^/?#]+)'
)
ACCOUNT_URL_RE = re.compile(
    r'href="(https://www\.instagram\.com/(?!p/|reel/)([A-Za-z0-9._]+)/?)"'
)
MEDIA_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\big-initials\b[^"]*"[^>]*>.*?</div>'
    r'|<img\b(?=[^>]*class="[^"]*\big-(?:thumb|avatar)\b[^"]*")[^>]*>',
    re.DOTALL,
)
DATA_SRC_RE = re.compile(
    r'src="(data:image/(?:jpeg|jpg|png|webp);base64,[^"]+)"', re.IGNORECASE
)
FALLBACK_MARKERS = (
    "需登入補抓 / 無法驗證",
    "無法驗證最新貼文",
    "最新可見貼文較舊",
    "不列今日新訊",
    "本月無新貼文",
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138 Safari/537.36"
)
CURL_USER_AGENT = "Mozilla/5.0"


class OgImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.image_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta" or self.image_url:
            return
        values = {key.lower(): value for key, value in attrs if value is not None}
        if values.get("property", "").lower() == "og:image":
            self.image_url = html.unescape(values.get("content", "")) or None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text_atomic(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def is_verified_post(card: str) -> bool:
    return bool(POST_URL_RE.search(card)) and not any(
        marker in card for marker in FALLBACK_MARKERS
    )


def media_src(card: str) -> str | None:
    match = DATA_SRC_RE.search(card)
    return html.unescape(match.group(1)) if match else None


def post_cache_key(url: str) -> str:
    match = POST_ID_RE.search(url)
    return f"instagram-post:{match.group(1)}" if match else url.rstrip("/")


def collect_previous_media(source: str) -> tuple[dict[str, str], dict[str, str]]:
    by_post: dict[str, str] = {}
    by_account: dict[str, str] = {}
    for match in ACCOUNT_CARD_RE.finditer(source):
        card = match.group(0)
        src = media_src(card)
        if not src:
            continue
        post = POST_URL_RE.search(card)
        account = ACCOUNT_URL_RE.search(card)
        if post and 'class="ig-thumb"' in card:
            post_url = post.group(1).rstrip("/")
            by_post[post_url] = src
            by_post[post_cache_key(post_url)] = src
        if account and 'class="ig-avatar"' in card:
            by_account[account.group(1).rstrip("/")] = src
    return by_post, by_account


def request_bytes(url: str, *, referer: str | None = None) -> tuple[bytes, str]:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(5_000_001)
        content_type = response.headers.get_content_type()
    if len(data) > 5_000_000:
        raise ValueError("image exceeds 5 MB")
    return data, content_type


def curl_bytes(url: str, *, referer: str | None = None) -> bytes:
    command = [
        "curl",
        "--location",
        "--silent",
        "--show-error",
        "--fail",
        "--max-time",
        "30",
        "--max-filesize",
        "5000000",
        "--user-agent",
        CURL_USER_AGENT,
    ]
    if referer:
        command.extend(["--referer", referer])
    command.append(url)
    result = subprocess.run(command, check=True, capture_output=True)
    if len(result.stdout) > 5_000_000:
        raise ValueError("response exceeds 5 MB")
    return result.stdout


def detect_image_mime(data: bytes, declared: str) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if declared in {"image/jpeg", "image/png", "image/webp"}:
        return declared
    raise ValueError("response is not a supported image")


def fetch_data_uri(page_url: str) -> str:
    page_bytes, _ = request_bytes(page_url)
    parser = OgImageParser()
    parser.feed(page_bytes.decode("utf-8", errors="replace"))
    if not parser.image_url:
        parser = OgImageParser()
        parser.feed(curl_bytes(page_url).decode("utf-8", errors="replace"))
    if not parser.image_url:
        raise ValueError("og:image not found")
    try:
        image_bytes, declared = request_bytes(parser.image_url, referer=page_url)
    except Exception:
        image_bytes = curl_bytes(parser.image_url, referer=page_url)
        declared = "application/octet-stream"
    mime = detect_image_mime(image_bytes, declared)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def card_target(card: str) -> tuple[str | None, str, str]:
    verified = is_verified_post(card)
    post = POST_URL_RE.search(card)
    account = ACCOUNT_URL_RE.search(card)
    if verified and post:
        return post.group(1).rstrip("/"), "ig-thumb", "IG 貼文縮圖"
    if account:
        return account.group(1).rstrip("/"), "ig-avatar", "IG 帳號頭貼"
    return None, "ig-avatar", "IG 帳號頭貼"


def replace_media(card: str, data_uri: str, css_class: str, alt: str) -> str:
    tag = (
        f'<img class="{css_class}" src="{data_uri}" '
        f'alt="{html.escape(alt, quote=True)}" loading="lazy">'
    )
    if MEDIA_RE.search(card):
        return MEDIA_RE.sub(tag, card, count=1)
    return card.replace(">", f">{tag}", 1)


def ensure_thumbnail_css(source: str) -> str:
    if ".ig-thumb,.ig-avatar{" not in source:
        initials = re.search(r"\.ig-initials\{[^}]+\}", source)
        if not initials:
            raise ValueError(".ig-initials CSS rule not found")
        css = (
            ".ig-thumb,.ig-avatar{width:96px;height:96px;border-radius:6px;"
            "border:1px solid var(--line);object-fit:cover;background:var(--soft);display:block}"
        )
        source = source[: initials.end()] + css + source[initials.end() :]
    source = source.replace(
        ".ig-initials{width:72px;height:72px}",
        ".ig-initials,.ig-thumb,.ig-avatar{width:72px;height:72px}",
    )
    return source


def validate_data_uri(value: str) -> bool:
    try:
        header, payload = value.split(",", 1)
        if not header.startswith("data:image/") or ";base64" not in header:
            return False
        data = base64.b64decode(payload, validate=True)
        detect_image_mime(data, header[5:].split(";", 1)[0])
        return len(data) >= 1_000
    except (ValueError, TypeError):
        return False


def validate(source: str) -> dict[str, int]:
    cards = [match.group(0) for match in ACCOUNT_CARD_RE.finditer(source)]
    if not cards:
        raise ValueError("no IG account cards found")

    verified = 0
    thumbnails = 0
    avatars = 0
    initials = 0
    errors: list[str] = []

    for index, card in enumerate(cards, start=1):
        src = media_src(card)
        has_initials = 'class="ig-initials"' in card
        if 'class="ig-thumb"' in card:
            thumbnails += 1
        if 'class="ig-avatar"' in card:
            avatars += 1
        if has_initials:
            initials += 1

        if src and not validate_data_uri(src):
            errors.append(f"IG row {index}: invalid embedded image")

        if is_verified_post(card):
            verified += 1
            if 'class="ig-thumb"' not in card or not src:
                errors.append(f"IG row {index}: verified post has no embedded thumbnail")
        elif not src and not has_initials:
            errors.append(f"IG row {index}: no avatar or initials fallback")

    if verified and thumbnails != verified:
        errors.append(
            f"verified posts ({verified}) and thumbnails ({thumbnails}) do not match"
        )
    if re.search(r'<img[^>]+src="https?://[^"]*(?:instagram|cdninstagram)', source):
        errors.append("external Instagram image URL remains")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "account_cards": len(cards),
        "verified_posts": verified,
        "embedded_post_thumbnails": thumbnails,
        "embedded_account_avatars": avatars,
        "initials_fallbacks": initials,
    }


def repair(candidate_path: Path, previous_path: Path | None) -> dict[str, int]:
    candidate = read_text(candidate_path)
    previous = read_text(previous_path) if previous_path and previous_path.exists() else ""
    previous_posts, previous_accounts = collect_previous_media(previous)
    candidate_posts, candidate_accounts = collect_previous_media(candidate)
    previous_posts = {**candidate_posts, **previous_posts}
    previous_accounts = {**candidate_accounts, **previous_accounts}
    cards = [match.group(0) for match in ACCOUNT_CARD_RE.finditer(candidate)]
    if not cards:
        raise ValueError("no IG account cards found")

    targets: dict[str, tuple[str, str]] = {}
    for card in cards:
        target, css_class, alt = card_target(card)
        if target:
            targets[target] = (css_class, alt)

    resolved: dict[str, str] = {}
    for target, (css_class, _) in targets.items():
        cached = (
            previous_posts.get(post_cache_key(target)) or previous_posts.get(target)
            if css_class == "ig-thumb"
            else previous_accounts.get(target)
        )
        if cached and validate_data_uri(cached):
            resolved[target] = cached

    missing = [target for target in targets if target not in resolved]
    fetch_errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_data_uri, target): target for target in missing}
        for future in as_completed(futures):
            target = futures[future]
            try:
                resolved[target] = future.result()
            except Exception as exc:  # Network failures are reported without URL query data.
                fetch_errors[target] = str(exc)

    hard_errors: list[str] = []

    def update_card(match: re.Match[str]) -> str:
        card = match.group(0)
        target, css_class, alt = card_target(card)
        if not target or target not in resolved:
            if is_verified_post(card):
                hard_errors.append(f"verified post thumbnail unavailable: {target or 'unknown'}")
            return card
        return replace_media(card, resolved[target], css_class, alt)

    repaired = ACCOUNT_CARD_RE.sub(update_card, candidate)
    if hard_errors:
        details = [f"{item} ({fetch_errors.get(item.rsplit(': ', 1)[-1], 'fetch failed')})" for item in hard_errors]
        raise ValueError("; ".join(details))
    repaired = ensure_thumbnail_css(repaired)
    stats = validate(repaired)
    write_text_atomic(candidate_path, repaired)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    repair_parser = subparsers.add_parser("repair")
    repair_parser.add_argument("candidate", type=Path)
    repair_parser.add_argument("--previous", type=Path)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("html", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "repair":
            stats = repair(args.candidate, args.previous)
        else:
            stats = validate(read_text(args.html))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS " + " ".join(f"{key}={value}" for key, value in stats.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
