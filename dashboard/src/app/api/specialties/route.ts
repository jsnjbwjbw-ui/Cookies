import { getStore } from "@/lib/store";
import { json, requireAuth, isResponse } from "@/lib/api";
import { logAudit } from "@/lib/audit";

export async function GET() {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const store = getStore();
    const [settings, works] = await Promise.all([store.getSettings(), store.getWorks()]);
    return json({
      specialties: settings.specialties || {},
      currency: settings.currency || "$",
      works: works.map((w) => ({ name: w.name, custom_prices: w.custom_prices || {} })),
    });
  } catch (e) {
    console.error("[SPECIALTIES/GET]", e);
    return json({ error: "تعذر قراءة التخصصات" }, 503);
  }
}

export async function POST(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as { name?: string; price?: number };
    const name = (body.name || "").trim().replace(/\s+/g, "_");
    const price = Number(body.price);
    if (!name) return json({ error: "اسم التخصص مطلوب" }, 400);
    if (Number.isNaN(price) || price < 0) return json({ error: "سعر غير صالح" }, 400);
    const store = getStore();
    const settings = await store.getSettings();
    settings.specialties ||= {};
    if (name in settings.specialties) return json({ error: "التخصص موجود مسبقًا" }, 409);
    settings.specialties[name] = { price, active: true, last_modified: new Date().toISOString() };
    const saved = await store.saveSettings(settings);
    if (!saved) return json({ error: "تعذر الحفظ" }, 503);
    await logAudit(store, "إضافة_تخصص", auth.id, null, `${name} بسعر ${price}`);
    return json({ ok: true });
  } catch (e) {
    console.error("[SPECIALTIES/POST]", e);
    return json({ error: "تعذر الإضافة" }, 500);
  }
}

/** تعديل سعر/تفعيل تخصص عام — أو تعديل تخصيص عمل ({work, name, price}) */
export async function PATCH(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as {
      name?: string;
      price?: number;
      active?: boolean;
      work?: string; // عند وجوده: التعديل على تخصيص العمل وليس التخصص العام
    };
    if (!body.name) return json({ error: "اسم التخصص مطلوب" }, 400);
    const store = getStore();

    if (body.work) {
      const works = await store.getWorks();
      const w = works.find((x) => x.name === body.work);
      if (!w) return json({ error: "العمل غير موجود" }, 404);
      if (typeof body.price === "number") {
        w.custom_prices ||= {};
        w.custom_prices[body.name] = body.price;
      }
      const saved = await store.saveWorks(works);
      if (!saved) return json({ error: "تعذر الحفظ" }, 503);
      await logAudit(store, "تعديل_تخصيص", auth.id, null, `${body.name} في ${body.work} = ${body.price}`);
      return json({ ok: true });
    }

    const settings = await store.getSettings();
    settings.specialties ||= {};
    const sp = settings.specialties[body.name];
    if (!sp) return json({ error: "التخصص غير موجود" }, 404);
    if (typeof body.price === "number" && body.price >= 0) sp.price = body.price;
    if (typeof body.active === "boolean") sp.active = body.active;
    sp.last_modified = new Date().toISOString();
    const saved = await store.saveSettings(settings);
    if (!saved) return json({ error: "تعذر الحفظ" }, 503);
    await logAudit(store, "تعديل_تخصص", auth.id, null, `${body.name}: سعر=${sp.price} نشط=${sp.active}`);
    return json({ ok: true });
  } catch (e) {
    console.error("[SPECIALTIES/PATCH]", e);
    return json({ error: "تعذر التعديل" }, 500);
  }
}

/** حذف تخصص عام — أو إعادة تخصيص عمل إلى القائمة العامة ({work, name, toGlobal: true}) */
export async function DELETE(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const { searchParams } = new URL(req.url);
    const name = searchParams.get("name");
    const work = searchParams.get("work");
    const toGlobal = searchParams.get("toGlobal") === "1";
    if (!name) return json({ error: "اسم التخصص مطلوب" }, 400);
    const store = getStore();

    if (work) {
      const [works, settings] = await Promise.all([store.getWorks(), store.getSettings()]);
      const w = works.find((x) => x.name === work);
      if (!w || !w.custom_prices || !(name in w.custom_prices)) {
        return json({ error: "التخصيص غير موجود" }, 404);
      }
      const price = w.custom_prices[name];
      delete w.custom_prices[name];
      if (Object.keys(w.custom_prices).length === 0) delete w.custom_prices;
      if (toGlobal) {
        settings.specialties ||= {};
        settings.specialties[name] = { price, active: true, last_modified: new Date().toISOString() };
        await store.saveSettings(settings);
      }
      const saved = await store.saveWorks(works);
      if (!saved) return json({ error: "تعذر الحفظ" }, 503);
      await logAudit(store, "نقل_تخصص", auth.id, null, `${name}: من ${work} إلى ${toGlobal ? "العام" : "الحذف"}`);
      return json({ ok: true });
    }

    const settings = await store.getSettings();
    if (!settings.specialties || !(name in settings.specialties)) {
      return json({ error: "التخصص غير موجود" }, 404);
    }
    delete settings.specialties[name];
    const saved = await store.saveSettings(settings);
    if (!saved) return json({ error: "تعذر الحفظ" }, 503);
    await logAudit(store, "حذف_تخصص", auth.id, null, `حُذف ${name} من القائمة العامة`);
    return json({ ok: true });
  } catch (e) {
    console.error("[SPECIALTIES/DELETE]", e);
    return json({ error: "تعذر الحذف" }, 500);
  }
}
