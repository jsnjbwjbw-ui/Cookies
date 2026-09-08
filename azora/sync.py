# ═══════════════════════════════════════════════════════════════
# ⚙️ محرك مزامنة أزورا — يعمل دوريًا في الخلفية (افتراضي كل 10 دقائق):
#
#   1) يقصف كل صفحات أعمال الفريق عبر النداء الرسمي المُرقّم
#      /api/teams/posts/{teamId} → يكتشف الأعمال الجديدة ويحدّث الأعداد.
#   2) أول تشغيل = خط أساس: يُسجّل كل أعمال الفريق الحالية كمعروفة
#      **دون** إضافتها للبوت ودون إعلانات (بما طلبه المستخدم صراحة)،
#      ثم تُضاف فقط الأعمال التي تنزل **بعد** التفعيل.
#      وحارسان إضافيان: أول دورة بعد التحديث الذي وسّع الفهرس من 24
#      عملًا إلى الكامل = إعادة خط أساس، وأي دفعة جديدة تتجاوز 10
#      أعمال في دورة واحدة لا تُضاف تلقائيًا — حماية من إضافة القديم.
#   3) يعيد جلب أرقام فصول الأعمال **المرتبطة** عندما يتغير عددها —
#      وتلك الأرقام هي القاعدة التي تُقيّد /تسجيل (فصل منشور فقط).
#   4) يعلن الفصول الجديدة في القناة المحددة للأعمال المرتبطة فقط.
#
#   كل فشل يُسجَّل في حالة النظام ويظهر في /أزورا — الحلقة لا تنكسر
#   أبدًا، وقاعدة البيانات محمية (فشل DB يلغي الدورة فورًا).
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
from ui import cards


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _work_display_line(work: dict) -> str:
    link = work.get("azora") or {}
    name = work.get("name", "")
    en = link.get("title_en") or ""
    return name if (not en or en == name) else f"{name} ({en})"


def _find_linked_work(works: list, azora_slug: str) -> dict | None:
    for w in works:
        link = w.get("azora") or {}
        if link.get("slug") == azora_slug:
            return w
    return None


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
        cards.text("سجّل فصولك المنجزة عبر /تسجيل بعد اكتمال رفع الفصل."),
        cards.sep(),
        cards.text(f"-# {cards.BOT_SIGNATURE}"),
    ]
    return cards.Card(cards.ACCENT_GOLD, *children)


