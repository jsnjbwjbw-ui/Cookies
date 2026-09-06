from typing import List
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import re
import discord
from discord import app_commands
from config import DEFAULT_SPECIALTIES, DEFAULT_ALLOWED_CHANNELS 
from database import collection, settings_collection, audit_collection, stats_collection

SETTINGS = {}
PRICES = {}

FIXED_ALLOWED_CHANNEL = "ム・💎〢شات・اونر"

def is_admin(interaction: discord.Interaction) -> bool:
    """توحيد صلاحية الإدارة لكل الأوامر:
    مدير السيرفر (administrator) أو من يملك إدارة الرسائل (manage_messages)."""
    if not interaction.guild:
        return False
    perms = getattr(interaction.user, "guild_permissions", None)
    if perms is None:
        return False
    return perms.administrator or perms.manage_messages


def channel_allowed(interaction: discord.Interaction) -> bool:
    """فحص القناة المسموحة — يقبل **المعرف الرقمي** أو الاسم معًا:
    أمر /تحديد_قنوات يحفظ معرف القناة (int)، لذا المقارنة بالاسم وحده
    كانت ترفض القناة المحددة نفسها. يعمل هذا الفحص مع الثريدات أيضًا."""
    ch = getattr(interaction, "channel", None)
    if ch is None:
        return False
    allowed = SETTINGS.get("allowed_channels", [])
    ch_id = getattr(ch, "id", None)
    if ch_id is not None and ch_id in allowed:
        return True
    name = getattr(ch, "name", None)
    return bool(name) and name in allowed


def sort_entries_by_chapter(entries: list) -> list:
    """ترتيب السجلات رقميًا حسب رقم الفصل (وإلا نصيًا) — للعرض المنظم."""
    def key(e):
        ch = str(e.get("chapter", ""))
        if ch.isdigit():
            return (0, int(ch), "")
        return (1, 0, ch)
    return sorted(entries, key=key)


def entry_datetime(entry: dict):
    """تحويل طابع السجل الزمني إلى datetime بأمان (None عند الفشل)."""
    ts = entry.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def build_monthly_summary_card(user, month_entries: list, currency: str = "$", avatar_url=None, back_factory=None):
    """بطاقة الملخص الشهري الموحدة — تُستخدم في /ملخص_شهري وفي زر
    «ملخص شهري» داخل لوحة التحكم حتى لا يختلف التصميم أبدًا.
    عند تمرير back_factory يُضاف زر «عودة إلى لوحة التحكم» أسفل البطاقة."""
    from ui import cards  # استيراد مؤجل لتجنب أي دورة استيراد

    currency = currency or "$"
    total = sum(e.get("total", 0) for e in month_entries)
    bonuses = sum(e.get("total", 0) for e in month_entries if e.get("work_type") == "مكافأة")
    deductions = sum(abs(e.get("total", 0)) for e in month_entries if e.get("work_type") == "خصم")
    work_entries = [e for e in month_entries if e.get("work_type") not in ("مكافأة", "خصم")]

    works_count = defaultdict(int)
    for e in work_entries:
        works_count[e.get("work_name", "غير محدد")] += 1
    types_count = defaultdict(int)
    for e in work_entries:
        types_count[e.get("work_type", "غير محدد")] += 1
    net = total + bonuses - deductions

    # كل رقم في سطر مستقل — لا حشو في سطر واحد أبدًا
    stats_lines = [f"**الفصول:** {len(work_entries)}"]
    if bonuses:
        stats_lines.append(f"**المكافآت:** {currency}{bonuses:,.2f}")
    if deductions:
        stats_lines.append(f"**الخصومات:** {currency}{deductions:,.2f}")
    stats_lines.append(f"**💰 الصافي المستحق:** {currency}{net:,.2f}")

    works_lines = [f"• **{w}** — {c} فصول" for w, c in sorted(works_count.items(), key=lambda kv: -kv[1])] or ["• لا يوجد"]
    types_lines = [f"• **{t.replace('_', ' ').title()}** — {c} فصول"
                   for t, c in sorted(types_count.items(), key=lambda kv: -kv[1])] or ["• لا يوجد"]

    thumb = avatar_url
    if thumb is None and hasattr(user, "display_avatar"):
        thumb = user.display_avatar.url

    head = (cards.member_header(["## الملخص الشهري", f"<@{user.id}>"], user) if thumb
            else cards.header(["## الملخص الشهري", f"<@{user.id}>"], None))

    children = [
        head,
        cards.sep(2),
        cards.text("\n".join(stats_lines)),
        cards.sep(),
        cards.text("### تفصيل الأعمال\n" + "\n".join(works_lines)),
        cards.sep(),
        cards.text("### تفصيل التخصصات\n" + "\n".join(types_lines)),
    ]
    if back_factory is not None:
        async def _back(interaction: discord.Interaction):
            parent = back_factory()
            if hasattr(parent, "__await__"):
                parent = await parent
            await interaction.response.edit_message(view=parent)
        children += [
            cards.sep(),
            cards.row(cards.secondary_btn("عودة إلى لوحة التحكم", _back, emoji="↩")),
        ]
    children += [
        cards.sep(),
        cards.text(f"-# من بداية الشهر حتى الآن • {cards.BOT_SIGNATURE}"),
    ]
    return cards.Card(cards.ACCENT_GOLD, *children)

