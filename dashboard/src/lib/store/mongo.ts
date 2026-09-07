import { MongoClient } from "mongodb";
import type { Store, RecordEntry, WorkDoc, SettingsDoc, MemberDoc, MonthDoc, AuditDoc } from "./types";
import { DEFAULT_SPECIALTIES } from "./defaults";

/**
 * متجر MongoDB الحقيقي — يقرأ ويكتب **نفس** مجموعات البوت تمامًا،
 * فأي تسجيل من ديسكورد يظهر هنا لحظيًا والعكس صحيح.
 * نفس حرسات البوت ضد الكتابة الفارغة (anti-wipe) مطبقة هنا أيضًا.
 */
export class MongoStore implements Store {
  mode = "mongo" as const;
  private client: MongoClient;
  private dbName: string;

  constructor(uri: string, dbName?: string) {
    this.client = new MongoClient(uri, {
      serverSelectionTimeoutMS: 8000,
      retryWrites: true,
      appName: "cookies-tracker-dashboard",
    });
    this.dbName = dbName || "work_bot";
  }

  private db() {
    return this.client.db(this.dbName);
  }

  async ping(): Promise<boolean> {
    try {
      await this.client.db("admin").command({ ping: 1 });
      return true;
    } catch {
      return false;
    }
  }

  async getRecords(): Promise<Record<string, RecordEntry[]>> {
    const doc = await this.db().collection("records").findOne({ _id: "records" });
    if (doc && "data" in doc && doc.data && typeof doc.data === "object") {
      return doc.data as Record<string, RecordEntry[]>;
    }
    return {};
  }

  async saveRecords(records: Record<string, RecordEntry[]>, opts?: { allowWipe?: boolean }): Promise<boolean> {
    if (!opts?.allowWipe) {
      const existing = await this.db().collection("records").findOne({ _id: "records" }, { projection: { data: 1 } });
      const hasData = existing?.data && Object.keys(existing.data as object).length > 0;
      if (hasData && Object.keys(records).length === 0) {
        console.error("[SAFETY] رفض استبدال سجلات غير فارغة بقاموس فارغ");
        return false;
      }
    }
    try {
      await this.db().collection("records").updateOne({ _id: "records" }, { $set: { data: records } }, { upsert: true });
      return true;
    } catch (e) {
      console.error("[ERROR] saveRecords:", e);
      return false;
    }
  }

  async getWorks(): Promise<WorkDoc[]> {
    const doc = await this.db().collection("records").findOne({ _id: "works" });
    if (doc && Array.isArray(doc.data)) return doc.data as WorkDoc[];
    return [];
  }

  async saveWorks(works: WorkDoc[], opts?: { allowWipe?: boolean }): Promise<boolean> {
    if (!opts?.allowWipe) {
      const existing = await this.db().collection("records").findOne({ _id: "works" }, { projection: { data: 1 } });
      const hasData = existing?.data && (existing.data as unknown[]).length > 0;
      if (hasData && works.length === 0) {
        console.error("[SAFETY] رفض استبدال أعمال غير فارغة بقائمة فارغة");
        return false;
      }
    }
    try {
      await this.db().collection("records").updateOne({ _id: "works" }, { $set: { data: works } }, { upsert: true });
      return true;
    } catch (e) {
      console.error("[ERROR] saveWorks:", e);
      return false;
    }
  }

  async getSettings(): Promise<SettingsDoc> {
    const doc = (await this.db().collection("settings").findOne({ _id: "settings" })) as (SettingsDoc & { _id: string }) | null;
    if (doc) {
      if (!doc.specialties || Object.keys(doc.specialties).length === 0) doc.specialties = { ...DEFAULT_SPECIALTIES };
      if (doc.payment_day === undefined) doc.payment_day = null;
      return doc;
    }
    return {
      allowed_channels: [],
      currency: "$",
      notify_channel_id: null,
      alert_threshold: 10.0,
      specialties: { ...DEFAULT_SPECIALTIES },
      payment_day: null,
      payment_hour: 0,
    };
  }

  async saveSettings(settings: SettingsDoc): Promise<boolean> {
    try {
      const { _id, ...rest } = settings as SettingsDoc & { _id?: string };
      await this.db().collection("settings").updateOne({ _id: "settings" }, { $set: rest }, { upsert: true });
      return true;
    } catch (e) {
      console.error("[ERROR] saveSettings:", e);
      return false;
    }
  }

  async getMembers(): Promise<Record<string, MemberDoc>> {
    const docs = await this.db().collection("members").find({}).limit(5000).toArray();
    const out: Record<string, MemberDoc> = {};
    for (const d of docs) out[String(d._id)] = { ...(d as unknown as MemberDoc), _id: String(d._id) };
    return out;
  }

  async upsertMember(id: string, patch: Partial<MemberDoc>): Promise<void> {
    await this.db().collection("members").updateOne(
      { _id: id },
      {
        $set: { ...patch, last_seen: new Date().toISOString() },
        $setOnInsert: { first_seen: new Date().toISOString() },
      },
      { upsert: true }
    );
  }

  async getMonths(): Promise<MonthDoc[]> {
    const docs = await this.db().collection("months").find({}).toArray();
    return docs
      .map((d) => ({ ...(d as unknown as MonthDoc), _id: String(d._id) }))
      .sort((a, b) => a._id.localeCompare(b._id));
  }

  async ensureMonth(key: string, createdBy?: string): Promise<void> {
    const setOnInsert: Record<string, unknown> = {
      name: `شهر ${key}`,
      created_at: new Date().toISOString(),
    };
    if (createdBy) setOnInsert.created_by = createdBy;
    await this.db().collection("months").updateOne({ _id: key }, { $setOnInsert: setOnInsert }, { upsert: true });
  }

  async updateMonth(key: string, patch: Partial<Omit<MonthDoc, "_id">>): Promise<void> {
    await this.db().collection("months").updateOne({ _id: key }, { $set: patch }, { upsert: true });
  }

  async deleteMonth(key: string): Promise<void> {
    await this.db().collection("months").deleteOne({ _id: key });
  }

  async getAudit(limit: number): Promise<AuditDoc[]> {
    const docs = await this.db()
      .collection("audit_log")
      .find({})
      .sort({ timestamp: -1 })
      .limit(limit)
      .toArray();
    return docs as unknown as AuditDoc[];
  }

  async logAudit(entry: AuditDoc): Promise<void> {
    await this.db().collection("audit_log").insertOne({ ...entry } as never);
  }
}
