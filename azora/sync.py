# ═══════════════════════════════════════════════════════════════
# ⚙️ محرك مزامنة أزورا — يعمل دوريًا في الخلفية (افتراضي كل 10 دقائق):
#
#   1) يعرف هوية الفريق ثم يقصف /api/teams/posts/{teamId} لاكتشاف
#      أعمال جديدة وتحديث الأعداد.
#   2) خط الأساس: أول تشغيل، أو بعد أي تغيير إجباري لإصدار المنطق
#      (SYNC_VERSION)، أو عند تغيير الفريق — يُسجّل الوضع الحالي كله
#      (أعمال + فصول + أعلى رقم لكل عمل) **بصمت تام** بلا إعلانات.
#   3) قرار الإعلان عن فصل:
#      • رقمه أعلى حرفيًا من أعلى رقم مخزّن لذلك العمل (top_numbers)،
#      • وتاريخ نشره إما غير متاح أو حديث (أحدث من آخر مزامنة ناجحة
#        وهامش 10 دقائق، ولا يتجاوز عمره RECENCY_HOURS ساعة)،
#      • ودفعته لعمل واحد ≤ PER_WORK_BRAKE وإجمالي الدورة ≤ GLOBAL_BRAKE.
#      كل ما عدا ذلك يُسجَّل معروفًا **بصمت** ولا يُعاد النظر فيه أبدًا
#      — لا يُعلن فصل قديم مهما تغيّرت هويات الموقع أو تواريخه.
#   4) العمل المرتبط حديثًا يُسجَّل فصوله الحالية بصمت أول مرة،
#      والإعلان يبدأ من فصله القادم فقط.
#   5) كاش أرقام الفصول يتحدث من الجلب — أساس بوابة «الفصل المنشور
#      فقط» في التسجيل.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from discord.ext import tasks

from state import bot
from helpers.core import load_works, save_works
from database import DatabaseUnavailableError
from azora import client, store
from azora.client import AzoraError, chapter_url
from azora.gating import normalize_chapter
from ui import cards


