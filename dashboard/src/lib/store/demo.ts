import fs from "node:fs/promises";
import path from "node:path";
import type { Store, RecordEntry, WorkDoc, SettingsDoc, MemberDoc, MonthDoc, AuditDoc, LiveEvent } from "./types";
import { DEFAULT_SPECIALTIES, BONUS_WORK_NAME } from "./defaults";
import { buildDemoData, DEMO_MEMBERS, DEMO_WORKS } from "./demo-seed";
import { currentMonthKey, monthKeyOf } from "./types";

interface DemoFile {
  records: Record<string, RecordEntry[]>;
  works: WorkDoc[];
  members: Record<string, MemberDoc>;
  months: MonthDoc[];
  settings: SettingsDoc;
  audit: AuditDoc[];
  lastPulseAt?: string;
}

/**
 * متجر تجريبي — يعمل فقط بدون MONGODB_URI.
 * نفس شكل بيانات البوت بالضبط لكنه محفوظ في db/demo-store.json.
 * فيه "نبض حي" يولّد تسجيلات دورية ليظهر التحديث اللحظي في المعاينة.
 */
export class DemoStore implements Store {
  mode = "demo" as const;
  private data: DemoFile | null = null;
  private file: string;
  private saving: Promise<void> | null = null;

  constructor() {
    this.file = path.join(process.cwd(), "db", "demo-store.json");
  }

  async ping(): Promise<boolean> {
    await this.load();
    return true;
  }

  private async load(): Promise<DemoFile> {
    if (this.data) return this.data;
    try {
      const raw = await fs.readFile(this.file, "utf8");
      this.data = JSON.parse(raw) as DemoFile;
      if (!this.data.settings?.active_month) throw new Error("stale");
    } catch {
      const now = new Date();
      const seeded = buildDemoData(now);
      this.data = { ...seeded, lastPulseAt: now.toISOString() };
      await this.persist();
    }
    return this.data;
  }

  private async persist(): Promise<void> {
    if (!this.data) return;
    if (this.saving) return this.saving;
    const snapshot = JSON.stringify(this.data);
    this.saving = (async () => {
      try {
        await fs.mkdir(path.dirname(this.file), { recursive: true });
        const tmp = this.file + ".tmp";
        await fs.writeFile(tmp, snapshot, "utf8");
        await fs.rename(tmp, this.file);
      } catch (e) {
        console.error("[DEMO] persist failed:", e);
      } finally {
        this.saving = null;
      }
    })();
    return this.saving;
  }

  async getRecords(): Promise<Record<string, RecordEntry[]>> {
    return (await this.load()).records;
  }

  async saveRecords(records: Record<string, RecordEntry[]>, opts?: { allowWipe?: boolean }): Promise<boolean> {
    const d = await this.load();
    const hasData = Object.keys(d.records).length > 0;
    if (hasData && Object.keys(records).length === 0 && !opts?.allowWipe) {
      console.error("[SAFETY][DEMO] رفض استبدال سجلات غير فارغة بقاموس فارغ");
      return false;
    }
    d.records = records;
    await this.persist();
    return true;
  }

  async getWorks(): Promise<WorkDoc[]> {
    return (await this.load()).works;
  }

  async saveWorks(works: WorkDoc[], opts?: { allowWipe?: boolean }): Promise<boolean> {
    const d = await this.load();
    if (d.works.length > 0 && works.length === 0 && !opts?.allowWipe) {
      console.error("[SAFETY][DEMO] رفض استبدال أعمال غير فارغة بقائمة فارغة");
      return false;
    }
    d.works = works;
    await this.persist();
    return true;
  }

  async getSettings(): Promise<SettingsDoc> {
    const d = await this.load();
    if (!d.settings.specialties || Object.keys(d.settings.specialties).length === 0) {
      d.settings.specialties = { ...DEFAULT_SPECIALTIES };
    }
    return d.settings;
  }