def member_display_name(guild: discord.Guild | None, user_id, username_hint: str = None) -> str:
    """اسم العضو في السيرفر (النك نيم) — يُستخدم داخل القوائم المنسدلة فقط."""
    member = guild.get_member(int(user_id)) if guild else None
    if member:
        return member.display_name
    if username_hint:
        return username_hint
    return str(user_id)


def member_mention(user_id) -> str:
    """المنشن الحقيقي الوحيد المسموح في كل رسائل البوت: <@ID>."""
    return f"<@{user_id}>"

async def load_works() -> list:
    doc = await collection.find_one({"_id": "works"})
    if doc and "data" in doc:
        return doc["data"]
    return []

async def save_works(works: list):
    await collection.update_one(
        {"_id": "works"},
        {"$set": {"data": works}},
        upsert=True
    )

async def get_work(work_name: str) -> dict | None:
    works = await load_works()
    for w in works:
        if w["name"] == work_name:
            return w
    return None

def is_work_isolated(work: dict | None) -> bool:
    return bool(work and work.get("isolated", False))

def get_isolated_work_names(works: list) -> set[str]:
    return {w.get("name") for w in works if is_work_isolated(w) and w.get("name")}

def filter_visible_entries(entries: list, isolated_work_names: set[str]) -> list:
    return [
        entry for entry in entries
        if not entry.get("work_name") or entry.get("work_name") not in isolated_work_names
    ]

async def load_visible_records() -> dict:
    records = await load_records()
    works = await load_works()
    isolated = get_isolated_work_names(works)
    if not isolated:
        return records
    visible = {}
    for user_id, entries in records.items():
        filtered = filter_visible_entries(entries, isolated)
        if filtered:
            visible[user_id] = filtered
    return visible

def filter_paid_chapters(work: dict, chapters_list: List[str]):
    if work.get("paid_start") is None:
        return chapters_list, 0
    paid_start = work["paid_start"]
    paid = []
    free = 0
    for ch in chapters_list:
        try:
            ch_num = int(ch)
        except ValueError:
            paid.append(ch)
            continue
        if ch_num >= paid_start:
            paid.append(ch)
        else:
            free += 1
    return paid, free

async def delete_all_records_of_work(work_name: str) -> int:
    """
    Delete every record that belongs to a specific work (across all users).
    If the work is isolated, no records will be touched and returns 0.
    """
    # ✅ فحص العزل قبل الحذف
    works = await load_works()
    work_obj = next((w for w in works if w["name"] == work_name), None)
    if work_obj and is_work_isolated(work_obj):
        # العمل معزول، لا تمس سجلاته
        return 0

    records = await load_records()
    removed_total = 0
    users_to_delete = []
    for user_id, entries in records.items():
        new_entries = [e for e in entries if e.get("work_name") != work_name]
        removed = len(entries) - len(new_entries)
        if removed > 0:
            removed_total += removed
            if new_entries:
                records[user_id] = new_entries
            else:
                users_to_delete.append(user_id)
    for uid in users_to_delete:
        del records[uid]
    if removed_total > 0:
        await save_records(records)
        await update_stats()
    return removed_total