# ───────────────────────────────────────────────────────────────
# الدورة الكاملة
# ───────────────────────────────────────────────────────────────
async def run_sync_cycle(bot_obj, manual: bool = False) -> dict:
    """دورة مزامنة واحدة. تعيد ملخصًا للعرض في /أزورا.
    تعيد {ok: False, error: "..."} عند أي فشل مع تسجيله في الحالة."""
    state = await store.load_state()
    if not state.get("enabled") and not manual:
        return {"ok": False, "skipped": True, "error": "النظام معطّل."}

    works = await load_works()  # قد يرفع DatabaseUnavailableError — قصدي: لا مزامنة بلا DB

    try:
        snap = await client.fetch_team_snapshot(state.get("team_slug") or client.DEFAULT_TEAM_SLUG)
    except AzoraError as e:
        await store.update_state_fields({
            "last_sync_at": _now_iso(), "last_sync_ok": False,
            "last_error": str(e)[:300], "last_error_at": _now_iso()})
        return {"ok": False, "error": str(e)}

    cache = await store.load_cache()
    known: dict = cache["works"]
    seen: set = set(cache.get("seen_chapter_ids", []))
    result = {"ok": True, "announced": 0, "auto_added": 0, "refreshed": 0,
              "team_works": len(snap.posts), "team_name": snap.team_name,
              "baseline": False, "errors": []}
    if snap.posts_source != "api":
        result["errors"].append(
            "قائمة أعمال الفريق جاءت من صفحة الفريق (جزئية) — النداء الرقمي غير متاح الآن؛ "
            "ستُكمل القائمة في دورة قادمة.")
    if snap.team_id is not None:
        state["team_id"] = snap.team_id

    team_name = snap.team_name or "COOKIES"

    # ── 1) خط الأساس (أول دورة بعد التفعيل): تسجيل المعروف فقط ──
    if not state.get("baseline_done"):
        for p in snap.posts:
            slug = str(p.get("slug") or "")
            if slug and slug not in known:
                known[slug] = {
                    "post_id": p.get("id"), "title_en": p.get("postTitle") or "",
                    "cover": p.get("featuredImage") or "",
                    "chapter_count": (p.get("_count") or {}).get("chapters", 0),
                    "updated_at": p.get("updatedAt") or "",
                    "first_seen": _now_iso(),
                }
        seen |= {int(c.get("id")) for c in snap.latest_chapters
                 if isinstance(c.get("id"), int)}
        state["baseline_done"] = True
        state["team_name"] = team_name
        state["last_sync_at"] = _now_iso()
        state["last_sync_ok"] = True
        state["last_error"] = None
        await store.save_state(state)
        await store.save_cache({"works": known, "seen_chapter_ids": list(seen)[-400:]})
        result["baseline"] = True
        result["baseline_count"] = len(known)
        return result

    # ── 2) اكتشاف الجديد + تحديث الكاش ──
    # أ) أول دورة بعد التحديث الذي وسّع الفهرس (listing_v2) = إعادة خط
    #    أساس: كل ما يظهر جديدًا يُسجّل معروفًا **دون إضافة** للبوت.
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
            "chapter_count": (p.get("_count") or {}).get("chapters", 0),
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

    # ── 3) إعلانات الفصول الجديدة (للأعمال المرتبطة فقط) ──
    last_sync = _parse_iso(state.get("last_sync_at"))
    announce_channel_id = state.get("announce_channel_id")
    channel = bot_obj.get_channel(announce_channel_id) if announce_channel_id else None
    if state.get("announcements_enabled", True) and channel is None and announce_channel_id:
        result["errors"].append("قناة الإعلانات المحفوظة لم تعد موجودة — أعد تحديدها من /أزورا.")

    for ch in snap.latest_chapters:
        cid = ch.get("id")
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        created = _parse_iso(ch.get("createdAt"))
        # مهلة سماح 10 دقائق: تحمي من فروق ساعات أزورا/الاستضافة عن حافة المزامنة،
        # ومن تكرار الإعلان يحمي تسجيل المعرفات في seen (يبقى 400 فصل أخيرًا).
        if last_sync and created and created <= last_sync - timedelta(minutes=10):
            continue  # فصل قديم ظهر في التغذية — لا إعلان له
        post = ch.get("mangaPost") or {}
        slug = str(post.get("slug") or "")
        work = _find_linked_work(works, slug)
        if not work or not channel:
            continue
        try:
            await channel.send(view=build_announcement_card(
                work, ch, ((ch.get("createdBy") or {}).get("name") or "")))
            result["announced"] += 1
        except Exception as e:
            result["errors"].append(f"تعذر إرسال إعلان لـ {slug} فصل {ch.get('number')}: {type(e).__name__}")

    # ── 4) تحديث كاش أرقام الفصول للأعمال المرتبطة ──
    limit = 30 if manual else 15
    refreshed = 0
    linked_slugs = []
    for w in works:
        link = w.get("azora") or {}
        if link.get("slug"):
            linked_slugs.append((w, str(link["slug"])))
    for _w, slug in linked_slugs:
        if refreshed >= limit:
            result["errors"].append("توجد أعمال مرتبطة لم يُحدَّث كاشها هذه الدورة — ستُحدَّث في القادمة.")
            break
        team_entry = known.get(slug) or {}
        cached = await store.get_cached_chapters(slug)
        team_count = team_entry.get("chapter_count")
        cached_count = (cached or {}).get("count")
        force = manual and not cached
        if cached and team_count is not None and cached_count == team_count:
            continue  # لا تغيير في العدد — توفير طلبات
        try:
            chapters = await client.fetch_work_chapters(slug)
        except AzoraError as e:
            result["errors"].append(f"تعذر تحديث فصول {slug}: {e}")
            await asyncio.sleep(1.5)
            continue
        await store.save_chapters_entry(slug, {
            "numbers": [c["number"] for c in chapters],
            "count": len(chapters),
            "updated_at": team_entry.get("updated_at") or "",
            "team_name": team_name,
        })
        refreshed += 1
        await asyncio.sleep(1.5)

    result["refreshed"] = refreshed

    # ── 5) حفظ الحالة والكاش ──
    state["team_name"] = team_name
    state["last_sync_at"] = _now_iso()
    state["last_sync_ok"] = True
    state["last_error"] = "؛ ".join(result["errors"][:3]) if result["errors"] else None
    if result["errors"]:
        state["last_error_at"] = _now_iso()
    if result["announced"]:
        state["announced_count"] = int(state.get("announced_count") or 0) + result["announced"]
    if result["auto_added"]:
        state["auto_added_count"] = int(state.get("auto_added_count") or 0) + result["auto_added"]
    await store.save_state(state)
    await store.save_cache({"works": known, "seen_chapter_ids": list(seen)[-400:]})
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
                f"أضيف {result['auto_added']} • أعلن {result['announced']} • حدّث {result['refreshed']}")
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
