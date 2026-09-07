import { getStore } from "@/lib/store";
import { memberDirectory, entriesForMonth, computeMemberTotals, isolatedNames, getActiveMonth } from "@/lib/agg";
import { json, requireAuth, isResponse } from "@/lib/api";
import { logAudit } from "@/lib/audit";

export async function GET() {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const store = getStore();
    const [records, works, { key: activeMonth }] = await Promise.all([
      store.getRecords(),
      store.getWorks(),
      getActiveMonth(store),
    ]);
    const directory = await memberDirectory(store, records);
    const monthEntries = entriesForMonth(records, activeMonth, isolatedNames(works));
    const totals = computeMemberTotals(monthEntries, directory);
    const allTimeChapters: Record<string, number> = {};
    for (const [uid, entries] of Object.entries(records)) {
      allTimeChapters[uid] = entries.filter((e) => e.work_type !== "مكافأة" && e.work_type !== "خصم").length;
    }
    const members = [...directory.values()].map((m) => {
      const t = totals.find((x) => x.userId === m.id);
      return {
        ...m,
        chaptersThisMonth: t?.chapters ?? 0,
        amountThisMonth: t?.amount ?? 0,
        chaptersAllTime: allTimeChapters[m.id] ?? 0,
        hasActivityThisMonth: Boolean(t),
        lastActivity: t?.lastActivity,
        perWork: t?.perWork ?? {},
        perType: t?.perType ?? {},
      };
    });
    return json({ members, activeMonth });
  } catch (e) {
    console.error("[MEMBERS/GET]", e);
    return json({ error: "تعذر قراءة الأعضاء" }, 503);
  }
}

/** تحديث اسم العضو المعروض (النك) — يكتب في مجموعة members نفسها */
export async function PATCH(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as { id?: string; nickname?: string };
    if (!body.id || typeof body.nickname !== "string") {
      return json({ error: "بيانات ناقصة" }, 400);
    }
    const store = getStore();
    await store.upsertMember(body.id, { nickname: body.nickname.trim() || undefined });
    await logAudit(store, "تحديث_عضو", auth.id, body.id, `النك الآن: ${body.nickname.trim() || "(إزالة)"}`);
    return json({ ok: true });
  } catch (e) {
    console.error("[MEMBERS/PATCH]", e);
    return json({ error: "تعذر التحديث" }, 500);
  }
}
