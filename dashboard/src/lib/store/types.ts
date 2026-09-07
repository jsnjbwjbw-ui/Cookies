/**
 * أنواع بيانات كوكيز تراكر — مرآة مطابقة 1:1 لمخطط MongoDB الخاص بالبوت
 * (فرع v4-months-and-persistence: database.py + helpers/core.py)
 *
 * المجموعات:
 *   records    → وثيقتان: {_id:"records", data:{[userId]: RecordEntry[]}} و {_id:"works", data: WorkDoc[]}
 *   settings   → {_id:"settings", ...}
 *   audit_log  → سجل عمليات
 *   stats      → {_id:"stats:{month_key}", ...} (يحسبها البوت — الداشبورد يحسب هو أيضًا من السجلات)
 *   members    → {_id: userId, username, first_seen, last_seen}
 *   months     → {_id:"YYYY-MM", name, created_at, created_by}
 */

export interface RecordEntry {
  work_name: string;
  chapter: string;
  work_type: string; // تخصص أو "مكافأة" أو "خصم"
  total: number; // سعر الفصل — الخصم يُخزن سالبًا
  notes: string;
  timestamp: string; // ISO
  month_key: string; // "YYYY-MM"
  username: string;
  added_by?: string;
}

export interface WorkDoc {
  name: string;
  isolated?: boolean;
  paid_start?: number | null;
  custom_prices?: Record<string, number>;
}

export interface SpecialtyDoc {
  price: number;
  active: boolean;
  last_modified?: string;
}

export interface SettingsDoc {
  allowed_channels: (number | string)[];
  currency: string;
  notify_channel_id?: number | null;
  daily_backup_channel_id?: number | null;
  alert_threshold?: number;
  specialties: Record<string, SpecialtyDoc>;
  payment_day?: number | null;
  payment_hour?: number;
  active_month?: string;
  [key: string]: unknown;
}

export interface MemberDoc {
  _id: string;
  username?: string;
  nickname?: string;
  avatar?: string;
  first_seen?: string;
  last_seen?: string;
}

export interface MonthDoc {
  _id: string; // "YYYY-MM"
  name?: string;
  created_at?: string;
  created_by?: string;
}

export interface AuditDoc {
  action: string;
  moderator_id?: string | null;
  target_id?: string | null;
  details?: string;
  timestamp: string;
}

export interface LiveEvent {
  kind: "record" | "audit";
  at: string;
  user_id?: string;
  username?: string;
  title: string;
  detail?: string;
  amount?: number;
  source: "bot" | "dashboard";
}

export interface Store {
  mode: "mongo" | "demo";
  ping(): Promise<boolean>;

  getRecords(): Promise<Record<string, RecordEntry[]>>;
  saveRecords(records: Record<string, RecordEntry[]>, opts?: { allowWipe?: boolean }): Promise<boolean>;

  getWorks(): Promise<WorkDoc[]>;
  saveWorks(works: WorkDoc[], opts?: { allowWipe?: boolean }): Promise<boolean>;

  getSettings(): Promise<SettingsDoc>;
  saveSettings(settings: SettingsDoc): Promise<boolean>;

  getMembers(): Promise<Record<string, MemberDoc>>;
  upsertMember(id: string, patch: Partial<MemberDoc>): Promise<void>;

  getMonths(): Promise<MonthDoc[]>;
  ensureMonth(key: string, createdBy?: string): Promise<void>;
  updateMonth(key: string, patch: Partial<Omit<MonthDoc, "_id">>): Promise<void>;
  deleteMonth(key: string): Promise<void>;

  getAudit(limit: number): Promise<AuditDoc[]>;
  logAudit(entry: AuditDoc): Promise<void>;
}

export function monthKeyOf(entry: RecordEntry): string {
  if (entry.month_key && /^\d{4}-\d{2}$/.test(entry.month_key)) return entry.month_key;
  const ts = entryDateTime(entry);
  return ts ? ts.toISOString().slice(0, 7) : "unknown";
}

export function entryDateTime(entry: RecordEntry): Date | null {
  if (!entry.timestamp) return null;
  const d = new Date(entry.timestamp);
  return isNaN(d.getTime()) ? null : d;
}

export function currentMonthKey(): string {
  return new Date().toISOString().slice(0, 7);
}

export function isMonthKey(v: unknown): v is string {
  return typeof v === "string" && /^\d{4}-\d{2}$/.test(v);
}

export function monthLabel(key: string): string {
  const [y, m] = key.split("-").map(Number);
  const names = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
  ];
  return `${names[(m || 1) - 1]} ${y}`;
}
