# ═══════════════════════════════════════════════════════════════
# 🌐 عميل أزورا — عقد الـAPI الموثّق من مصدرين حقيقيين:
#
#   أ) سورس إضافة أزورا الرسمية (keiyoushi/extensions-source → قالب
#      Iken) التي تعمل على azorafly.com منذ سنوات.
#   ب) الالتقاط الحي لردود موقع أزورا نفسه (SSR + JS الواجهة).
#
#   المصادر الثلاثة للبيانات:
#
#   1) أعمال الفريق (كلها بترقيم رسمي):
#      GET {api}/api/teams/posts/{teamId}?page=N&perPage=24
#      → {posts:[{id, slug, postTitle, featuredImage, updatedAt,
#         _count:{chapters}}], totalCount, page, perPage, totalPages}
#      هذا هو النداء نفسه الذي يستخدمه موقع أزورا لزر «تحميل المزيد»
#      في صفحة الفريق — teamId يُستخرج من خصائص صفحة الفريق SSR.
#
#   2) صفحة الفريق (SSR): GET {base}/teams/{team_slug}
#      صفحة Astro تضمّن astro-island props: team + teamId + stats +
#      postsData (24 عملًا للصفحة الأولى فقط) + chaptersData
#      (أحدث 20 فصلًا منشورًا للفريق مع العمل التابع له).
#      ⚠️ صفحة الفريق **لا تدعم** ?page=N — ثبُت أن أي صفحة غير الأولى
#      تعيد 404، لذلك القائمة الكاملة تأتي من النداء الرقمي أعلاه.
#
#   3) فصول عمل واحد — نقطتان حسب عقد Iken الرسمي:
#      GET {api}/api/post?postSlug={slug}
#      → {totalChapterCount, post:{id, slug, ..., chapters?}}
#      ⚠️ أزورا **لا تضمّن الفصول** في هذا الرد (chapters فارغ أو مقصوص)
#      بينما totalChapterCount هو العدد الحقيقي — والإضافة الرسمية
#      تتعامل مع ذلك بالتحويل تلقائيًا إلى:
#      GET {api}/api/chapters?postId={post.id} → {post:{chapters:[...]}}
#      نطبّق نفس المنطق حرفيًا.
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
    {team, team_id, posts: [...], posts_meta: {...}, latest_chapters: [...]}"""
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
            "team_id": data.get("teamId"),
            "posts": posts_data.get("posts", []) or [],
            "posts_meta": {
                "page": posts_data.get("page", 1),
                "perPage": posts_data.get("perPage", TEAM_POSTS_PER_PAGE),
                "totalCount": posts_data.get("totalCount", 0),
                "totalPages": posts_data.get("totalPages", 1),
            },
            "latest_chapters": chapters_data.get("chapters", []) or [],
        }
    raise AzoraUnavailableError("لم أجد بيانات الفريق داخل الصفحة — ربما تغيرت بنية موقع أزورا.")


@dataclass
class TeamSnapshot:
    """لقطة كاملة لأعمال الفريق:
    posts من النداء الرقمي الرسمي (كل الصفحات) أو من SSR عند فشله."""
    team_id: Optional[int] = None
    team_name: str = ""
    team_avatar: str = ""
    posts: list = field(default_factory=list)            # كل أعمال الفريق
    latest_chapters: list = field(default_factory=list)  # أحدث فصول منشورة (صفحة 1 SSR)
    pages_fetched: int = 0
    posts_source: str = "ssr"                            # api | ssr


# ───────────────────────────────────────────────────────────────
# صفحة الفريق (SSR) — الفريق + الصفحة الأولى + تغذية أحدث الفصول
# ───────────────────────────────────────────────────────────────
async def fetch_team_page(team_slug: str, page: int = 1) -> dict:
    """صفحة الفريق SSR — تُستخدم للتحقق من الفريق وللب البيانات الأولية.
    ملاحظة موثقة: الموقع لا يدعم ?page=N (تعيد 404) — لا تستخدمها للترقيم."""
    url = f"{AZORA_BASE}/teams/{team_slug}"
    raw = await _get_text(url)
    return parse_team_page(raw)


# ───────────────────────────────────────────────────────────────
# أعمال الفريق — النداء الرسمي المُرقّم (نفس نداء «تحميل المزيد» بالموقع)
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


async def fetch_team_snapshot(team_slug: str) -> TeamSnapshot:
    """اللقطة الكاملة: الهوية من SSR + الأعمال من النداء الرقمي الرسمي،
    وإن فشل النداء الرقمي نعود لعمال SSR للصفحة الأولى (قائمة جزئية)
    مع تعليم المصدر حتى تظهر الملاحظة في لوحة أزورا."""
    first = await fetch_team_page(team_slug, 1)
    snap = TeamSnapshot(
        team_id=first.get("team_id"),
        team_name=str((first.get("team") or {}).get("name") or team_slug).upper(),
        team_avatar=(first.get("team") or {}).get("avatarUrl") or "",
        posts=list(first.get("posts") or []),
        latest_chapters=list(first.get("latest_chapters") or []),
        pages_fetched=1,
        posts_source="ssr",
    )
    team_id = snap.team_id
    if team_id is None:
        return snap  # لا نعرف رقم الفريق — نكتفي بعمال الصفحة الأولى
    try:
        posts, pages = await fetch_all_team_posts(int(team_id))
    except AzoraError as e:
        # النداء الرقمي فشل كليًا — نعود للصفحة الأولى من SSR بدل التعطيل
        snap.posts_source = f"ssr (فشل النداء الرقمي: {str(e)[:80]})"
        return snap
    snap.posts = posts
    snap.pages_fetched = pages
    snap.posts_source = "api"
    return snap


# ───────────────────────────────────────────────────────────────
# فصول عمل واحد — عقد Iken الرسمي بخطوتيه
# ───────────────────────────────────────────────────────────────
def _parse_chapter_list(chapters: list) -> list[dict]:
    """يوحّد شكل الفصول: [{number: str, slug, title, created_at, locked}]
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
        full = await _get_json(f"{AZORA_API}/api/chapters?postId={int(post_id)}")
        full_post = (full or {}).get("post") or {}
        full_chapters = _parse_chapter_list(full_post.get("chapters") or [])
        if len(full_chapters) > len(chapters):
            chapters = full_chapters
    return chapters


def chapter_url(post_slug: str, chapter_slug: str) -> str:
    if chapter_slug:
        return f"{AZORA_BASE}/series/{post_slug}/{chapter_slug}"
    return f"{AZORA_BASE}/series/{post_slug}"
