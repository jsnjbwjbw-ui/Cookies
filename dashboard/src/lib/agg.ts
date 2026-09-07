import type { Store, RecordEntry, WorkDoc, SettingsDoc, MemberDoc, LiveEvent } from "./store/types";
import { monthKeyOf, entryDateTime, currentMonthKey, isMonthKey, monthLabel } from "./store/types";

export interface MemberInfo {
  id: string;
  name: string; // النك نيم إن وجد، وإلا username، وإلا المعرف
  username?: string;
  nickname?: string;
  avatar?: string;
  firstSeen?: string;
  lastSeen?: string;
  isMember: boolean; // موجود في مجموعة members بالبوت
}

export interface MemberTotal {
  userId: string;
  name: string;
  avatar?: string;
  chapters: number;
  amount: number; // صافي (الخصومات سالبة أصلاً)
  bonuses: number;
  deductions: number; // موجب دائمًا للعرض
  worksCount: number;
  lastActivity?: string;
  perWork: Record<string, number>;
  perType: Record<string, number>;
}

export interface WorkStat {
  name: string;
  isolated: boolean;
  paidStart: number | null;
  customPrices?: Record<string, number>;
  chaptersAllTime: number;
  chaptersThisMonth: number;
  contributors: number;
  amountThisMonth: number;
  lastActivity?: string;
}

export interface OverviewData {
  mode: "mongo" | "demo";
  dbUp: boolean;
  activeMonth: string;
  activeMonthName: string;
  currency: string;
  totals: {
    members: number;
    activeMembers: number;
    inactiveMembers: number;
    works: number;
    chapters: number;
    revenue: number;
    bonuses: number;
    deductions: number;
  };
  topMembers: Array<{ userId: string; name: string; avatar?: string; amount: number; chapters: number }>;
  dailySeries: Array<{ date: string; label: string; count: number; amount: number }>;
  specialtyCounts: Array<{ type: string; count: number; amount: number }>;
  workStats: WorkStat[];
  lastUpdated: string;
}

export function isolatedNames(works: WorkDoc[]): Set<string> {
  return new Set(works.filter((w) => w.isolated && w.name).map((w) => w.name));
}

export async function getActiveMonth(store: Store): Promise<{ key: string; name: string }> {
  const settings = await store.getSettings();
  const key = isMonthKey(settings.active_month) ? settings.active_month : currentMonthKey();
  const months = await store.getMonths();
  const doc = months.find((m) => m._id === key);
  return { key, name: doc?.name || `شهر ${key}` };
}

export async function memberDirectory(store: Store, records: Record<string, RecordEntry[]>): Promise<Map<string, MemberInfo>> {
  const memberDocs = await store.getMembers();
  const map = new Map<string, MemberInfo>();
  const ids = new Set<string>([...Object.keys(memberDocs), ...Object.keys(records)]);
  for (const id of ids) {
    const doc: MemberDoc | undefined = memberDocs[id];
    const hint = (records[id] || []).find((e) => e.username)?.username;
    map.set(id, {
      id,
      name: doc?.nickname || doc?.username || hint || id,
      username: doc?.username || hint,
      nickname: doc?.nickname,
      avatar: doc?.avatar,
      firstSeen: doc?.first_seen,
      lastSeen: doc?.last_seen,
      isMember: Boolean(memberDocs[id]),
    });
  }
  return map;
}

export function entriesForMonth(records: Record<string, RecordEntry[]>, monthKey: string, isolated: Set<string>): Record<string, RecordEntry[]> {
  const out: Record<string, RecordEntry[]> = {};
  for (const [uid, entries] of Object.entries(records)) {
    const filtered = entries.filter(
      (e) => monthKeyOf(e) === monthKey && (!e.work_name || !isolated.has(e.work_name))
    );
    if (filtered.length) out[uid] = filtered;
  }
  return out;
}

