# ═══════════════════════════════════════════════════════════════
# 🗄️ تخزين أزورا — مجموعة MongoDB منفصلة `azora` لا تلمس بيانات
#   البوت الحالية إطلاقًا (records/works/settings تبقى كما هي).
#
#   الوثائق:
#     {_id: "state"}   → إعدادات النظام وحالة آخر مزامنة.
#     {_id: "cache"}   → كاش أعمال الفريق (slug → بيانات) + معرفات
#                        الفصول المعلَن عنها سابقًا (منع التكرار).
#     {_id: "chapters", data: {slug: {numbers, chapters, updated_at,
#                        last_fetch, count}}} → أرقام فصول الأعمال
#                        **المرتبطة** (أساس بوابة «الفصل المنشور فقط»).
#
#   رابط الربط نفسه يُخزَّن داخل كائن العمل في works نفسه:
#     work["azora"] = {slug, post_id, title_en, cover, linked_at, linked_by}
#   فالأعمال غير المرتبطة لا تتأثر بشيء ولا تدخل أي بوابة.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from datetime import datetime, timezone

from database import DatabaseUnavailableError
from database import azora_collection
from azora.client import DEFAULT_TEAM_SLUG

DEFAULT_STATE = {
    "team_slug": DEFAULT_TEAM_SLUG,
    "team_id": None,
    "enabled": True,
    "auto_add_new_works": True,
    "announcements_enabled": True,
    "sync_interval_minutes": 10,
    "announce_channel_id": None,
    "baseline_done": False,
    "listing_v2": False,
    "last_sync_at": None,
    "last_sync_ok": None,
    "last_error": None,
    "last_error_at": None,
    "announced_count": 0,
    "auto_added_count": 0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ───────────────────────────────────────────────────────────────
# وثيقة الحالة
# ───────────────────────────────────────────────────────────────
async def load_state() -> dict:
    try:
        doc = await azora_collection.find_one({"_id": "state"})
    except Exception as e:
        raise DatabaseUnavailableError(f"تعذر قراءة حالة أزورا: {e}") from e
    state = dict(DEFAULT_STATE)
    if doc:
        state.update({k: v for k, v in doc.items() if k != "_id"})
    return state


async def save_state(state: dict) -> bool:
    try:
        await azora_collection.update_one(
            {"_id": "state"}, {"$set": state}, upsert=True)
        return True
    except Exception as e:
        print(f"[ERROR] azora.save_state() - {e}")
        return False


async def update_state_fields(fields: dict) -> bool:
    try:
        await azora_collection.update_one(
            {"_id": "state"}, {"$set": fields}, upsert=True)
        return True
    except Exception as e:
        print(f"[ERROR] azora.update_state_fields() - {e}")
        return False


# ───────────────────────────────────────────────────────────────
# كاش أعمال الفريق + معرفات الفصول المعلَن عنها
# ───────────────────────────────────────────────────────────────
async def load_cache() -> dict:
    try:
        doc = await azora_collection.find_one({"_id": "cache"})
    except Exception as e:
        raise DatabaseUnavailableError(f"تعذر قراءة كاش أزورا: {e}") from e
    if doc and isinstance(doc.get("works"), dict):
        return {"works": doc["works"],
                "seen_chapter_ids": doc.get("seen_chapter_ids", []) or []}
    return {"works": {}, "seen_chapter_ids": []}


async def save_cache(cache: dict) -> bool:
    try:
        await azora_collection.update_one(
            {"_id": "cache"},
            {"$set": {"works": cache.get("works", {}),
                      "seen_chapter_ids": cache.get("seen_chapter_ids", []) or []}},
            upsert=True)
        return True
    except Exception as e:
        print(f"[ERROR] azora.save_cache() - {e}")
        return False


# ───────────────────────────────────────────────────────────────
# كاش أرقام فصول الأعمال المرتبطة
# ───────────────────────────────────────────────────────────────
async def load_chapters_cache() -> dict:
    """{slug: {numbers: [...], chapters: [...], last_fetch, count, updated_at}}"""
    try:
        doc = await azora_collection.find_one({"_id": "chapters"})
    except Exception as e:
        raise DatabaseUnavailableError(f"تعذر قراءة كاش فصول أزورا: {e}") from e
    if doc and isinstance(doc.get("data"), dict):
        return doc["data"]
    return {}


async def save_chapters_entry(slug: str, entry: dict) -> bool:
    entry = dict(entry)
    entry["last_fetch"] = _now_iso()
    try:
        await azora_collection.update_one(
            {"_id": "chapters"},
            {"$set": {f"data.{slug}": entry}},
            upsert=True)
        return True
    except Exception as e:
        print(f"[ERROR] azora.save_chapters_entry({slug}) - {e}")
        return False


async def delete_chapters_entry(slug: str) -> bool:
    try:
        await azora_collection.update_one(
            {"_id": "chapters"}, {"$unset": {f"data.{slug}": ""}})
        return True
    except Exception as e:
        print(f"[ERROR] azora.delete_chapters_entry({slug}) - {e}")
        return False


async def get_cached_chapters(slug: str) -> dict | None:
    cache = await load_chapters_cache()
    return cache.get(slug)
