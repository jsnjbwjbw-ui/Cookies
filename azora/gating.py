# ═══════════════════════════════════════════════════════════════
# 🚧 بوابة التسجيل للأعمال المرتبطة بأزورا:
#
#   1) «الفصل المنشور فقط» — لا يُقبل فصل لم يُرفَع بعد على صفحة
#      العمل في أزورا (يُقاس ضد كاش الأرقام الحقيقي).
#   2) «لا تكرار فصل+تخصص» — نفس الفصل بنفس التخصص لا يسجله
#      شخصان؛ التخصصات المختلفة لنفس الفصل مسموحة.
#
#   ⚠️ كل هذا يسري **فقط** على الأعمال المرتبطة (work["azora"]) —
#   الأعمال غير المرتبطة تبقى بسلوكها القديم تمامًا كما طلب المستخدم.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations


def get_azora_link(work: dict | None) -> dict | None:
    """رابط الربط من كائن العمل — None = عمل غير مرتبط (بلا بوابة)."""
    if not work:
        return None
    link = work.get("azora")
    return link if isinstance(link, dict) and link.get("slug") else None


def normalize_chapter(value) -> str:
    """توحيد رقم الفصل للمقارنة: "05"→"5"، "5.0"→"5"، "5.50"→"5.5"."""
    s = str(value).strip()
    try:
        f = float(s)
    except ValueError:
        return s
    if f.is_integer():
        return str(int(f))
    return ("%.2f" % f).rstrip("0").rstrip(".")


async def published_numbers(slug: str) -> set[str]:
    """مجموعة أرقام الفصول المنشورة لعمل أزورا (من الكاش المحدَّث بالمزامنة)."""
    from azora import store
    entry = await store.get_cached_chapters(slug)
    if not entry:
        return set()
    return {normalize_chapter(n) for n in entry.get("numbers", [])}


async def unpublished_chapters(work: dict, chapters: list[str]) -> list[str]:
    """الفصول المطلوبة غير المنشورة بعد على أزورا (للأعمال المرتبطة فقط).

    منطق الحكم بدقة:
    • لا يوجد كاش أصلًا → لا حجب بلا دليل (المزامنة تعبئ الكاش فورًا).
    • يوجد كاش بعدد 0 (صفر فصول منشورة فعليًا) → كل الفصول المطلوبة
      غير منشورة → حجب كامل. هذه الحالة تصير فقط بجلب ناجح بعد إصلاح
      جلب الفصول، فالحكم فيها صحيح ومقصود."""
    link = get_azora_link(work)
    if not link:
        return []
    from azora import store
    entry = await store.get_cached_chapters(link["slug"])
    if not entry:
        return []  # لا كاش بعد: لا نحجب بلا دليل — المزامنة تعبئه فورًا
    published = {normalize_chapter(n) for n in entry.get("numbers", [])}
    return [ch for ch in chapters if normalize_chapter(ch) not in published]


def duplicate_conflicts(records: dict, requester_id, work_name: str,
                        chapters: list[str], types: list[str]) -> list[str]:
    """أسطر تعارض «فصل+تخصص» سجّلهم أعضاء آخرون سابقًا.
    يُستثنى صاحب الطلب نفسه حتى يعيد المحاولة لنفسه بلا حظر زائف."""
    out: list[str] = []
    requester_key = str(requester_id)
    for ch, t in zip(chapters, types):
        for user_id, entries in records.items():
            if user_id == requester_key:
                continue
            for e in entries:
                if (e.get("work_name") == work_name
                        and normalize_chapter(e.get("chapter", "")) == normalize_chapter(ch)
                        and str(e.get("work_type", "")) == str(t)):
                    name = e.get("username") or user_id
                    out.append(f"فصل {ch} — تخصص {t} — مسجل سابقًا لـ {name}")
                    break
            else:
                continue
            break
    return out


async def registration_blockers(work: dict, paid_chapters: list[str],
                                filtered_types: list[str], records: dict,
                                requester_id) -> list[str]:
    """كل أسباب الرفض الخاصة بأزورا لهذا التسجيل — قائمة فارغة = مسموح.
    تعمل فقط للأعمال المرتبطة؛ غير المرتبط يعيد [] فورًا."""
    link = get_azora_link(work)
    if not link:
        return []
    lines: list[str] = []
    missing = await unpublished_chapters(work, paid_chapters)
    if missing:
        shown = "، ".join(f"فصل {m}" for m in missing[:10])
        more = f" و{len(missing) - 10} أخرى" if len(missing) > 10 else ""
        lines.append("لم تُرفَع هذه الفصول على أزورا بعد — التسجيل عليها مغلق حتى النشر: "
                     f"{shown}{more}.")
    conflicts = duplicate_conflicts(records, requester_id, work.get("name", ""),
                                    paid_chapters, filtered_types)
    if conflicts:
        lines.append("لا يُسمح بتسجيل نفس الفصل والتخصص مرتين:")
        lines.extend(f"• {c}" for c in conflicts[:8])
        if len(conflicts) > 8:
            lines.append(f"• و{len(conflicts) - 8} تعارضات أخرى.")
    return lines
