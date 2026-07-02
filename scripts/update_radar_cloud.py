#!/usr/bin/env python3
"""
Generate Kathy Outdoor Radar for GitHub Actions / GitHub Pages.

This script only reads public pages and RSS feeds. It does not use cookies,
tokens, browser profiles, or any private login state.
"""

from __future__ import annotations

import html
import hashlib
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "01_營運後台" / "每日戶外情報"
HTML_OUT = OUTPUT_DIR / "Kathy_Outdoor_Radar.html"
MD_OUT = OUTPUT_DIR / "Kathy_Outdoor_Radar_Latest.md"
TZ = ZoneInfo("Asia/Taipei")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)

RELEVANT_GQ_KEYWORDS = [
    "鞋",
    "球鞋",
    "足球鞋",
    "跑",
    "戶外",
    "高爾夫",
    "運動",
    "服裝",
    "服飾",
    "穿搭",
    "格紋",
    "男裝",
    "聯名",
    "設計",
    "球衣",
    "機能",
    "防水",
    "GORE",
    "材質",
    "世界盃",
    "HOKA",
    "Salomon",
    "NNormal",
    "Altra",
    "Topo",
    "KEEN",
]

RUNNING_KEYWORDS = [
    "HOKA",
    "On",
    "Cloudboom",
    "SAUCONY",
    "Triumph",
    "跑鞋",
    "速度訓練",
    "Joe Klecker",
    "馬拉松",
    "訓練",
]


@dataclass
class Article:
    source: str
    group: str
    title: str
    url: str
    date_label: str
    tags: list[str]
    summary: str
    use_case: str
    image: str = ""
    id: str = ""


@dataclass
class SourceResult:
    group: str
    title: str
    description: str
    pills: list[str]
    articles: list[Article]
    note: str = ""


