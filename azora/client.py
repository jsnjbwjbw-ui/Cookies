# ═══════════════════════════════════════════════════════════════
# 🌐 عميل أزورا — عقد الـAPI الحالي بعد تحديث واجهة الموقع:
#
#   الموقع azorafly.com أصبح Next.js/React (بدل Astro)، والمصدر
#   المرجعي هو سورس إضافة أزورا الرسمية (keiyoushi/extensions-source
#   ← قالب Iken 1.6) المحدّث للواجهة الجديدة.
#
#   1) أعمال الفريق (كلها بترقيم رسمي) — النداء نفسه شغال ومؤكد:
#      GET {api}/api/teams/posts/{teamId}?page=N&perPage=24
#      → {posts:[{id, slug, postTitle, featuredImage, updatedAt,
#         _count:{chapters}}], totalCount, page, perPage, totalPages}
#
#   2) معرف الفريق من السلاغ — قائمة الفرق الرسمية:
#      GET {api}/api/teams?page=N&perPage=50
#      → {teams:[{id, slug, name, avatarUrl, ...}], totalCount,
#         totalPages}
#
#   3) صفحة الفريق SSR: GET {base}/teams/{slug}
#      Next.js تعيد الاسم في <title> وأعمال الصفحة الأولى كروابط
#      href="/series/{slug}" — تُستخدم تحققًا ومرجعًا احتياطيًا فقط.
#
#   4) فصول عمل واحد — عقد Iken الرسمي:
#      GET {api}/api/post?postSlug={slug}
#      → {totalChapterCount, post:{id, slug, ..., chapters?}}
#      GET {api}/api/chapters?postId={post.id}
#      → {post:{chapters:[...]}} — القائمة الكاملة (إضافة أزورا
#      الرسمية تستخدم هذا المسار دائمًا عبر useChaptersApi).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
import html as html_mod
import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import aiohttp

AZORA_BASE = "https://azorafly.com"
AZORA_API = "https://api.azorafly.com"
DEFAULT_TEAM_SLUG = "cookies"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=25, connect=10)
MAX_TEAM_PAGES = 20            # سقف أمان (20 × 24 = حتى 480 عملًا)
TEAM_POSTS_PER_PAGE = 24       # نفس قيمة الموقع الرسمي في واجهته
TEAM_LIST_PER_PAGE = 50        # صفحة قائمة الفرق عند البحث عن معرف الفريق
MAX_TEAM_LIST_PAGES = 10       # سقف صفحات قائمة الفرق (10 × 50 = 500 فريق)

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
# طبقة HTTP مشتركة
# ───────────────────────────────────────────────────────────────
async def _resp_check(resp: aiohttp.ClientResponse):
    if resp.status in (403, 503, 429):
        raise AzoraBlockedError(f"كلاودفلير رفض الطلب ({resp.status}).")
    if resp.status == 404:
        raise AzoraError(f"الرابط غير موجود على أزورا (404).")
    resp.raise_for_status()


async def _get_text(url: str) -> str:
    session = _get_session()
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            async with session.get(url) as resp:
                _resp_check(resp)
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


async def _get_json(url: str) -> dict:
    """GET يتوقع JSON — بنفس تصنيف أخطاء _get_text (بلا إعادة محاولة:
    تُستخدم في نداءات متسلسلة والمزامنة تعيد المحاولة دوريًا)."""
    session = _get_session()
    try:
        async with session.get(url, headers={"Accept": "application/json"}) as resp:
            _resp_check(resp)
            data = await resp.json(content_type=None)
            return data if isinstance(data, dict) else {}
    except (AzoraBlockedError, AzoraError):
        raise
    except asyncio.TimeoutError as e:
        raise AzoraUnavailableError(f"انتهت المهلة مع {url}") from e
    except aiohttp.ClientError as e:
        raise AzoraUnavailableError(f"خطأ شبكة مع أزورا: {type(e).__name__}") from e
    except Exception as e:
        raise AzoraUnavailableError(f"رد غير متوقع من أزورا: {type(e).__name__}") from e


# ───────────────────────────────────────────────────────────────
# صفحة الفريق SSR (Next.js) — الاسم من <title> والأعمال من الروابط
# ───────────────────────────────────────────────────────────────
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_SERIES_HREF_RE = re.compile(r'href="/series/([A-Za-z0-9_\-]+)"')


def parse_team_page(page_html: str) -> dict:
    """يستخرج هوية الفريق وأعمال الصفحة الأولى من HTML صفحة /teams/{slug}:
    {team:{name}, team_id: None, posts:[{slug, postTitle}], posts_meta, latest_chapters: []}"""
    if "Attention Required" in page_html or "cf-error" in page_html:
        raise AzoraBlockedError("صفحة الفريق محجوبة من كلاودفلير حاليًا.")
    m = _TITLE_RE.search(page_html)
    title = html_mod.unescape(m.group(1)).strip() if m else ""
    slugs = list(dict.fromkeys(_SERIES_HREF_RE.findall(page_html)))
    if not title and not slugs:
        raise AzoraUnavailableError("لم أتعرف على صفحة الفريق — ربما تغيرت بنية موقع أزورا.")
    posts = [{"slug": s, "postTitle": s} for s in slugs]
    return {
        "team": {"name": title},
        "team_id": None,
        "posts": posts,
        "posts_meta": {"page": 1, "perPage": len(posts),
                       "totalCount": len(posts), "totalPages": 1},
        "latest_chapters": [],
    }


