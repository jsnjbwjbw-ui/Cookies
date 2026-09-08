# ═══════════════════════════════════════════════════════════════
# 🌐 عميل أزورا — مبني على عقد الـAPI المستخرج حرفيًا من سورس
#   إضافة أزورا الرسمية (keiyoushi/extensions-source → قالب Iken):
#
#   • صفحة الفريق (SSR):  GET {base}/teams/{team_slug}?page=N
#     صفحة Astro تضمّن داخل astro-island props كل شيء:
#       team (الاسم/الشعار/الإحصاءات) + postsData (أعمال الفريق
#       مقسمة صفحات: id/slug/عنوان/غلاف/عدد الفصول/آخر تحديث)
#       + chaptersData (أحدث 20 فصلًا منشورًا للفريق مع العمل التابع له).
#
#   • فصول عمل واحد:  GET {api}/api/post?postSlug={slug}
#     يعيد post.chapters[] = [{number, slug, title, createdAt,
#     isLocked, isTimeLocked, price, ...}] + totalChapterCount.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
import html as html_mod
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

AZORA_BASE = "https://azorafly.com"
AZORA_API = "https://api.azorafly.com"
DEFAULT_TEAM_SLUG = "cookies"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=25, connect=10)
MAX_TEAM_PAGES = 12            # سقف أمان عند اكتشاف أعمال الفريق

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.8",
    "Referer": AZORA_BASE + "/",
}

_session: Optional[aiohttp.ClientSession] = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=REQUEST_TIMEOUT, headers=BROWSER_HEADERS)
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


class AzoraError(Exception):
    """أصل أخطاء أزورا — رسالتها تظهر في بطاقة الحالة."""


class AzoraBlockedError(AzoraError):
    """حجب من كلاودفلير (403/503/429) — يعاد المحاولة في الدورة التالية."""


class AzoraUnavailableError(AzoraError):
    """شبكة/مهلة/رد غير متوقع — الموقع قد يكون تحت الصيانة."""