ANNOUNCE_GIF_URL = "https://iili.io/n3p13R1.gif"
SYNC_VERSION = 8              # رفع هذا الرقم يجبر خط أساس جديد صامت عند الإقلاع
RECENCY_HOURS = 24            # لا يُعلن فصل تجاوز عمره هذا مهما كانت الظروف
ANNOUNCE_GRACE_MINUTES = 10   # هامش حول آخر مزامنة ناجحة
PER_WORK_BRAKE = 5            # فصول أعلى من المخزّن لعمل واحد في دورة = سقف الدفعة الطبيعية
GLOBAL_BRAKE = 15             # إجمالي مرشحي الإعلان في دورة = سقف الدورة الطبيعية
MAX_ANNOUNCE_PER_CYCLE = 30
WORK_FETCH_PAUSE = 1.0
SEND_PAUSE = 1.5
_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)
_MISSING = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value) -> datetime | None:
    """تاريخ من ISO أو ثانية/ميلي ثانية رقمية — None عند أي تعذر."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        if ts > 1e9:
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                return None
        return None
    s = str(value).strip()
    if s.isdigit():
        return _parse_iso(int(s))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _work_display_line(work: dict) -> str:
    link = work.get("azora") or {}
    name = work.get("name", "")
    en = link.get("title_en") or ""
    return name if (not en or en == name) else f"{name} ({en})"


def _chapter_key(ch: dict):
    """هوية الفصل المضادة للتكرار: المعرف الرقمي إن وجد وإلا السلاغ+الرقم."""
    cid = ch.get("id")
    if isinstance(cid, int):
        return cid
    return f"{ch.get('slug') or ''}|{normalize_chapter(ch.get('number', ''))}"


def _max_number(chapters: list[dict]) -> float | None:
    """أعلى رقم فصل رقمي في القائمة — None إن لم يوجد أي رقم رقمي."""
    best = None
    for c in chapters:
        try:
            f = float(normalize_chapter(c.get("number", "")))
        except (TypeError, ValueError):
            continue
        if best is None or f > best:
            best = f
    return best


def _count_of(post: dict) -> int:
    counts = post.get("_count") or {}
    if not isinstance(counts, dict):
        return 0
    for key in ("chapters", "publishedChapters"):
        try:
            v = counts.get(key)
            if v is not None:
                return max(0, int(v))
        except (TypeError, ValueError):
            continue
    return 0


def build_announcement_card(work: dict, chapter: dict, uploader: str) -> cards.Card:
    """بطاقة إعلان نزول الفصل — ذهبية بنفس لغة التصميم، معلومات لكل سطر."""
    link = work.get("azora") or {}
    display = _work_display_line(work)
    cover = link.get("cover") or None
    number = chapter.get("number", "?")
    ch_link = chapter_url(link.get("slug", ""), chapter.get("slug", ""))
    work_link = f"{client.AZORA_BASE}/series/{link.get('slug', '')}"

    children: list = [
        cards.header(["## نزول فصل جديد", f"**{display}**"], cover),
    ]
    role_id = work.get("role_id")
    if role_id:
        children.append(cards.text(f"<@&{int(role_id)}>"))
    children += [
        cards.sep(2),
        cards.text(
            f"**الفصل:** {number}\n"
            f"**النشر:** أزورا — فريق {link.get('team_name', 'COOKIES')}\n"
            f"**أضافه على الموقع:** {uploader or '—'}"
        ),
        cards.sep(),
        cards.row(
            cards.link_btn("افتح الفصل على أزورا", ch_link),
            cards.link_btn("صفحة العمل", work_link),
        ),
        cards.sep(),
        cards.text("الفصل نزل — يمكنك تسجيل فصلك الآن عبر /تسجيل."),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    return cards.Card(cards.ACCENT_GOLD, *children)


async def _work_chapters(work: dict, known: dict) -> list[dict]:
    """قائمة فصول كاملة لعمل مرتبط: بالمعرف أولاً ثم بالسلاغ،
    وتُصلح post_id الناقص في العمل من كاش الفريق."""
    link = work.get("azora") or {}
    slug = str(link.get("slug") or "")
    post_id = link.get("post_id")
    if not post_id:
        cached_id = (known.get(slug) or {}).get("post_id")
        if cached_id is not None:
            work["azora"]["post_id"] = cached_id
            post_id = cached_id
    if post_id is not None:
        return await client.fetch_work_chapters_by_id(int(post_id))
    return await client.fetch_work_chapters(slug)


# ───────────────────────────────────────────────────────────────
# الدورة الكاملة
# ───────────────────────────────────────────────────────────────
async def run_sync_cycle(bot_obj, manual: bool = False) -> dict:
    """دورة مزامنة واحدة. تعيد ملخصًا للعرض في /أزورا.
    تعيد {ok: False, error: "..."} عند أي فشل مع تسجيله في الحالة."""
    state = await store.load_state()
    if not state.get("enabled") and not manual:
        return {"ok": False, "skipped": True, "error": "النظام معطّل."}

    if not state.get("last_ok_sync_at") and state.get("last_sync_ok") and state.get("last_sync_at"):
        state["last_ok_sync_at"] = state["last_sync_at"]

    works = await load_works()  # قد يرفع DatabaseUnavailableError — قصدي: لا مزامنة بلا DB

    team_slug = state.get("team_slug") or client.DEFAULT_TEAM_SLUG
    try:
        snap = await client.fetch_team_snapshot(
            team_slug,
            known_team_id=state.get("team_id"),
            known_team_name=state.get("team_name") or "",
        )
    except AzoraError as e:
        await store.update_state_fields({
            "last_sync_at": _now_iso(), "last_sync_ok": False,
            "last_error": str(e)[:300], "last_error_at": _now_iso()})
        return {"ok": False, "error": str(e)}

    if snap.team_id is not None and snap.team_id != state.get("team_id"):
        state["team_id"] = snap.team_id
    if snap.team_name:
        state["team_name"] = snap.team_name
    team_name = snap.team_name or "COOKIES"

    cache = await store.load_cache()
    known: dict = cache["works"]
    seen: set = set(cache.get("seen_chapter_ids", []))
    tops: dict = dict(cache.get("top_numbers") or {})
    result = {"ok": True, "announced": 0, "auto_added": 0, "refreshed": 0,
              "silent_registered": 0, "team_works": len(snap.posts),
              "team_name": team_name, "baseline": False, "errors": [],
              "posts_source": snap.posts_source}
    if snap.posts_source != "api":
        result["errors"].append(
            "قائمة أعمال الفريق جاءت جزئية من صفحة الفريق — النداء الرقمي غير متاح "
            "الآن؛ ستُكمل القائمة في دورة قادمة.")

    try:
        state_version = int(state.get("sync_version") or 0)
    except (TypeError, ValueError):
        state_version = 0

    # ── 1) خط الأساس الصامت: أول تشغيل أو تغيّر إصدار المنطق ──
    if (not state.get("baseline_done")) or state_version < SYNC_VERSION:
        for p in snap.posts:
            slug = str(p.get("slug") or "")
            if slug and slug not in known:
                known[slug] = {
                    "post_id": p.get("id"), "title_en": p.get("postTitle") or "",
                    "cover": p.get("featuredImage") or "",
                    "chapter_count": _count_of(p),
                    "updated_at": p.get("updatedAt") or "",
                    "first_seen": _now_iso(),
                }
        linked = [w for w in works if (w.get("azora") or {}).get("slug")]
        for w in linked:
            slug = str(w["azora"]["slug"])
            try:
                chapters = await _work_chapters(w, known)
            except AzoraError as e:
                result["errors"].append(f"تعذر جلب فصول {slug}: {str(e)[:120]}")
                await asyncio.sleep(WORK_FETCH_PAUSE)
                continue
            mt = _max_number(chapters)
            if mt is not None and (tops.get(slug) is None or mt > tops[slug]):
                tops[slug] = mt
            seen |= {_chapter_key(c) for c in chapters}
            await store.save_chapters_entry(slug, {
                "numbers": [c["number"] for c in chapters],
                "count": len(chapters),
                "updated_at": (known.get(slug) or {}).get("updated_at") or "",
                "team_name": team_name,
            })
            result["refreshed"] += 1
            await asyncio.sleep(WORK_FETCH_PAUSE)
        state["baseline_done"] = True
        state["sync_version"] = SYNC_VERSION
        if snap.posts_source == "api":
            state["listing_v2"] = True
        state["last_ok_sync_at"] = _now_iso()
        state["last_sync_at"] = _now_iso()
        state["last_sync_ok"] = True
        state["last_error"] = None
        await store.save_state(state)
        await store.save_cache({"works": known,
                                "seen_chapter_ids": list(seen)[-20000:],
                                "top_numbers": tops})
        result["baseline"] = True
        result["baseline_count"] = len(known)
        return result

    # ── 2) اكتشاف الأعمال الجديدة + تحديث الكاش ──
    # أ) أول دورة بعد اكتمال الفهرس = إعادة خط أساس: كل ما يظهر جديدًا
    #    يُسجّل معروفًا **دون إضافة** للبوت.
    # ب) أي دفعة جديدة > 10 أعمال في دورة واحدة تُسجّل معروفة دون إضافة
    #    (توسّع فهرس وليست أعمالًا نزلت الآن) + ملاحظة للوحة.
    # ج) غير ذلك: الجديد (1-10) يُضاف تلقائيًا إن كانت الإضافة مفعلة.
    entries_by_slug: dict[str, dict] = {}
    for p in snap.posts:
        slug = str(p.get("slug") or "")
        if not slug:
            continue
        entries_by_slug[slug] = {
            "post_id": p.get("id"), "title_en": p.get("postTitle") or "",
            "cover": p.get("featuredImage") or "",
            "chapter_count": _count_of(p),
            "updated_at": p.get("updatedAt") or "",
        }

    new_slugs = [s for s in entries_by_slug if s not in known]
    works_changed = False
    listing_v2 = bool(state.get("listing_v2"))
    backfill = (not listing_v2) or len(new_slugs) > 10

    if backfill:
        for slug in new_slugs:
            entry = dict(entries_by_slug[slug])
            entry["first_seen"] = _now_iso()
            known[slug] = entry
        if not listing_v2:
            state["listing_v2"] = True
            result["rebaseline"] = len(new_slugs)
        else:
            result["backfilled"] = len(new_slugs)
            result["errors"].append(
                f"ظهر {len(new_slugs)} عملًا جديدًا في دفعة واحدة — سُجّلوا معروفين "
                "دون إضافة تلقائية احتياطًا؛ اربط ما تريد منها من لوحة أزورا.")
    else:
        for slug in new_slugs:
            entry = dict(entries_by_slug[slug])
            entry["first_seen"] = _now_iso()
            known[slug] = entry
            e = entries_by_slug[slug]
            if state.get("auto_add_new_works", True):
                existing = next((w for w in works if (w.get("azora") or {}).get("slug") == slug), None)
                if existing is None and get_by_title(works, e["title_en"]) is None:
                    works.append({
                        "name": e["title_en"] or slug,
                        "paid_start": None,
                        "active": True,
                        "azora": {
                            "slug": slug, "post_id": e["post_id"],
                            "title_en": e["title_en"], "cover": e["cover"],
                            "team_name": team_name,
                            "linked_at": _now_iso(), "linked_by": "azora-sync",
                        },
                    })
                    works_changed = True
                    result["auto_added"] += 1

    # تحديث بيانات المعروف (العداد/الغلاف/الاسم) لكل الأعمال المكتشفة
    for slug, e in entries_by_slug.items():
        if slug in known:
            known[slug].update(e)

    if works_changed:
        await save_works(works)

    # ── 3) الإعلانات — الفصل الحديث فقط ──
    announce_on = state.get("announcements_enabled", True)
    announce_channel_id = state.get("announce_channel_id")
    channel = bot_obj.get_channel(announce_channel_id) if announce_channel_id else None
    if announce_on and channel is None and announce_channel_id:
        result["errors"].append("قناة الإعلانات المحفوظة لم تعد موجودة — أعد تحديدها من /أزورا.")

    last_ok = _parse_iso(state.get("last_ok_sync_at"))
    cutoff = last_ok - timedelta(minutes=ANNOUNCE_GRACE_MINUTES) if last_ok else None
    recency_floor = datetime.now(timezone.utc) - timedelta(hours=RECENCY_HOURS)

    linked = [w for w in works if (w.get("azora") or {}).get("slug")]
    pending: list[tuple[datetime, dict, dict]] = []
    fixed_post_ids = False

    for w in linked:
        slug = str(w["azora"]["slug"])
        before_id = (w.get("azora") or {}).get("post_id")
        try:
            chapters = await _work_chapters(w, known)
        except AzoraError as e:
            result["errors"].append(f"تعذر جلب فصول {slug}: {str(e)[:120]}")
            await asyncio.sleep(WORK_FETCH_PAUSE)
            continue
        if before_id is None and (w.get("azora") or {}).get("post_id") is not None:
            fixed_post_ids = True

        stored_top = tops.get(slug, _MISSING)
        if stored_top is _MISSING:
            # أول رؤية لهذا العمل: تسجيل صامت كامل — الإعلان من فصله القادم فقط
            mt = _max_number(chapters)
            if mt is not None:
                tops[slug] = mt
            seen |= {_chapter_key(c) for c in chapters}
            result["silent_registered"] += len(chapters)
        else:
            candidates: list[dict] = []
            for c in chapters:
                k = _chapter_key(c)
                if k in seen:
                    continue
                try:
                    f = float(normalize_chapter(c.get("number", "")))
                except (TypeError, ValueError):
                    f = None
                if f is None:
                    # رقم غير رقمي (خاصة/إضافي): لا يُعلن إلا بتاريخ نشر حديث موثق
                    created = _parse_iso(c.get("created_at"))
                    fresh_time = (created is not None and created >= recency_floor
                                  and (cutoff is None or created > cutoff))
                    if fresh_time:
                        candidates.append(c)
                    else:
                        seen.add(k)
                        result["silent_registered"] += 1
                elif stored_top is None or f > stored_top:
                    candidates.append(c)
                else:
                    seen.add(k)

            mt = _max_number(chapters)
            if mt is not None:
                tops[slug] = mt if (stored_top is None or mt > stored_top) else stored_top

            if candidates:
                if channel is None or not announce_on:
                    seen |= {_chapter_key(c) for c in candidates}
                    result["silent_registered"] += len(candidates)
                elif len(candidates) > PER_WORK_BRAKE:
                    seen |= {_chapter_key(c) for c in candidates}
                    result["silent_registered"] += len(candidates)
                    result["errors"].append(
                        f"{w.get('name')}: ظهر {len(candidates)} فصلًا دفعة واحدة — "
                        "سُجلوا بلا إعلان.")
                else:
                    for c in candidates:
                        created = _parse_iso(c.get("created_at"))
                        if created is not None and cutoff and created <= cutoff:
                            seen.add(_chapter_key(c))
                            result["silent_registered"] += 1
                            continue
                        if created is not None and created < recency_floor:
                            seen.add(_chapter_key(c))
                            result["silent_registered"] += 1
                            continue
                        pending.append((created or _FAR_FUTURE, w, c))

        await store.save_chapters_entry(slug, {
            "numbers": [c["number"] for c in chapters],
            "count": len(chapters),
            "updated_at": (known.get(slug) or {}).get("updated_at") or "",
            "team_name": team_name,
        })
        result["refreshed"] += 1
        await asyncio.sleep(WORK_FETCH_PAUSE)

    if fixed_post_ids:
        await save_works(works)

    if len(pending) > GLOBAL_BRAKE:
        for _, w, c in pending:
            seen.add(_chapter_key(c))
        result["silent_registered"] += len(pending)
        result["errors"].append(
            f"ظهر {len(pending)} فصلًا جديدًا في دورة واحدة — سُجلوا بلا إعلان.")
        pending = []

    pending.sort(key=lambda t: t[0])
    announced_now = 0
    for created, w, c in pending:
        if announced_now >= MAX_ANNOUNCE_PER_CYCLE:
            break
        try:
            try:
                await channel.send(ANNOUNCE_GIF_URL)
            except Exception:
                pass
            await channel.send(view=build_announcement_card(
                w, c, ((c.get("createdBy") or {}).get("name") or "")))
            seen.add(_chapter_key(c))
            announced_now += 1
            await asyncio.sleep(SEND_PAUSE)
        except Exception as e:
            result["errors"].append(
                f"تعذر إرسال إعلان لـ {w.get('name')} فصل {c.get('number')}: {type(e).__name__}")
            break
    result["announced"] += announced_now
    leftover = len(pending) - announced_now
    if leftover > 0:
        result["errors"].append(
            f"تبقى {leftover} فصلًا في طابور الإعلانات — تُرسل في الدورات التالية بالترتيب.")
    # ── 4) حفظ الحالة والكاش ──
    state["team_name"] = team_name
    state["last_sync_at"] = _now_iso()
    state["last_sync_ok"] = True
    state["last_error"] = "؛ ".join(result["errors"][:3]) if result["errors"] else None
    if result["errors"]:
        state["last_error_at"] = _now_iso()
    state["last_ok_sync_at"] = _now_iso()
    if result["announced"]:
        state["announced_count"] = int(state.get("announced_count") or 0) + result["announced"]
    if result["auto_added"]:
        state["auto_added_count"] = int(state.get("auto_added_count") or 0) + result["auto_added"]
    await store.save_state(state)
    await store.save_cache({"works": known,
                            "seen_chapter_ids": list(seen)[-20000:],
                            "top_numbers": tops})
    return result


def get_by_title(works: list, title: str) -> dict | None:
    """منع ازدواجية الإضافة التلقائية: عمل بنفس الاسم الإنجليزي موجود؟"""
    if not title:
        return None
    t = title.strip().lower()
    for w in works:
        if str(w.get("name", "")).strip().lower() == t:
            return w
        if str((w.get("azora") or {}).get("title_en", "")).strip().lower() == t:
            return w
    return None


# ───────────────────────────────────────────────────────────────
# الحلقة الدورية — لا تنكسر أبدًا، وتتبع تغيّر المدة من الإعدادات
# ───────────────────────────────────────────────────────────────
@tasks.loop(minutes=10)
async def azora_sync_loop():
    try:
        state = await store.load_state()
        wanted = max(5, int(state.get("sync_interval_minutes") or 10))
        if azora_sync_loop.minutes != wanted:
            azora_sync_loop.minutes = wanted
        if not state.get("enabled"):
            return
        result = await run_sync_cycle(bot)
        if result.get("ok"):
            tag = "أساس" if result.get("baseline") else (
                f"أضيف {result['auto_added']} • أعلن {result['announced']} • "
                f"صامت {result.get('silent_registered', 0)} • حدّث {result['refreshed']}")
            print(f"[AZORA] مزامنة ناجحة ({result.get('team_name')}): {tag}")
        else:
            print(f"[AZORA] فشلت المزامنة: {result.get('error')}")
    except DatabaseUnavailableError as e:
        print(f"[AZORA] تخطيت الدورة — قاعدة البيانات غير متاحة: {e}")
    except Exception as e:
        import traceback
        print(f"[AZORA] خطأ غير متوقع في المزامنة: {e}")
        traceback.print_exc()


async def start_sync_loop():
    """تُستدعى من on_ready — تشغيل آمن بلا تكرار."""
    if azora_sync_loop.is_running():
        return
    try:
        state = await store.load_state()
        azora_sync_loop.change_interval(minutes=max(5, int(state.get("sync_interval_minutes") or 10)))
    except Exception:
        pass
    azora_sync_loop.start()
    print("[AZORA] حلقة المزامنة تعمل الآن.")