@dataclass
class TeamSnapshot:
    """لقطة أعمال الفريق: من النداء الرقمي الرسمي أو SSR احتياطًا."""
    team_id: Optional[int] = None
    team_name: str = ""
    team_avatar: str = ""
    posts: list = field(default_factory=list)            # كل أعمال الفريق
    latest_chapters: list = field(default_factory=list)  # مهجور — الإعلانات من فصول الأعمال مباشرة
    pages_fetched: int = 0
    posts_source: str = "ssr"                            # api | ssr | ...


# ───────────────────────────────────────────────────────────────
# هوية الفريق — قائمة الفرق الرسمية
# ───────────────────────────────────────────────────────────────
async def resolve_team(team_slug: str) -> dict | None:
    """يبحث الفريق بالسلاغ في /api/teams — يعيد {id, name, avatarUrl} أو None."""
    slug = str(team_slug or "").strip()
    if not slug:
        return None
    for page in range(1, MAX_TEAM_LIST_PAGES + 1):
        data = await _get_json(
            f"{AZORA_API}/api/teams?page={page}&perPage={TEAM_LIST_PER_PAGE}")
        teams = data.get("teams") or []
        for t in teams:
            if not isinstance(t, dict):
                continue
            if str(t.get("slug") or "") == slug:
                return {"id": t.get("id"), "name": str(t.get("name") or slug),
                        "avatarUrl": t.get("avatarUrl") or ""}
        total_pages = int(data.get("totalPages") or 1)
        if page >= total_pages or not teams:
            return None
        await asyncio.sleep(0.8)
    return None


# ───────────────────────────────────────────────────────────────
# أعمال الفريق — النداء الرسمي المُرقّم
# ───────────────────────────────────────────────────────────────
async def fetch_team_posts_page(team_id: int, page: int = 1,
                                per_page: int = TEAM_POSTS_PER_PAGE) -> dict:
    """صفحة واحدة من /api/teams/posts/{teamId} — تعيد {posts, meta}."""
    url = (f"{AZORA_API}/api/teams/posts/{int(team_id)}"
           f"?page={int(page)}&perPage={int(per_page)}")
    data = await _get_json(url)
    posts = data.get("posts") or []
    return {
        "posts": [p for p in posts if isinstance(p, dict)],
        "meta": {
            "page": int(data.get("page") or page),
            "perPage": int(data.get("perPage") or per_page),
            "totalCount": int(data.get("totalCount") or 0),
            "totalPages": int(data.get("totalPages") or 1),
        },
    }


async def fetch_all_team_posts(team_id: int) -> tuple[list, int]:
    """كل أعمال الفريق عبر النداء الرسمي المُرقّم — (posts, pages_fetched).
    أي فشل بعد الصفحة الأولى يُرفع (المزامنة تفشل نظيفة وتعيد في الدورة القادمة)
    حتى لا يُبنى كاش ناقص يُعامل كأنه كامل."""
    first = await fetch_team_posts_page(team_id, 1)
    posts: list = list(first["posts"])
    pages = 1
    total_pages = int(first["meta"]["totalPages"]) or 1
    seen: set = set()
    for p in posts:
        s = str(p.get("slug") or p.get("id") or "")
        if s:
            seen.add(s)
    while pages < min(total_pages, MAX_TEAM_PAGES):
        data = await fetch_team_posts_page(team_id, pages + 1)
        for p in data["posts"]:
            s = str(p.get("slug") or p.get("id") or "")
            if s and s in seen:
                continue  # حماية من تكرار الصفحة نفسها
            if s:
                seen.add(s)
            posts.append(p)
        pages += 1
        if not data["posts"]:
            break
        await asyncio.sleep(0.8)  # مهلة تربّت بين الصفحات
    return posts, pages


async def fetch_team_snapshot(team_slug: str, known_team_id: Optional[int] = None,
                              known_team_name: str = "") -> TeamSnapshot:
    """اللقطة الكاملة: معرف الفريق (المخزون ثم /api/teams) + الأعمال من
    النداء الرقمي الرسمي، وعند الفشل أعمال الصفحة الأولى من SSR."""
    snap = TeamSnapshot(team_id=known_team_id, team_name=known_team_name)
    team_id = known_team_id
    team_name = known_team_name
    if team_id is None:
        try:
            info = await resolve_team(team_slug)
        except AzoraError:
            info = None
        if info and info.get("id") is not None:
            team_id = int(info["id"])
            snap.team_id = team_id
            team_name = team_name or str(info.get("name") or "")
            snap.team_avatar = str(info.get("avatarUrl") or "")
    if team_name:
        snap.team_name = team_name
    if team_id is not None:
        try:
            posts, pages = await fetch_all_team_posts(int(team_id))
            snap.posts = posts
            snap.pages_fetched = pages
            snap.posts_source = "api"
            if not snap.team_name:
                snap.team_name = str(team_slug).upper()
            return snap
        except AzoraError as e:
            snap.posts_source = f"فشل النداء الرقمي: {str(e)[:80]}"
    page_data = await fetch_team_page(team_slug)
    if page_data.get("team_id") is not None and snap.team_id is None:
        snap.team_id = page_data["team_id"]
    if not snap.team_name:
        snap.team_name = str((page_data.get("team") or {}).get("name")
                             or str(team_slug).upper())
    snap.posts = list(page_data.get("posts") or [])
    snap.pages_fetched = 1
    return snap