export function computeMemberTotals(
  monthEntries: Record<string, RecordEntry[]>,
  directory: Map<string, MemberInfo>
): MemberTotal[] {
  const totals: MemberTotal[] = [];
  for (const [userId, entries] of Object.entries(monthEntries)) {
    let amount = 0;
    let bonuses = 0;
    let deductions = 0;
    let chapters = 0;
    let lastActivity: string | undefined;
    const perWork: Record<string, number> = {};
    const perType: Record<string, number> = {};
    for (const e of entries) {
      amount += e.total || 0;
      if (e.work_type === "مكافأة") bonuses += e.total || 0;
      else if (e.work_type === "خصم") deductions += Math.abs(e.total || 0);
      else {
        chapters += 1;
        perWork[e.work_name || "غير محدد"] = (perWork[e.work_name || "غير محدد"] || 0) + 1;
        perType[e.work_type || "غير محدد"] = (perType[e.work_type || "غير محدد"] || 0) + 1;
      }
      if (!lastActivity || (entryDateTime(e)?.getTime() ?? 0) > (new Date(lastActivity).getTime() || 0)) {
        lastActivity = e.timestamp;
      }
    }
    const info = directory.get(userId);
    totals.push({
      userId,
      name: info?.name || userId,
      avatar: info?.avatar,
      chapters,
      amount,
      bonuses,
      deductions,
      worksCount: Object.keys(perWork).length,
      lastActivity,
      perWork,
      perType,
    });
  }
  return totals.sort((a, b) => b.amount - a.amount);
}

export function computeWorkStats(records: Record<string, RecordEntry[]>, works: WorkDoc[], monthKey: string): WorkStat[] {
  const iso = isolatedNames(works);
  return works.map((w) => {
    let chaptersAllTime = 0;
    let chaptersThisMonth = 0;
    let amountThisMonth = 0;
    let lastActivity: string | undefined;
    const contributors = new Set<string>();
    for (const [uid, entries] of Object.entries(records)) {
      for (const e of entries) {
        if (e.work_name !== w.name) continue;
        if (e.work_type === "مكافأة" || e.work_type === "خصم") continue;
        chaptersAllTime += 1;
        if (monthKeyOf(e) === monthKey) {
          chaptersThisMonth += 1;
          amountThisMonth += e.total || 0;
        }
        contributors.add(uid);
        const t = entryDateTime(e)?.toISOString();
        if (t && (!lastActivity || t > lastActivity)) lastActivity = t;
      }
    }
    return {
      name: w.name,
      isolated: Boolean(w.isolated),
      paidStart: w.paid_start ?? null,
      customPrices: w.custom_prices,
      chaptersAllTime,
      chaptersThisMonth,
      contributors: contributors.size,
      amountThisMonth,
      lastActivity,
    };
  });
}

export function dailySeries(records: Record<string, RecordEntry[]>, monthKey: string, days: number) {
  const now = new Date();
  const out: Array<{ date: string; label: string; count: number; amount: number }> = [];
  const counts = new Map<string, { count: number; amount: number }>();
  for (const entries of Object.values(records)) {
    for (const e of entries) {
      if (monthKeyOf(e) !== monthKey) continue;
      const d = entryDateTime(e);
      if (!d) continue;
      const key = d.toISOString().slice(0, 10);
      const agg = counts.get(key) || { count: 0, amount: 0 };
      agg.count += 1;
      agg.amount += e.total || 0;
      counts.set(key, agg);
    }
  }
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 86400000);
    const key = d.toISOString().slice(0, 10);
    const agg = counts.get(key) || { count: 0, amount: 0 };
    out.push({
      date: key,
      label: `${d.getUTCDate()}/${d.getUTCMonth() + 1}`,
      count: agg.count,
      amount: agg.amount,
    });
  }
  return out;
}