  async saveSettings(settings: SettingsDoc): Promise<boolean> {
    const d = await this.load();
    const { _id, ...rest } = settings as SettingsDoc & { _id?: string };
    d.settings = rest;
    await this.persist();
    return true;
  }

  async getMembers(): Promise<Record<string, MemberDoc>> {
    return (await this.load()).members;
  }

  async upsertMember(id: string, patch: Partial<MemberDoc>): Promise<void> {
    const d = await this.load();
    const existing = d.members[id] || { _id: id, first_seen: new Date().toISOString() };
    d.members[id] = { ...existing, ...patch, _id: id, last_seen: new Date().toISOString() };
    await this.persist();
  }

  async getMonths(): Promise<MonthDoc[]> {
    return [...(await this.load()).months].sort((a, b) => a._id.localeCompare(b._id));
  }

  async ensureMonth(key: string, createdBy?: string): Promise<void> {
    const d = await this.load();
    if (!d.months.some((m) => m._id === key)) {
      d.months.push({ _id: key, name: `شهر ${key}`, created_at: new Date().toISOString(), created_by: createdBy });
      await this.persist();
    }
  }

  async updateMonth(key: string, patch: Partial<Omit<MonthDoc, "_id">>): Promise<void> {
    const d = await this.load();
    const m = d.months.find((x) => x._id === key);
    if (m) {
      Object.assign(m, patch);
      await this.persist();
    }
  }

  async deleteMonth(key: string): Promise<void> {
    const d = await this.load();
    d.months = d.months.filter((m) => m._id !== key);
    await this.persist();
  }

  async getAudit(limit: number): Promise<AuditDoc[]> {
    const list = [...(await this.load()).audit];
    list.sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""));
    return list.slice(0, limit);
  }

  async logAudit(entry: AuditDoc): Promise<void> {
    const d = await this.load();
    d.audit.unshift(entry);
    if (d.audit.length > 500) d.audit.length = 500;
    await this.persist();
  }

  /** نبض حي: يولّد تسجيلًا جديدًا كل ~45 ثانية ليشعر الزائر بالتحديث اللحظي */
  async pulse(): Promise<LiveEvent | null> {
    const d = await this.load();
    const last = d.lastPulseAt ? new Date(d.lastPulseAt).getTime() : 0;
    if (Date.now() - last < 45_000) return null;

    const activeKey = d.settings.active_month || currentMonthKey();
    const member = DEMO_MEMBERS[Math.floor(Math.random() * DEMO_MEMBERS.length)];
    const work = DEMO_WORKS.filter((w) => !w.isolated)[Math.floor(Math.random() * 6)] || DEMO_WORKS[0];
    const types = Object.keys(DEFAULT_SPECIALTIES);
    const type = types[Math.floor(Math.random() * types.length)];
    const price =
      work.custom_prices && type in work.custom_prices
        ? work.custom_prices[type]
        : (d.settings.specialties[type]?.price ?? DEFAULT_SPECIALTIES[type]?.price ?? 0.05);

    const entry: RecordEntry = {
      work_name: work.name,
      chapter: String(1 + Math.floor(Math.random() * 200)),
      work_type: type,
      total: price,
      notes: "",
      timestamp: new Date().toISOString(),
      month_key: activeKey,
      username: member.username,
    };
    (d.records[member.id] ||= []).push(entry);
    d.lastPulseAt = entry.timestamp;

    const auditEntry: AuditDoc = {
      action: "تسجيل_عمل",
      moderator_id: member.id,
      target_id: member.id,
      details: `${member.nickname} سجل الفصل ${entry.chapter} في ${work.name}`,
      timestamp: entry.timestamp,
    };
    d.audit.unshift(auditEntry);
    await this.persist();

    return {
      kind: "record",
      at: entry.timestamp,
      user_id: member.id,
      username: member.nickname,
      title: `تسجيل جديد — ${work.name}`,
      detail: `الفصل ${entry.chapter} • ${type.replace("_", " ")}`,
      amount: entry.total,
      source: "bot",
    };
  }
}
