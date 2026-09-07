import { getStore } from "@/lib/store";
import { getActiveMonth, resolvePrice } from "@/lib/agg";
import { monthKeyOf as mkOf } from "@/lib/store/types";
import { json, requireAuth, isResponse } from "@/lib/api";
import { logAudit } from "@/lib/audit";

export async function GET(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const { searchParams } = new URL(req.url);
    const userId = searchParams.get("userId");
    const work = searchParams.get("work");
    const month = searchParams.get("month");
    const type = searchParams.get("type");
    const store = getStore();
    const [records, members] = await Promise.all([store.getRecords(), store.getMembers()]);
    const out: Array<{
      userId: string;
      memberName: string;
      entry: Record<string, unknown>;
    }> = [];
    for (const [uid, entries] of Object.entries(records)) {
      if (userId && uid !== userId) continue;
      for (const e of entries) {
        if (work && e.work_name !== work) continue;
        if (month && mkOf(e) !== month) continue;
        if (type && e.work_type !== type) continue;
        const doc = members[uid];
        out.push({
          userId: uid,
          memberName: doc?.nickname || doc?.username || e.username || uid,
          entry: e as unknown as Record<string, unknown>,
        });
      }
    }
    out.sort((a, b) => String((b.entry as { timestamp?: string }).timestamp || "").localeCompare(String((a.entry as { timestamp?: string }).timestamp || "")));
    return json({ records: out.slice(0, 600) });
  } catch (e) {
    console.error("[RECORDS/GET]", e);
    return json({ error: "تعذر قراءة السجلات" }, 503);
  }
}

/**
 * تسجيل سجلات جديدة — نفس منطق البوت بالضبط:
 * فحص تكرار (نفس العضو+العمل+الفصل+التخصص)، سعر التخصيص ثم العام،
 * ختم month_key بالشهر النشط، تحديث مجموعة members، وتدقيق.
 * body: { userId, work, chapters: string[], types: string[], notes? }
 */
export async function POST(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  try {
    const body = (await req.json()) as {
      userId?: string;
      work?: string;
      chapters?: string[];
      types?: string[];
      notes?: string;
    };
    if (!body.userId || !body.work || !Array.isArray(body.chapters) || body.chapters.length === 0) {
      return json({ error: "بيانات ناقصة: العضو والعمل والفصول مطلوبة" }, 400);
    }
    const store = getStore();
    const [records, works, settings, { key: monthKey }] = await Promise.all([
      store.getRecords(),
      store.getWorks(),
      store.getSettings(),
      getActiveMonth(store),
    ]);
    const work = works.find((w) => w.name === body.work);
    if (!work) return json({ error: "العمل غير موجود" }, 404);
    if (work.isolated) return json({ error: "العمل معزول — لا يمكن التسجيل له" }, 400);

    const types = Array.isArray(body.types) && body.types.length === body.chapters.length
      ? body.types
      : body.chapters.map(() => (Array.isArray(body.types) && body.types.length > 0 ? body.types[0] : "تحرير"));

    const memberDocs = await store.getMembers();
    const usernameHint = memberDocs[body.userId]?.nickname || memberDocs[body.userId]?.username || auth.username;

    const added: string[] = [];
    const skipped: Array<{ chapter: string; reason: string }> = [];
    let gained = 0;
    const nowIso = new Date().toISOString();

    (records[body.userId] ||= []);
    for (let i = 0; i < body.chapters.length; i++) {
      const ch = String(body.chapters[i]).trim();
      const type = String(types[i]).trim();
      if (!ch) continue;
      const dup = records[body.userId].some(
        (e) => e.work_name === work.name && e.chapter === ch && e.work_type === type
      );
      if (dup) {
        skipped.push({ chapter: ch, reason: "مكرر" });
        continue;
      }
      // فصول مجانية قبل paid_start
      const chNum = Number(ch);
      if (work.paid_start !== null && work.paid_start !== undefined && !Number.isNaN(chNum) && chNum < work.paid_start) {
        skipped.push({ chapter: ch, reason: `مجاني (قبل الفصل ${work.paid_start})` });
        continue;
      }
      const total = resolvePrice(work, type, settings);
      records[body.userId].push({
        work_name: work.name,
        chapter: ch,
        work_type: type,
        total,
        notes: body.notes || "",
        timestamp: nowIso,
        month_key: monthKey,
        username: String(usernameHint),
        added_by: auth.id,
      });
      gained += total;
      added.push(ch);
    }

    if (added.length === 0) {
      return json({ error: "لم يُسجّل شيء جديد — كل الفصول إما مكررة أو مجانية", added: [], skipped }, 409);
    }
    const saved = await store.saveRecords(records);
    if (!saved) return json({ error: "تعذر الحفظ — قاعدة البيانات غير متاحة ولم يُطبق شيء" }, 503);
    await store.upsertMember(body.userId, { username: String(usernameHint) });
    await logAudit(store, "تسجيل_عمل", auth.id, body.userId, `${added.length} فصل في ${work.name} (${types[0]})`);
    return json({ ok: true, added, skipped, gained });
  } catch (e) {
    console.error("[RECORDS/POST]", e);
    return json({ error: "تعذر التسجيل" }, 500);
  }
}

/** حذف سجل محدد — يتطابق عبر (userId, work_name, chapter, work_type, timestamp) */
export async function DELETE(req: Request) {
  const auth = await requireAuth();
  if (isResponse(auth)) return auth;
  if (!auth.isAdmin) return json({ error: "للمشرفين فقط" }, 403);
  try {
    const body = (await req.json()) as {
      userId?: string;
      work_name?: string;
      chapter?: string;
      work_type?: string;
      timestamp?: string;
    };
    if (!body.userId || !body.work_name || !body.chapter || !body.work_type || !body.timestamp) {
      return json({ error: "تحديد السجل ناقص" }, 400);
    }
    const store = getStore();
    const records = await store.getRecords();
    const entries = records[body.userId] || [];
    const before = entries.length;
    records[body.userId] = entries.filter(
      (e) =>
        !(
          e.work_name === body.work_name &&
          e.chapter === body.chapter &&
          e.work_type === body.work_type &&
          e.timestamp === body.timestamp
        )
    );
    if (records[body.userId].length === before) {
      return json({ error: "السجل غير موجود" }, 404);
    }
    if (records[body.userId].length === 0) delete records[body.userId];
    const saved = await store.saveRecords(records);
    if (!saved) return json({ error: "تعذر الحفظ" }, 503);
    await logAudit(store, "حذف_سجل", auth.id, body.userId, `${body.work_name} — فصل ${body.chapter}`);
    return json({ ok: true });
  } catch (e) {
    console.error("[RECORDS/DELETE]", e);
    return json({ error: "تعذر الحذف" }, 500);
  }
}
