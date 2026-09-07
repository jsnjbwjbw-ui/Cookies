import { getStore } from "@/lib/store";
import { monthKeyOf } from "@/lib/store/types";
import { json, requireAuth, isResponse } from "@/lib/api";
import { logAudit } from "@/lib/audit";
import { isMonthKey, currentMonthKey } from "@/lib/store/types";

export async function GET() {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const store = getStore();
    const [months, records, settings] = await Promise.all([store.getMonths(), store.getRecords(), store.getSettings()]);
    const list = months.map((m) => {
      let recordsCount = 0;
      let chapters = 0;
      let amount = 0;
      for (const entries of Object.values(records)) {
        for (const e of entries) {
          if (monthKeyOf(e) !== m._id) continue;
          recordsCount += 1;
          if (e.work_type !== "مكافأة" && e.work_type !== "خصم") chapters += 1;
          amount += e.total || 0;
        }
      }
      return { ...m, recordsCount, chapters, amount };
    });
    return json({
      months: list,
      activeMonth: isMonthKey(settings.active_month) ? settings.active_month : currentMonthKey(),
    });
  } catch (e) {
    console.error("[MONTHS/GET]", e);
    return json({ error: "تعذر قراءة الأشهر" }, 503);
  }
}

/** إنشاء شهر — الأعمال والأعضاء تبقى كما هي، والسجلات تبدأ نظيفة */
export async function POST(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as { key?: string; name?: string; activate?: boolean };
    let key = body.key?.trim();
    if (key && !/^\d{4}-\d{2}$/.test(key)) {
      return json({ error: "صيغة الشهر يجب أن تكون YYYY-MM مثل 2025-07" }, 400);
    }
    if (!key) {
      // الشهر التالي على الشهر النشط
      const settings = await storeSafeActive();
      const [y, m] = settings.split("-").map(Number);
      const next = new Date(Date.UTC(y, m, 1));
      key = next.toISOString().slice(0, 7);
    }
    const store = getStore();
    const months = await store.getMonths();
    if (months.some((m) => m._id === key)) return json({ error: "هذا الشهر موجود مسبقًا" }, 409);
    await store.ensureMonth(key, auth.id);
    if (body.name?.trim()) await store.updateMonth(key, { name: body.name.trim() });
    if (body.activate) {
      const settings = await store.getSettings();
      settings.active_month = key;
      await store.saveSettings(settings);
    }
    await logAudit(store, "إنشاء_شهر", auth.id, null, `الشهر ${key}${body.activate ? " — مفعّل الآن" : ""}`);
    return json({ ok: true, key });
  } catch (e) {
    console.error("[MONTHS/POST]", e);
    return json({ error: "تعذر إنشاء الشهر" }, 500);
  }
}

async function storeSafeActive(): Promise<string> {
  const store = getStore();
  const settings = await store.getSettings();
  return isMonthKey(settings.active_month) ? settings.active_month : currentMonthKey();
}

/** تسمية شهر أو تفعيله */
export async function PATCH(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as { key?: string; name?: string; activate?: boolean };
    if (!body.key || !isMonthKey(body.key)) return json({ error: "مفتاح الشهر مطلوب" }, 400);
    const store = getStore();
    const months = await store.getMonths();
    if (!months.some((m) => m._id === body.key)) return json({ error: "الشهر غير موجود" }, 404);
    if (typeof body.name === "string") {
      await store.updateMonth(body.key, { name: body.name.trim() || undefined });
    }
    if (body.activate) {
      const settings = await store.getSettings();
      settings.active_month = body.key;
      await store.saveSettings(settings);
      await logAudit(store, "تبديل_شهر", auth.id, null, `تم تفعيل ${body.key}`);
    } else {
      await logAudit(store, "تعديل_شهر", auth.id, null, `${body.key}: تسمية «${body.name ?? ""}»`);
    }
    return json({ ok: true });
  } catch (e) {
    console.error("[MONTHS/PATCH]", e);
    return json({ error: "تعذر التعديل" }, 500);
  }
}

/** حذف شهر — يحذف سجلات هذا الشهر فقط من كل الأعضاء (مطابق لمنطق /الشهور في البوت) */
export async function DELETE(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const { searchParams } = new URL(req.url);
    const key = searchParams.get("key");
    if (!key || !isMonthKey(key)) return json({ error: "مفتاح الشهر مطلوب" }, 400);
    const store = getStore();
    const settings = await store.getSettings();
    const active = isMonthKey(settings.active_month) ? settings.active_month : currentMonthKey();
    if (key === active) {
      return json({ error: "لا يمكن حذف الشهر النشط — فعّل شهرًا آخر أولًا" }, 400);
    }
    const records = await store.getRecords();
    let removed = 0;
    for (const uid of Object.keys(records)) {
      const before = records[uid].length;
      records[uid] = records[uid].filter((e) => monthKeyOf(e) !== key);
      removed += before - records[uid].length;
      if (records[uid].length === 0) delete records[uid];
    }
    await store.saveRecords(records, { allowWipe: true });
    await store.deleteMonth(key);
    await logAudit(store, "حذف_شهر", auth.id, null, `حُذف ${key} مع ${removed} سجل`);
    return json({ ok: true, removed });
  } catch (e) {
    console.error("[MONTHS/DELETE]", e);
    return json({ error: "تعذر الحذف" }, 500);
  }
}