async def fetch_team_page(team_slug: str, page: int = 1) -> dict:
    """صفحة الفريق SSR — تحقق هوية الفريق ومرجع احتياطي لأعمال الصفحة الأولى.
    ملاحظة موثقة: الواجهة الجديدة لا تعيد معرف الفريق في HTML."""
    url = f"{AZORA_BASE}/teams/{team_slug}"
    raw = await _get_text(url)
    return parse_team_page(raw)


# ───────────────────────────────────────────────────────────────
# فصول عمل واحد — عقد Iken الرسمي
# ───────────────────────────────────────────────────────────────
def _parse_chapter_list(chapters: list) -> list[dict]:
    """يوحّد شكل الفصول: [{id, number: str, slug, title, created_at, locked}]
    مرتبة تصاعديًا. قاعدة «المقفل» من سورس الإضافة الرسمي:
    isLocked أو isTimeLocked أو (سعر ≠ 0 وغير مشترى).
    الفصول المقفلة **منشورة** فعلًا (مجرد حجب دفع) — تدخل القائمة."""
    unified: list[dict] = []
    for ch in chapters or []:
        if not isinstance(ch, dict):
            continue
        number = ch.get("number")
        if number is None:
            continue
        locked = bool(ch.get("isLocked") or ch.get("isTimeLocked")
                      or (ch.get("price") not in (None, 0) and not ch.get("chapterPurchased")))
        unified.append({
            "id": ch.get("id"),
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


def parse_work_chapters(payload: dict) -> list[dict]:
    """تحليل رد /api/post — يدعم الرد القديم (فصول مضمّنة) والجديد
    (post بدون فصول + totalChapterCount في الأعلى)."""
    post = (payload or {}).get("post") or {}
    return _parse_chapter_list(post.get("chapters") or [])


def _chapters_from_payload(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    post = payload.get("post")
    if isinstance(post, dict) and isinstance(post.get("chapters"), list):
        return _parse_chapter_list(post["chapters"])
    if isinstance(payload.get("chapters"), list):
        return _parse_chapter_list(payload["chapters"])
    return []


async def fetch_work_chapters_by_id(post_id: int) -> list[dict]:
    """كل فصول عمل أزورا عبر /api/chapters?postId=… — المسار الذي تستخدمه
    إضافة أزورا الرسمية دائمًا (useChaptersApi) للقائمة الكاملة."""
    payload = await _get_json(f"{AZORA_API}/api/chapters?postId={int(post_id)}")
    return _chapters_from_payload(payload)


async def fetch_work_chapters(post_slug: str) -> list[dict]:
    """كل فصول عمل أزورا المنشورة — بخطوتي عقد Iken الرسمي:
    1) /api/post?postSlug=… → إن كانت الفصول مضمّنة وكاملة نستخدمها.
    2) إن كان totalChapterCount أكبر من المضمّن (حالة أزورا الفعلية:
       الفصول غير مضمّنة إطلاقًا) → /api/chapters?postId=… القائمة الكاملة.
    السلاغ يُرمَّز دائمًا (أسماء أعمال أزورا تحتوي فواصل عليا مثل
    serim's-iron-rule — يجب أن تصل %27 لا ' خام)."""
    slug_enc = quote(str(post_slug or "").strip(), safe="")
    payload = await _get_json(f"{AZORA_API}/api/post?postSlug={slug_enc}")
    post = (payload or {}).get("post") or {}
    chapters = _parse_chapter_list(post.get("chapters") or [])
    total_raw = payload.get("totalChapterCount", post.get("totalChapterCount"))
    try:
        total = int(total_raw) if total_raw is not None else None
    except (TypeError, ValueError):
        total = None
    post_id = post.get("id")
    need_fallback = post_id is not None and (
        (total is not None and len(chapters) < total)
        or (total is None and not chapters))
    if need_fallback:
        full = await fetch_work_chapters_by_id(int(post_id))
        if len(full) > len(chapters):
            chapters = full
    return chapters


def chapter_url(post_slug: str, chapter_slug: str) -> str:
    if chapter_slug:
        return f"{AZORA_BASE}/series/{post_slug}/{chapter_slug}"
    return f"{AZORA_BASE}/series/{post_slug}"