export function specialtyBreakdown(records: Record<string, RecordEntry[]>, monthKey: string) {
  const map = new Map<string, { count: number; amount: number }>();
  for (const entries of Object.values(records)) {
    for (const e of entries) {
      if (monthKeyOf(e) !== monthKey) continue;
      if (e.work_type === "مكافأة" || e.work_type === "خصم") continue;
      const agg = map.get(e.work_type) || { count: 0, amount: 0 };
      agg.count += 1;
      agg.amount += e.total || 0;
      map.set(e.work_type, agg);
    }
  }
  return [...map.entries()]
    .map(([type, v]) => ({ type, ...v }))
    .sort((a, b) => b.count - a.count);
}

export async function buildOverview(store: Store, mode: "mongo" | "demo"): Promise<OverviewData> {
  const [records, works, { key: activeMonth, name: activeMonthName }, settings] = await Promise.all([
    store.getRecords(),
    store.getWorks(),
    getActiveMonth(store),
    store.getSettings(),
  ]);
  const iso = isolatedNames(works);
  const monthEntries = entriesForMonth(records, activeMonth, iso);
  const directory = await memberDirectory(store, records);
  const totals = computeMemberTotals(monthEntries, directory);

  const chapters = totals.reduce((s, t) => s + t.chapters, 0);
  const revenue = totals.reduce((s, t) => s + t.amount, 0);
  const bonuses = totals.reduce((s, t) => s + t.bonuses, 0);
  const deductions = totals.reduce((s, t) => s + t.deductions, 0);
  const activeMembers = totals.filter((t) => t.chapters > 0 || t.bonuses > 0 || t.deductions > 0).length;

  return {
    mode,
    dbUp: await store.ping(),
    activeMonth,
    activeMonthName,
    currency: settings.currency || "$",
    totals: {
      members: directory.size,
      activeMembers,
      inactiveMembers: Math.max(0, directory.size - activeMembers),
      works: works.length,
      chapters,
      revenue,
      bonuses,
      deductions,
    },
    topMembers: totals.slice(0, 5).map((t) => ({
      userId: t.userId,
      name: t.name,
      avatar: t.avatar,
      amount: t.amount,
      chapters: t.chapters,
    })),
    dailySeries: dailySeries(records, activeMonth, 14),
    specialtyCounts: specialtyBreakdown(records, activeMonth),
    workStats: computeWorkStats(records, works, activeMonth),
    lastUpdated: new Date().toISOString(),
  };
}

export async function buildLiveEvents(store: Store, limit = 24): Promise<LiveEvent[]> {
  const records = await store.getRecords();
  const flat: Array<LiveEvent & { at: string }> = [];
  for (const [uid, entries] of Object.entries(records)) {
    for (const e of entries.slice(-40)) {
      const isBonus = e.work_type === "مكافأة";
      const isDed = e.work_type === "خصم";
      flat.push({
        kind: "record",
        at: e.timestamp,
        user_id: uid,
        username: e.username,
        source: "bot",
        amount: e.total,
        title: isBonus ? "مكافأة جديدة" : isDed ? "خصم جديد" : `تسجيل — ${e.work_name}`,
        detail: isBonus || isDed ? e.notes || undefined : `الفصل ${e.chapter} • ${e.work_type.replace("_", " ")}`,
      });
    }
  }
  const audit = await store.getAudit(12);
  for (const a of audit) {
    flat.push({
      kind: "audit",
      at: a.timestamp,
      user_id: a.moderator_id || undefined,
      source: "bot",
      title: a.action.replace(/_/g, " "),
      detail: a.details || undefined,
    });
  }
  flat.sort((a, b) => (b.at || "").localeCompare(a.at || ""));
  return flat.slice(0, limit);
}

/** سعر التخصص لأمر تسجيل — مطابق لمنطق البوت: تخصيص العمل أولًا ثم العام النشط */
export function resolvePrice(work: WorkDoc, type: string, settings: SettingsDoc): number {
  if (work.custom_prices && type in work.custom_prices) return work.custom_prices[type];
  return settings.specialties?.[type]?.price ?? 0;
}

export function monthNameOr(key: string, months: Array<{ _id: string; name?: string }>): string {
  return months.find((m) => m._id === key)?.name || monthLabel(key);
}