# ----------------------------------------------------------------------
# Core helpers (unchanged logic)
# ----------------------------------------------------------------------
async def load_records():
    try:
        doc = await collection.find_one({"_id": "records"})
        if doc and "data" in doc:
            return doc["data"]
        return {}
    except Exception as e:
        print(f"[ERROR] load_records() - {e}")
        return {}

async def save_records(records):
    try:
        await collection.update_one(
            {"_id": "records"},
            {"$set": {"data": records}},
            upsert=True
        )
    except Exception as e:
        print(f"[ERROR] save_records() - {e}")

async def load_settings():
    try:
        doc = await settings_collection.find_one({"_id": "settings"})
        if doc:
            if "specialties" not in doc:
                doc["specialties"] = DEFAULT_SPECIALTIES.copy()
            if "payment_day" not in doc:
                doc["payment_day"] = None
                doc["payment_hour"] = 0
                doc["payment_reminder_24h_sent"] = False
                doc["payment_day_sent"] = False
            allowed = doc.get("allowed_channels", [])
            if isinstance(allowed, list):
                allowed = [
                    int(x) if isinstance(x, str) and x.isdigit() else x 
                    for x in allowed
                ]
                if FIXED_ALLOWED_CHANNEL not in allowed:
                    allowed.append(FIXED_ALLOWED_CHANNEL)
                doc["allowed_channels"] = allowed
            else:
                doc["allowed_channels"] = [FIXED_ALLOWED_CHANNEL]
            return doc
        default_channels = []
        for ch in DEFAULT_ALLOWED_CHANNELS:
            if isinstance(ch, int) or (isinstance(ch, str) and ch.isdigit()):
                default_channels.append(int(ch))
            else:
                default_channels.append(ch)
        if FIXED_ALLOWED_CHANNEL not in default_channels:
            default_channels.append(FIXED_ALLOWED_CHANNEL)
        return {
            "allowed_channels": default_channels,
            "currency": "$",
            "notify_channel_id": None,
            "daily_backup_channel_id": None,
            "alert_threshold": 10.0,
            "specialties": DEFAULT_SPECIALTIES.copy(),
            "payment_day": None,
            "payment_hour": 0,
            "payment_reminder_24h_sent": False,
            "payment_day_sent": False
        }
    except Exception as e:
        print(f"[ERROR] load_settings() - {e}")
        default_channels = []
        for ch in DEFAULT_ALLOWED_CHANNELS:
            if isinstance(ch, int) or (isinstance(ch, str) and ch.isdigit()):
                default_channels.append(int(ch))
            else:
                default_channels.append(ch)
        if FIXED_ALLOWED_CHANNEL not in default_channels:
            default_channels.append(FIXED_ALLOWED_CHANNEL)
        return {
            "allowed_channels": default_channels,
            "currency": "$",
            "notify_channel_id": None,
            "daily_backup_channel_id": None,
            "alert_threshold": 10.0,
            "specialties": DEFAULT_SPECIALTIES.copy(),
            "payment_day": None,
            "payment_hour": 0,
            "payment_reminder_24h_sent": False,
            "payment_day_sent": False
        }

async def save_settings(settings):
    settings_copy = settings.copy()
    allowed = settings_copy.get("allowed_channels", [])
    if isinstance(allowed, list):
        allowed = [
            int(x) if isinstance(x, str) and x.isdigit() else x 
            for x in allowed
        ]
        if FIXED_ALLOWED_CHANNEL not in allowed:
            allowed.append(FIXED_ALLOWED_CHANNEL)
        settings_copy["allowed_channels"] = allowed
    else:
        settings_copy["allowed_channels"] = [FIXED_ALLOWED_CHANNEL]
    try:
        await settings_collection.update_one(
            {"_id": "settings"},
            {"$set": settings_copy},
            upsert=True
        )
    except Exception as e:
        print(f"[ERROR] save_settings() - {e}")