def fetch_text(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def strip_tags(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def escape(value: str) -> str:
    return html.escape(value or "", quote=True)


def parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except Exception:
        return None


def is_fresh(date_value: datetime | None, now: datetime) -> bool:
    if date_value is None:
        return True
    return date_value.year == now.year and date_value.month == now.month


def date_label(date_value: datetime | None, now: datetime, fallback: str = "公開首頁最新") -> str:
    if date_value is None:
        return fallback
    if date_value.date() == now.date():
        return date_value.strftime("%Y/%m/%d")
    delta = now.date() - date_value.date()
    if timedelta(days=0) < delta <= timedelta(days=7):
        return f"{date_value.strftime('%Y/%m/%d')}｜{delta.days} 天前"
    return date_value.strftime("%Y/%m/%d")


def article_meta(url: str) -> dict[str, str]:
    try:
        text = fetch_text(url, timeout=18)
    except Exception:
        return {}

    def meta_value(pattern: str) -> str:
        match = re.search(pattern, text, flags=re.I)
        return html.unescape(match.group(1).strip()) if match else ""

    return {
        "image": meta_value(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'),
        "description": meta_value(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)["\']'),
        "date": (
            meta_value(r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']')
            or meta_value(r'"datePublished"\s*:\s*"([^"]+)"')
            or meta_value(r'<time[^>]+datetime=["\']([^"\']+)["\']')
        ),
    }


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    prefix = normalized[:54] or "item"
    return f"{prefix}-{digest}"


def infer_tags(title: str, source: str) -> list[str]:
    tags = [source]
    if any(keyword in title for keyword in ["鞋", "HOKA", "On", "SAUCONY", "足球鞋", "跑鞋"]):
        tags.extend(["鞋款", "男性 TA", "女性 TA"])
    if any(keyword in title for keyword in ["跑", "馬拉松", "速度訓練", "Joe Klecker"]):
        tags.extend(["跑步", "跑團"])
    if any(keyword in title for keyword in ["登山", "山", "步道", "森林", "虎頭蜂", "戶外"]):
        tags.extend(["登山", "全性別"])
    if any(keyword in title for keyword in ["格紋", "男裝", "球衣", "服裝", "服飾", "穿搭", "CANADA GOOSE", "CAYL"]):
        tags.extend(["男性 TA", "機能服飾", "設計趨勢"])
    if any(keyword in title for keyword in ["材質", "PFAS", "防水", "GORE", "回收"]):
        tags.extend(["材料", "機能布料"])
    deduped: list[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped[:5]


def use_case_for(title: str, source: str) -> str:
    if any(keyword in title for keyword in ["鞋", "HOKA", "On", "SAUCONY", "足球鞋", "跑鞋"]):
        return "可轉成鞋款比較、門市試穿話術或跑者選鞋內容。"
    if any(keyword in title for keyword in ["訓練", "馬拉松", "跑"]):
        return "可延伸成跑團活動、試穿鞋課表或跑者教育內容。"
    if any(keyword in title for keyword in ["登山", "步道", "虎頭蜂", "森林", "山"]):
        return "可整理成戶外安全提醒、登山準備清單或門市裝備諮詢題材。"
    if any(keyword in title for keyword in ["格紋", "男裝", "服裝", "服飾", "球衣", "設計"]):
        return "可觀察男性戶外風格與機能穿搭語言，支援社群與選品靈感。"
    return "可作為 OUTDOOR MAN 社群選題、部落格題材或商品溝通角度。"


def parse_rss_articles(
    feed_url: str,
    source: str,
    group: str,
    now: datetime,
    limit: int,
    relevant_keywords: list[str] | None = None,
    fetch_meta: bool = False,
) -> list[Article]:
    ns = {
        "media": "http://search.yahoo.com/mrss/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    text = fetch_text(feed_url)
    root = ET.fromstring(text)
    articles: list[Article] = []
    for item in root.findall(".//item"):
        title = strip_tags(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        pub = parse_pub_date(item.findtext("pubDate"))
        description = strip_tags(item.findtext("description") or "")
        categories = " ".join(strip_tags(cat.text or "") for cat in item.findall("category"))
        keywords = strip_tags(item.findtext("media:keywords", namespaces=ns) or "")
        haystack = " ".join([title, description, categories, keywords])

        if relevant_keywords and not any(keyword.lower() in haystack.lower() for keyword in relevant_keywords):
            continue
        if not is_fresh(pub, now):
            continue

        image = ""
        thumb = item.find("media:thumbnail", ns)
        if thumb is not None:
            image = thumb.attrib.get("url", "")
        if fetch_meta:
            meta = article_meta(link)
            image = meta.get("image") or image
            description = description or meta.get("description", "")
            meta_date = parse_pub_date(meta.get("date"))
            pub = pub or meta_date

        articles.append(
            Article(
                source=source,
                group=group,
                title=title,
                url=link,
                date_label=date_label(pub, now),
                tags=infer_tags(title, source),
                summary=(description[:110] + "…") if len(description) > 110 else description,
                use_case=use_case_for(title, source),
                image=image,
                id=f"{group}-{slug(link or title)}",
            )
        )
        if len(articles) >= limit:
            break
    return articles


def parse_hiking(now: datetime) -> list[Article]:
    text = fetch_text("https://hiking.biji.co/")
    articles: list[Article] = []
    pattern = re.compile(
        r'<a href="([^"]+)" class="headline__item[^"]*" title="([^"]+)">\s*'
        r'<img src="([^"]+)"',
        flags=re.S,
    )
    for href, title, image in pattern.findall(text):
        url = urllib.parse.urljoin("https://hiking.biji.co/", html.unescape(href))
        clean_title = html.unescape(title).strip()
        meta = article_meta(url)
        pub = parse_pub_date(meta.get("date"))
        if not is_fresh(pub, now):
            continue
        desc = meta.get("description") or clean_title
        articles.append(
            Article(
                source="健行筆記",
                group="hiking",
                title=clean_title,
                url=url,
                date_label=date_label(pub, now),
                tags=infer_tags(clean_title, "健行筆記"),
                summary=(desc[:110] + "…") if len(desc) > 110 else desc,
                use_case=use_case_for(clean_title, "健行筆記"),
                image=image,
                id=f"hiking-{slug(url)}",
            )
        )
        if len(articles) >= 4:
            break
    return articles


def parse_running(now: datetime) -> list[Article]:
    text = fetch_text("https://running.biji.co/")
    articles: list[Article] = []
    patterns = [
        re.compile(
            r'<a class="photo[^"]*" href="([^"]+)"[^>]+aria-label="([^"]+)"[^>]+'
            r'data-background-image="([^"]+)"',
            flags=re.S,
        ),
        re.compile(
            r'<a href="([^"]+)" class="index_tracking"[^>]+title="([^"]+)"[\s\S]*?'
            r'data-background-image="([^"]+)"',
            flags=re.S,
        ),
    ]
    seen: set[str] = set()
    for pattern in patterns:
        for href, title, image in pattern.findall(text):
            clean_title = html.unescape(title).strip()
            if not any(keyword.lower() in clean_title.lower() for keyword in RUNNING_KEYWORDS):
                continue
            url = urllib.parse.urljoin("https://running.biji.co/", html.unescape(href))
            if url in seen:
                continue
            seen.add(url)
            meta = article_meta(url)
            pub = parse_pub_date(meta.get("date"))
            if not is_fresh(pub, now):
                continue
            desc = meta.get("description") or clean_title
            articles.append(
                Article(
                    source="運動筆記",
                    group="running",
                    title=clean_title,
                    url=url,
                    date_label=date_label(pub, now),
                    tags=infer_tags(clean_title, "運動筆記"),
                    summary=(desc[:110] + "…") if len(desc) > 110 else desc,
                    use_case=use_case_for(clean_title, "運動筆記"),
                    image=image,
                    id=f"running-{slug(url)}",
                )
            )
            if len(articles) >= 4:
                return articles
    return articles


def fallback_article(source: str, group: str, message: str, url: str) -> Article:
    return Article(
        source=source,
        group=group,
        title="本週暫無可公開確認的新訊",
        url=url,
        date_label="待更新",
        tags=[source, "待確認"],
        summary=message,
        use_case="保留來源入口，下一次排程會再檢查公開頁與 RSS。",
        id=f"{group}-fallback",
    )


def build_sources(now: datetime) -> list[SourceResult]:
    results: list[SourceResult] = []

    try:
        outsiders = parse_rss_articles(
            "https://www.outsiders.com.tw/feed",
            "OUTSiDERS",
            "outsiders",
            now,
            5,
            fetch_meta=True,
        )
    except Exception as exc:
        outsiders = [fallback_article("OUTSiDERS", "outsiders", f"公開 RSS 抓取失敗：{exc}", "https://www.outsiders.com.tw/")]
    results.append(
        SourceResult(
            "outsiders",
            "OUTSiDERS",
            "戶外文化、戶外產業、機能品牌與台灣山林議題。",
            ["戶外文化", "機能品牌", "男女皆可"],
            outsiders,
        )
    )

    try:
        gq = parse_rss_articles(
            "https://www.gq.com.tw/feed/rss",
            "GQ Taiwan",
            "gq",
            now,
            4,
            relevant_keywords=RELEVANT_GQ_KEYWORDS,
        )
    except Exception as exc:
        gq = [fallback_article("GQ Taiwan", "gq", f"公開 RSS 抓取失敗：{exc}", "https://www.gq.com.tw/")]
    if not gq:
        gq = [fallback_article("GQ Taiwan", "gq", "今天 RSS 內沒有符合鞋款、男性戶外、機能服飾或設計趨勢的新文章。", "https://www.gq.com.tw/")]
    results.append(
        SourceResult(
            "gq",
            "GQ Taiwan",
            "男性 TA、城市風格、鞋款與機能設計趨勢。已排除純娛樂與低關聯影片。",
            ["男性 TA", "鞋款", "設計趨勢"],
            gq,
        )
    )

    try:
        hiking = parse_hiking(now)
    except Exception as exc:
        hiking = [fallback_article("健行筆記", "hiking", f"公開首頁抓取失敗：{exc}", "https://hiking.biji.co/")]
    if not hiking:
        hiking = [fallback_article("健行筆記", "hiking", "公開首頁沒有抓到當月可確認的新文章。", "https://hiking.biji.co/")]
    results.append(
        SourceResult(
            "hiking",
            "健行筆記",
            "台灣登山路線、戶外安全、健行知識與活動消息。",
            ["登山知識", "戶外安全", "路線"],
            hiking,
        )
    )

    try:
        running = parse_running(now)
    except Exception as exc:
        running = [fallback_article("運動筆記", "running", f"公開首頁抓取失敗：{exc}", "https://running.biji.co/")]
    if not running:
        running = [fallback_article("運動筆記", "running", "公開首頁沒有抓到當月可確認的跑鞋或訓練文章。", "https://running.biji.co/")]
    results.append(
        SourceResult(
            "running",
            "運動筆記",
            "跑鞋新品、品牌動態、跑步訓練、賽事與跑團話題。",
            ["鞋款", "跑團", "訓練"],
            running,
        )
    )

    results.append(
        SourceResult(
            "likeshop",
            "GQ LikeShop",
            "只收可確認日期與文章型內容；影片或無法確認日期時不放今日文章牆。",
            ["待確認", "不硬補"],
            [
                fallback_article(
                    "GQ LikeShop",
                    "likeshop",
                    "雲端版未抓到可公開確認日期的 LikeShop 文章，避免把影片或舊內容誤放成今日新聞。",
                    "https://likeshop.me/gqtaiwan",
                )
            ],
        )
    )

    results.append(
        SourceResult(
            "material",
            "材質 / 規範",
            "歐盟、ECHA、Textile Exchange、ISPO 等公開來源的新規範與材料趨勢。",
            ["PFAS-free", "環保材質", "規範"],
            [
                fallback_article(
                    "材質 / 規範",
                    "material",
                    "本次公開來源未抓到當月新的材質或歐盟規範文章；舊法規不放進今日首頁。",
                    "https://echa.europa.eu/",
                )
            ],
        )
    )

    return results


IG_ACCOUNTS = [
    ("PAPERSKY.TW", "https://www.instagram.com/papersky.tw/", "旅遊企劃、戶外行旅、活動報名"),
    ("AMOUTER", "https://www.instagram.com/amouter/", "同行選品、鞋款、門市活動"),
    ("GQ Taiwan", "https://www.instagram.com/gqtaiwan/", "男性風格、運動與城市生活"),
    ("AMOUTER Life", "https://www.instagram.com/amouter_life/", "同行生活線、包款與機能服飾"),
    ("WRC Taipei", "https://www.instagram.com/wrc_taipei/", "跑團活動與品牌合作"),
    ("NNormal", "https://www.instagram.com/nnormal_official/", "越野跑鞋與品牌故事"),
    ("Keep On", "https://www.instagram.com/keepon.outdoor/", "登山補給、同行活動"),
    ("ROCKLAND", "https://www.instagram.com/rockland_taiwan/", "登山旅遊、裝備建議"),
    ("Cliff Coaching", "https://www.instagram.com/cliff_coaching_system/", "越野跑訓練"),
    ("Blackwater RC", "https://www.instagram.com/blackwater.rc/", "跑團與恢復訓練"),
    ("BEAMS Taiwan", "https://www.instagram.com/beams_taiwan/", "城市風格、鞋款與機能材質"),
    ("MAC RUN CLUB", "https://www.instagram.com/montreal.athletes.club/", "跑團與鞋款合作"),
    ("GOOPi", "https://www.instagram.com/goopi.co/", "機能服飾、生活風格"),
]


def render_article(article: Article) -> str:
    img = (
        f'<div class="article-image"><img src="{escape(article.image)}" alt="{escape(article.title)} 來源圖片" loading="lazy"></div>'
        if article.image
        else '<div class="article-image article-image-empty"><span>NO IMAGE</span></div>'
    )
    tags = "".join(f'<span class="pill">{escape(tag)}</span>' for tag in article.tags[:4])
    return f"""
              <article class="article-card" data-id="{escape(article.id)}" data-title="{escape(article.title)}" data-tags="{escape(','.join(article.tags))}">
                {img}
                <div class="article-body">
                  <div class="meta-row"><span class="pill">{escape(article.source)}</span><span class="pill">{escape(article.date_label)}</span>{tags}</div>
                  <h4>{escape(article.title)}</h4>
                  <p>{escape(article.summary)}</p>
                  <div class="use-case"><strong>可用角度</strong>{escape(article.use_case)}</div>
                  <a class="source-link" href="{escape(article.url)}" target="_blank" rel="noopener noreferrer">閱讀來源</a>
                  <div class="card-actions">
                    <button class="feedback-button" type="button" data-action="like">喜歡</button>
                    <button class="feedback-button" type="button" data-action="useful">有用</button>
                    <button class="feedback-button" type="button" data-action="product">可用於選品</button>
                    <button class="feedback-button" type="button" data-action="post">想做成貼文</button>
                    <button class="feedback-button" type="button" data-action="irrelevant">不相關</button>
                  </div>
                </div>
              </article>"""


def render_accounts() -> str:
    cards = []
    for name, url, angle in IG_ACCOUNTS:
        initials = "".join(part[:1] for part in re.split(r"[\s._-]+", name) if part)[:2].upper()
        cards.append(
            f"""
          <article class="account-card">
            <div class="avatar-fallback">{escape(initials)}</div>
            <div>
              <div class="meta-row"><span class="pill">Instagram</span><span class="pill">雲端公開版</span><span class="pill">需公開驗證</span></div>
              <h4>{escape(name)}</h4>
              <p>{escape(angle)}。雲端版不存 IG cookie；若公開頁無法確認最新日期，就不把舊貼文寫成今天最新。</p>
            </div>
            <div class="use-case"><strong>可用角度</strong>保留帳號入口，後續可用登入瀏覽器手動補抓最新貼文日期。</div>
            <a class="source-link ig-post-link" href="{escape(url)}" rel="noopener noreferrer">查看帳號</a>
          </article>"""
        )
    return "\n".join(cards)


def render_html(results: list[SourceResult], now: datetime) -> str:
    updated = now.strftime("%Y/%m/%d %H:%M")
    filter_buttons = [
        ("all", "全部來源"),
        ("outsiders", "OUTSiDERS"),
        ("gq", "GQ Taiwan"),
        ("hiking", "健行筆記"),
        ("running", "運動筆記"),
        ("likeshop", "GQ LikeShop"),
        ("material", "材質 / 規範"),
        ("accounts", "IG 帳號"),
    ]
    buttons = "\n".join(
        f'<button class="filter-button" type="button" data-filter="{key}" aria-pressed="{str(key == "all").lower()}">{label}</button>'
        for key, label in filter_buttons
    )
    sections = []
    for result in results:
        pills = "".join(f'<span class="pill">{escape(pill)}</span>' for pill in result.pills)
        articles = "\n".join(render_article(article) for article in result.articles)
        sections.append(
            f"""
          <section class="source-panel" data-source="{escape(result.group)}">
            <div class="source-panel-header">
              <div>
                <p class="eyebrow">Source</p>
                <h3>{escape(result.title)}</h3>
                <div class="source-meta">{pills}</div>
              </div>
              <p>{escape(result.description)}</p>
            </div>
            <div class="source-grid">{articles}
            </div>
          </section>"""
        )

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>Kathy Outdoor Radar</title>
  <style>
    :root {{
      --text: #111111;
      --muted: #666666;
      --line: #dddddd;
      --soft: #f7f7f7;
      --green: #e7f2e8;
      --blue: #e8f0f7;
      --rose: #f6e8ea;
      --yellow: #f6f0dc;
      --violet: #eee9f7;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #ffffff; color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif; }}
    a {{ color: inherit; }}
    .page-shell {{ max-width: 1180px; margin: 0 auto; padding: 18px; }}
    .topbar {{ display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 0 18px; border-bottom: 1px solid var(--line); position: sticky; top: 0; background: rgba(255,255,255,.96); z-index: 5; }}
    .brand {{ display: inline-flex; align-items: center; gap: 10px; font-weight: 800; text-decoration: none; letter-spacing: .02em; }}
    .brand-mark {{ display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--text); font-size: 14px; }}
    .nav {{ display: flex; gap: 12px; flex-wrap: wrap; font-size: 13px; color: var(--muted); }}
    .nav a {{ text-decoration: none; }}
    .section {{ padding: 22px 0; }}
    .filter-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }}
    button, .source-link {{ border: 1px solid var(--text); background: #fff; color: var(--text); min-height: 34px; padding: 7px 11px; border-radius: 6px; font-size: 13px; text-decoration: none; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }}
    .filter-button[data-filter="outsiders"] {{ background: var(--green); }}
    .filter-button[data-filter="gq"] {{ background: var(--blue); }}
    .filter-button[data-filter="hiking"] {{ background: var(--yellow); }}
    .filter-button[data-filter="running"] {{ background: var(--rose); }}
    .filter-button[data-filter="material"] {{ background: var(--violet); }}
    .filter-button[aria-pressed="true"], .source-link {{ background: #111; color: #fff; }}
    .notice {{ margin: 0 0 18px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 6px; color: var(--muted); line-height: 1.7; }}
    .source-panel {{ border-top: 1px solid var(--line); padding: 22px 0; }}
    .source-panel[hidden] {{ display: none; }}
    .source-panel-header {{ display: grid; grid-template-columns: minmax(220px, .34fr) 1fr; gap: 22px; align-items: start; margin-bottom: 16px; }}
    .source-panel-header h3 {{ margin: 2px 0 10px; font-size: clamp(26px, 4vw, 48px); line-height: .95; letter-spacing: 0; }}
    .source-panel-header p {{ margin: 0; color: var(--muted); line-height: 1.7; }}
    .eyebrow {{ text-transform: uppercase; letter-spacing: .08em; font-size: 12px; color: var(--muted); }}
    .source-meta, .meta-row, .card-actions {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .pill {{ display: inline-flex; align-items: center; min-height: 24px; padding: 3px 8px; border: 1px solid var(--line); border-radius: 999px; font-size: 12px; color: var(--muted); background: #fff; }}
    .source-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    .article-card {{ border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #fff; display: grid; grid-template-columns: minmax(180px, .42fr) 1fr; min-height: 250px; }}
    .article-image {{ background: var(--soft); min-height: 220px; }}
    .article-image img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .article-image-empty {{ display: grid; place-items: center; color: #aaa; font-weight: 700; }}
    .article-body {{ padding: 16px; display: flex; flex-direction: column; gap: 10px; }}
    h4 {{ margin: 0; font-size: 20px; line-height: 1.25; }}
    p {{ margin: 0; line-height: 1.65; color: var(--muted); }}
    .use-case {{ border-top: 1px solid var(--line); padding-top: 10px; color: var(--muted); line-height: 1.55; font-size: 14px; }}
    .use-case strong {{ color: var(--text); margin-right: 6px; }}
    .feedback-button[data-action="like"] {{ background: var(--rose); }}
    .feedback-button[data-action="useful"] {{ background: var(--green); }}
    .feedback-button[data-action="product"] {{ background: var(--yellow); }}
    .feedback-button[data-action="post"] {{ background: var(--blue); }}
    .feedback-button[data-action="irrelevant"] {{ background: #f0f0f0; color: #555; }}
    .account-grid {{ display: grid; gap: 12px; }}
    .account-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; display: grid; grid-template-columns: 58px minmax(0, 1fr) minmax(180px, .35fr) auto; gap: 14px; align-items: start; }}
    .avatar-fallback {{ width: 48px; height: 48px; border: 1px solid var(--text); border-radius: 50%; display: grid; place-items: center; font-weight: 800; }}
    .feedback-panel {{ border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    .toast {{ position: fixed; right: 16px; bottom: 16px; background: #111; color: #fff; padding: 10px 12px; border-radius: 6px; opacity: 0; transform: translateY(8px); transition: .2s ease; }}
    .toast[data-show="true"] {{ opacity: 1; transform: translateY(0); }}
    @media (max-width: 880px) {{
      .source-panel-header, .article-card, .account-card {{ grid-template-columns: 1fr; }}
      .source-grid {{ grid-template-columns: 1fr; }}
      .topbar {{ position: static; align-items: flex-start; flex-direction: column; }}
      .article-image {{ min-height: 210px; }}
    }}
  </style>
</head>
<body>
  <div class="page-shell">
    <header class="topbar">
      <a class="brand" href="#feed"><span class="brand-mark">K</span><span>Kathy Outdoor Radar</span></a>
      <nav class="nav" aria-label="頁面導覽">
        <a href="#feed">Articles</a>
        <a href="#accounts">Accounts</a>
        <a href="#feedback">Feedback</a>
      </nav>
    </header>
    <main>
      <section class="section" id="feed">
        <div class="filter-row" role="toolbar" aria-label="來源篩選">{buttons}</div>
        <p class="notice">更新時間：{escape(updated)}（台北時間）。雲端版只抓公開可驗證來源；IG 不保存登入資料，無法確認日期時只保留帳號入口，不把舊貼文寫成今日最新。</p>
        <div class="source-feed">{''.join(sections)}
        </div>
      </section>
      <section class="section source-panel" id="accounts" data-source="accounts">
        <div class="source-panel-header">
          <div>
            <p class="eyebrow">Instagram accounts</p>
            <h3>IG 帳號最新動態</h3>
            <div class="source-meta"><span class="pill">不存登入資料</span><span class="pill">文字版</span></div>
          </div>
          <p>雲端排程不使用 Kathy 的 IG cookie。這區保留帳號入口與追蹤角度；需要日期確認的貼文，後續可用登入瀏覽器補抓。</p>
        </div>
        <div class="account-grid">{render_accounts()}
        </div>
      </section>
      <section class="section" id="feedback">
        <div class="feedback-panel">
          <p class="eyebrow">Feedback</p>
          <h3>本頁回饋</h3>
          <p id="feedbackSummary">尚未留下回饋。</p>
          <div class="card-actions" style="margin-top:12px">
            <button class="feedback-button" type="button" id="copyFeedback" data-action="useful">複製回饋 JSON</button>
            <button class="feedback-button" type="button" id="resetFeedback" data-action="irrelevant">清除本頁回饋</button>
          </div>
        </div>
      </section>
    </main>
  </div>
  <div class="toast" id="toast">已更新</div>
  <script>
    const STORAGE_KEY = "kathyOutdoorRadarFeedbackCloud";
    let feedback = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}");
    const toast = document.getElementById("toast");
    function showToast(text) {{
      toast.textContent = text;
      toast.dataset.show = "true";
      setTimeout(() => toast.dataset.show = "false", 1600);
    }}
    function saveFeedback() {{
      localStorage.setItem(STORAGE_KEY, JSON.stringify(feedback, null, 2));
      renderFeedback();
    }}
    function renderFeedback() {{
      const counts = Object.values(feedback).flat().reduce((acc, action) => {{
        acc[action] = (acc[action] || 0) + 1;
        return acc;
      }}, {{}});
      const summary = Object.entries(counts).map(([key, value]) => `${{key}}：${{value}}`).join(" / ");
      document.getElementById("feedbackSummary").textContent = summary || "尚未留下回饋。";
    }}
    document.querySelectorAll(".filter-button").forEach((button) => {{
      button.addEventListener("click", () => {{
        const filter = button.dataset.filter;
        document.querySelectorAll(".filter-button").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
        document.querySelectorAll(".source-panel[data-source]").forEach((panel) => {{
          panel.hidden = filter !== "all" && panel.dataset.source !== filter;
        }});
        if (filter === "accounts") document.getElementById("accounts").scrollIntoView({{ behavior: "smooth" }});
      }});
    }});
    document.querySelectorAll(".feedback-button[data-action]").forEach((button) => {{
      button.addEventListener("click", () => {{
        const card = button.closest("[data-id]");
        if (!card) return;
        const id = card.dataset.id;
        const action = button.dataset.action;
        feedback[id] = feedback[id] || [];
        if (!feedback[id].includes(action)) feedback[id].push(action);
        saveFeedback();
        showToast("已記錄回饋。");
      }});
    }});
    document.getElementById("copyFeedback").addEventListener("click", async () => {{
      await navigator.clipboard.writeText(JSON.stringify(feedback, null, 2));
      showToast("已複製回饋。");
    }});
    document.getElementById("resetFeedback").addEventListener("click", () => {{
      feedback = {{}};
      saveFeedback();
      showToast("已清除回饋。");
    }});
    renderFeedback();
  </script>
</body>
</html>
"""


def render_markdown(results: list[SourceResult], now: datetime) -> str:
    lines = [
        "# Kathy Outdoor Radar 最新摘要",
        "",
        f"更新時間：{now.strftime('%Y-%m-%d %H:%M')}（台北時間；雲端公開來源版）  ",
        "HTML 固定頁面：`Kathy_Outdoor_Radar.html`",
        "",
        "本版可由 GitHub Actions 在雲端排程產生，不依賴 Kathy 的 Mac 是否醒著。IG 不使用登入資料，無法公開確認日期時不把舊貼文寫成最新。",
        "",
        "## 今日網站來源",
        "",
    ]
    for result in results:
        lines.append(f"### {result.title}")
        for article in result.articles:
            lines.append(f"- {article.date_label}｜[{article.title}]({article.url})：{article.summary}")
        lines.append("")
    lines.extend(
        [
            "## IG 帳號",
            "",
            "雲端版不保存 IG cookie 或登入狀態；目前以帳號入口與追蹤角度呈現。若要確認 IG 最新貼文日期，需要使用 Kathy 已登入的瀏覽器補抓。",
            "",
        ]
    )
    for name, url, angle in IG_ACCOUNTS:
        lines.append(f"- [{name}]({url})：{angle}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(TZ)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = build_sources(now)
    HTML_OUT.write_text(render_html(results, now), encoding="utf-8")
    MD_OUT.write_text(render_markdown(results, now), encoding="utf-8")
    print(f"Updated {HTML_OUT}")
    print(f"Updated {MD_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