# ───────────────────────────────────────────────────────────────
# فك تسلسل Astro props: {"k": [0, قيمة]} (صيغة [نوع, بيانات])
# ───────────────────────────────────────────────────────────────
def _unwrap_astro(value):
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
        return _unwrap_astro(value[1])
    if isinstance(value, dict):
        return {k: _unwrap_astro(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap_astro(v) for v in value]
    return value


_ISLAND_RE = re.compile(r'astro-island[^>]*props="(.*?)"', re.S)


def parse_team_page(page_html: str) -> dict:
    """يستخرج بيانات الفريق من HTML صفحة /teams/{slug}:
    {team, posts: [...], posts_meta: {...}, latest_chapters: [...]}"""
    if "Attention Required" in page_html or "cf-error" in page_html:
        raise AzoraBlockedError("صفحة الفريق محجوبة من كلاودفلير حاليًا.")
    decoded_islands = [html_mod.unescape(m) for m in _ISLAND_RE.findall(page_html)]
    for decoded in decoded_islands:
        if "postsData" not in decoded:
            continue
        try:
            raw = json.loads(decoded)
        except Exception:
            continue
        data = _unwrap_astro(raw)
        posts_data = data.get("postsData") or {}
        chapters_data = data.get("chaptersData") or {}
        team = data.get("team") or {}
        return {
            "team": team,
            "posts": posts_data.get("posts", []) or [],
            "posts_meta": {
                "page": posts_data.get("page", 1),
                "perPage": posts_data.get("perPage", 24),
                "totalCount": posts_data.get("totalCount", 0),
                "totalPages": posts_data.get("totalPages", 1),
            },
            "latest_chapters": chapters_data.get("chapters", []) or [],
        }
    raise AzoraUnavailableError("لم أجد بيانات الفريق داخل الصفحة — ربما تغيرت بنية موقع أزورا.")


@dataclass
class TeamSnapshot:
    """لقطة كاملة لأعمال الفريق من صفحات /teams/{slug}."""
    team_name: str = ""
    team_avatar: str = ""
    posts: list = field(default_factory=list)            # كل أعمال الفريق
    latest_chapters: list = field(default_factory=list)  # أحدث فصول منشورة (الصفحة 1)
    pages_fetched: int = 0


async def _get_text(url: str) -> str:
    session = _get_session()
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            async with session.get(url) as resp:
                if resp.status in (403, 503, 429):
                    raise AzoraBlockedError(f"كلاودفلير رفض الطلب ({resp.status}).")
                if resp.status == 404:
                    raise AzoraError(f"الرابط غير موجود على أزورا (404): {url}")
                resp.raise_for_status()
                return await resp.text()
        except (AzoraBlockedError, AzoraError):
            raise
        except asyncio.TimeoutError:
            last_err = AzoraUnavailableError(f"انتهت المهلة أثناء الاتصال بأزورا: {url}")
        except aiohttp.ClientError as e:
            last_err = AzoraUnavailableError(f"خطأ شبكة مع أزورا: {type(e).__name__}")
        if attempt == 0:
            await asyncio.sleep(3.0)
    raise last_err or AzoraUnavailableError("فشل الاتصال بأزورا.")


async def fetch_team_page(team_slug: str, page: int = 1) -> dict:
    """صفحة واحدة من صفحات الفريق — تعيد dict مُحللًا."""
    url = f"{AZORA_BASE}/teams/{team_slug}"
    if page and page > 1:
        url += f"?page={page}"
    raw = await _get_text(url)
    return parse_team_page(raw)


async def fetch_team_snapshot(team_slug: str) -> TeamSnapshot:
    """كل أعمال الفريق (كل الصفحات حتى totalPages) + أحدث الفصول من الصفحة 1."""
    first = await fetch_team_page(team_slug, 1)
    snap = TeamSnapshot(
        team_name=str((first.get("team") or {}).get("name") or team_slug).upper(),
        team_avatar=(first.get("team") or {}).get("avatarUrl") or "",
        posts=list(first.get("posts") or []),
        latest_chapters=list(first.get("latest_chapters") or []),
        pages_fetched=1,
    )
    total_pages = int((first.get("posts_meta") or {}).get("totalPages") or 1)
    for page in range(2, min(total_pages, MAX_TEAM_PAGES) + 1):
        try:
            data = await fetch_team_page(team_slug, page)
        except (AzoraBlockedError, AzoraUnavailableError):
            # حجب/انقطاع أثناء التقاط الأعمال: نفضّل فشل الدورة كلها لنظافة البيانات
            raise
        except AzoraError:
            continue  # صفحة فرعية مفقودة: نكتفي بما توفر
        snap.posts.extend(data.get("posts") or [])
        snap.pages_fetched += 1
        await asyncio.sleep(1.0)  # مهلة تربّت بين الصفحات
    return snap


# ───────────────────────────────────────────────────────────────
# فصول عمل واحد — GET {api}/api/post?postSlug={slug}
# ───────────────────────────────────────────────────────────────
def parse_work_chapters(payload: dict) -> list[dict]:
    """يوحّد شكل الفصول القادمة من /api/post:
    [{number: str, slug, title, created_at, locked}] مرتبة تصاعديًا."""
    post = (payload or {}).get("post") or {}
    chapters = post.get("chapters") or []
    unified: list[dict] = []
    for ch in chapters:
        number = ch.get("number")
        if number is None:
            continue
        locked = bool(ch.get("isLocked") or ch.get("isTimeLocked")
                      or (ch.get("price") not in (None, 0) and not ch.get("chapterPurchased")))
        unified.append({
            "number": str(number),
            "slug": str(ch.get("slug") or ""),
            "title": str(ch.get("title") or ""),
            "created_at": str(ch.get("createdAt") or ""),
            "locked": locked,
        })
    try:
        unified.sort(key=lambda c: float(c["number"]))
    except Exception:
        pass
    return unified


async def fetch_work_chapters(post_slug: str) -> list[dict]:
    url = f"{AZORA_API}/api/post?postSlug={post_slug}"
    session = _get_session()
    try:
        async with session.get(url, headers={"Accept": "application/json"}) as resp:
            if resp.status in (403, 503, 429):
                raise AzoraBlockedError(f"كلاودفلير رفض طلب الفصول ({resp.status}).")
            if resp.status == 404:
                raise AzoraError(f"العمل غير موجود على أزورا: {post_slug}")
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    except (AzoraBlockedError, AzoraError):
        raise
    except Exception as e:
        raise AzoraUnavailableError(f"تعذر جلب فصول العمل {post_slug}: {type(e).__name__}") from e
    return parse_work_chapters(data if isinstance(data, dict) else {})


def chapter_url(post_slug: str, chapter_slug: str) -> str:
    if chapter_slug:
        return f"{AZORA_BASE}/series/{post_slug}/{chapter_slug}"
    return f"{AZORA_BASE}/series/{post_slug}"