def rebuild_prices():
    specialties = SETTINGS.get("specialties", DEFAULT_SPECIALTIES)
    PRICES.clear()
    PRICES.update({k: v["price"] for k, v in specialties.items() if v.get("active", True)})

async def log_audit(action, moderator_id, target_id, details):
    log_entry = {
        "action": action,
        "moderator_id": str(moderator_id),
        "target_id": str(target_id) if target_id else None,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    await audit_collection.insert_one(log_entry)

async def log_unauthorized(user_id, command_name):
    await log_audit("محاولة_غير_مصرح_بها", user_id, None,
                    f"محاولة استخدام الأمر {command_name} بدون صلاحية")

async def update_stats():
    records = await load_visible_records()
    total_entries = sum(len(entries) for entries in records.values())
    total_amount = 0
    type_counts = {}
    member_stats = {}

    for user_id, entries in records.items():
        member_total = 0
        member_counts = {}
        for entry in entries:
            amount = entry.get("total", 0)
            total_amount += amount
            member_total += amount
            wtype = entry.get("work_type")
            type_counts[wtype] = type_counts.get(wtype, 0) + 1
            member_counts[wtype] = member_counts.get(wtype, 0) + 1
        member_stats[user_id] = {
            "total_amount": member_total,
            "total_entries": len(entries),
            "type_counts": member_counts
        }

    top_members = sorted(member_stats.items(),
                         key=lambda x: x[1]["total_amount"], reverse=True)[:10]
    top_members_data = [(uid, stats) for uid, stats in top_members]

    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    daily_entries = 0
    daily_amount = 0
    weekly_entries = 0
    weekly_amount = 0
    monthly_entries = 0
    monthly_amount = 0

    for user_id, entries in records.items():
        for entry in entries:
            ts = entry.get("timestamp")
            if ts:
                try:
                    entry_date = datetime.fromisoformat(ts).date()
                    if entry_date == today:
                        daily_entries += 1
                        daily_amount += entry.get("total", 0)
                    if entry_date >= week_start:
                        weekly_entries += 1
                        weekly_amount += entry.get("total", 0)
                    if entry_date >= month_start:
                        monthly_entries += 1
                        monthly_amount += entry.get("total", 0)
                except:
                    pass

    stat_doc = {
        "total_entries": total_entries,
        "total_amount": total_amount,
        "type_counts": type_counts,
        "member_stats": member_stats,
        "top_members": top_members_data,
        "daily": {"entries": daily_entries, "amount": daily_amount},
        "weekly": {"entries": weekly_entries, "amount": weekly_amount},
        "monthly": {"entries": monthly_entries, "amount": monthly_amount},
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    await stats_collection.update_one(
        {"_id": "stats"},
        {"$set": stat_doc},
        upsert=True
    )

def parse_fields(text):
    fields = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        fields[key] = value
    return fields

def parse_chapter_range(range_str):
    range_str = range_str.strip()
    chapters = []
    if '-' in range_str:
        parts = range_str.split('-')
        if len(parts) == 2:
            try:
                start = int(parts[0])
                end = int(parts[1])
                for i in range(start, end+1):
                    chapters.append(str(i))
            except:
                pass
    elif ',' in range_str:
        for part in range_str.split(','):
            part = part.strip()
            if part.isdigit():
                chapters.append(part)
    else:
        if range_str.isdigit():
            chapters.append(range_str)
    return chapters

def parse_mixed_types(types_input, chapters_count):
    types_input = types_input.strip()
    if '-' in types_input:
        parts = types_input.split('-')
        if len(parts) == chapters_count:
            return [p.strip() for p in parts]
        elif len(parts) == 2:
            first = parts[0].strip()
            rest = parts[1].strip()
            return [first] + [rest] * (chapters_count - 1)
        else:
            if ',' in types_input:
                return parse_mixed_types(types_input.replace('-', ','), chapters_count)
            return None
    elif ',' in types_input:
        parts = [p.strip() for p in types_input.split(',')]
        if len(parts) == chapters_count:
            return parts
        elif len(parts) == 1:
            return [parts[0]] * chapters_count
        else:
            return None
    else:
        return [types_input] * chapters_count

def map_type(t):
    return t.strip().replace(' ', '_')

def is_duplicate(records, user_id, work_name, chapter, work_type):
    user_entries = records.get(str(user_id), [])
    for e in user_entries:
        if (e.get("work_name") == work_name and 
            e.get("chapter") == chapter and 
            e.get("work_type") == work_type):
            return True
    return False

# ----------------------------------------------------------------------
# Unified UI helpers
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# NEW: Helper to get the correct price for a specialty in a specific work
# ----------------------------------------------------------------------
async def get_specialty_price(work_name: str, specialty: str) -> float:
    """
    Return the price for a specialty in the given work.
    If the work has a 'custom_prices' dictionary and the specialty exists in it,
    return that custom price. Otherwise, fall back to the global PRICES dictionary.
    """
    work = await get_work(work_name)
    if work and "custom_prices" in work and specialty in work["custom_prices"]:
        return work["custom_prices"][specialty]
    # Fallback to global price (from PRICES loaded from specialties settings)
    return PRICES.get(specialty, 0.0)

# ----------------------------------------------------------------------
# NEW: Helpers to move specialties between global and work-specific
# ----------------------------------------------------------------------
async def move_specialty_to_work_core(work_name: str, specialty: str) -> tuple[bool, str, float]:
    """
    Move a specialty from the global list into the custom_prices of a specific work.
    Returns (success, message, price) where price is the old global price if success.
    """
    specialties = SETTINGS.get("specialties", {})
    norm = map_type(specialty)
    if norm not in specialties:
        return False, f"التخصص `{specialty}` غير موجود في القائمة العامة.", 0.0
    if not specialties[norm].get("active", True):
        return False, f"التخصص `{specialty}` معطّل حالياً ولا يمكن نقله.", 0.0

    price = specialties[norm]["price"]
    # Remove from global
    del specialties[norm]
    await save_settings(SETTINGS)
    rebuild_prices()

    # Add to work's custom_prices
    works = await load_works()
    target = next((w for w in works if w["name"] == work_name), None)
    if not target:
        # Rollback: re-add to global
        specialties[norm] = {"price": price, "active": True, "last_modified": datetime.now(timezone.utc).isoformat()}
        await save_settings(SETTINGS)
        rebuild_prices()
        return False, f"العمل `{work_name}` غير موجود.", 0.0

    if "custom_prices" not in target:
        target["custom_prices"] = {}
    target["custom_prices"][norm] = price
    await save_works(works)

    return True, f"تم نقل التخصص `{specialty}` إلى عمل `{work_name}` بسعر {price}.", price

async def move_specialty_to_global_core(work_name: str, specialty: str) -> tuple[bool, str, float]:
    """
    Move a specialty from a work's custom_prices back to the global list.
    Returns (success, message, price).
    """
    works = await load_works()
    target = next((w for w in works if w["name"] == work_name), None)
    if not target:
        return False, f"العمل `{work_name}` غير موجود.", 0.0

    custom = target.get("custom_prices")
    norm = map_type(specialty)
    if not custom or norm not in custom:
        return False, f"التخصص `{specialty}` غير موجود في تخصيصات العمل `{work_name}`.", 0.0

    price = custom[norm]
    # Remove from work
    del custom[norm]
    if not custom:
        del target["custom_prices"]
    await save_works(works)

    # Add to global specialties
    specialties = SETTINGS.get("specialties", {})
    specialties[norm] = {
        "price": price,
        "active": True,
        "last_modified": datetime.now(timezone.utc).isoformat()
    }
    await save_settings(SETTINGS)
    rebuild_prices()

    return True, f"تم نقل التخصص `{specialty}` إلى القائمة العامة بسعر {price}.", price