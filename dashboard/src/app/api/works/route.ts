import { getStore } from "@/lib/store";
import { computeWorkStats, getActiveMonth } from "@/lib/agg";
import { json, requireAuth, isResponse } from "@/lib/api";
import { logAudit } from "@/lib/audit";

export async function GET() {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const store = getStore();
    const [works, records, { key: activeMonth }] = await Promise.all([
      store.getWorks(),
      store.getRecords(),
      getActiveMonth(store),
    ]);
    return json({ works, stats: computeWorkStats(records, works, activeMonth), activeMonth });
  } catch (e) {
    console.error("[WORKS/GET]", e);
    return json({ error: "تعذر قراءة الأعمال" }, 503);
  }
}

export async function POST(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as { name?: string; paid_start?: number | null };
    const name = (body.name || "").trim();
    if (!name) return json({ error: "اسم العمل مطلوب" }, 400);
    const store = getStore();
    const works = await store.getWorks();
    if (works.some((w) => w.name === name)) {
      return json({ error: "يوجد عمل بنفس الاسم" }, 409);
    }
    works.push({
      name,
      paid_start: typeof body.paid_start === "number" ? body.paid_start : null,
      isolated: false,
    });
    const saved = await store.saveWorks(works);
    if (!saved) return json({ error: "تعذر الحفظ — قاعدة البيانات غير متاحة" }, 503);
    await logAudit(store, "إضافة_عمل", auth.id, null, `أُضيف العمل ${name}`);
    return json({ ok: true });
  } catch (e) {
    console.error("[WORKS/POST]", e);
    return json({ error: "تعذر الإضافة" }, 500);
  }
}

export async function PATCH(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as {
      name?: string;
      newName?: string;
      paid_start?: number | null;
      isolated?: boolean;
    };
    if (!body.name) return json({ error: "اسم العمل مطلوب" }, 400);
    const store = getStore();
    const works = await store.getWorks();
    const work = works.find((w) => w.name === body.name);
    if (!work) return json({ error: "العمل غير موجود" }, 404);
    if (typeof body.newName === "string" && body.newName.trim() && body.newName.trim() !== body.name) {
      const nn = body.newName.trim();
      if (works.some((w) => w.name === nn)) return json({ error: "يوجد عمل بنفس الاسم الجديد" }, 409);
      work.name = nn;
    }
    if (body.paid_start !== undefined) work.paid_start = body.paid_start;
    if (body.isolated !== undefined) work.isolated = body.isolated;
    const saved = await store.saveWorks(works);
    if (!saved) return json({ error: "تعذر الحفظ" }, 503);
    await logAudit(store, "تعديل_عمل", auth.id, null, `تحديث العمل ${body.name}`);
    return json({ ok: true });
  } catch (e) {
    console.error("[WORKS/PATCH]", e);
    return json({ error: "تعذر التعديل" }, 500);
  }
}

export async function DELETE(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const { searchParams } = new URL(req.url);
    const name = searchParams.get("name");
    if (!name) return json({ error: "اسم العمل مطلوب" }, 400);
    const store = getStore();
    const works = await store.getWorks();
    const work = works.find((w) => w.name === name);
    if (!work) return json({ error: "العمل غير موجود" }, 404);
    if (work.isolated) {
      return json({ error: "العمل معزول — سجلاته محفوظة ولا يمكن حذفه من هنا" }, 400);
    }
    const remaining = works.filter((w) => w.name !== name);
    const saved = await store.saveWorks(remaining);
    if (!saved) return json({ error: "تعذر الحفظ" }, 503);
    await logAudit(store, "حذف_عمل", auth.id, null, `حُذف العمل ${name} (سجلاته تبقى محفوظة)`);
    return json({ ok: true });
  } catch (e) {
    console.error("[WORKS/DELETE]", e);
    return json({ error: "تعذر الحذف" }, 500);
  }
}
