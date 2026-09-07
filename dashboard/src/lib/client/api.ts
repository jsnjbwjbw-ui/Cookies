export interface MeResponse {
  authenticated: boolean;
  user: {
    id: string;
    username: string;
    globalName?: string;
    avatar?: string;
    isAdmin: boolean;
    demo?: boolean;
  } | null;
  config: {
    oauthEnabled: boolean;
    mode: "mongo" | "demo";
    guildId: string | null;
    botLinked: boolean;
  };
}

export interface PublicStats {
  mode: "mongo" | "demo";
  members: number;
  works: number;
  chapters: number;
  revenue: number;
  activeMonthName: string;
  lastUpdated: string;
}

export interface LiveEventDTO {
  kind: "record" | "audit";
  at: string;
  user_id?: string;
  username?: string;
  title: string;
  detail?: string;
  amount?: number;
  source: "bot" | "dashboard";
}

export interface MemberDTO {
  id: string;
  name: string;
  username?: string;
  nickname?: string;
  avatar?: string;
  firstSeen?: string;
  lastSeen?: string;
  isMember: boolean;
  chaptersThisMonth: number;
  amountThisMonth: number;
  chaptersAllTime: number;
  hasActivityThisMonth: boolean;
  lastActivity?: string;
  perWork: Record<string, number>;
  perType: Record<string, number>;
}

export interface WorkStatDTO {
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

export interface OverviewDTO {
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
  workStats: WorkStatDTO[];
  lastUpdated: string;
}

export interface MonthDTO {
  _id: string;
  name?: string;
  created_at?: string;
  created_by?: string;
  recordsCount: number;
  chapters: number;
  amount: number;
}

export interface RecordDTO {
  userId: string;
  memberName: string;
  entry: {
    work_name: string;
    chapter: string;
    work_type: string;
    total: number;
    notes: string;
    timestamp: string;
    month_key: string;
    username: string;
    added_by?: string;
  };
}

export interface SpecialtiesDTO {
  specialties: Record<string, { price: number; active: boolean; last_modified?: string }>;
  currency: string;
  works: Array<{ name: string; custom_prices: Record<string, number> }>;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) {
    throw new Error(data.error || `خطأ ${res.status}`);
  }
  return data;
}

export const api = {
  me: () => request<MeResponse>("/api/auth/me"),
  publicStats: () => request<PublicStats>("/api/public/stats"),
  demoLogin: () => request<{ ok: boolean }>("/api/auth/demo", { method: "POST" }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  overview: () => request<OverviewDTO>("/api/overview"),
  members: () => request<{ members: MemberDTO[]; activeMonth: string }>("/api/members"),
  updateNickname: (id: string, nickname: string) =>
    request<{ ok: boolean }>("/api/members", { method: "PATCH", body: JSON.stringify({ id, nickname }) }),

  works: () => request<{ works: Array<{ name: string; isolated?: boolean; paid_start?: number | null; custom_prices?: Record<string, number> }>; stats: WorkStatDTO[]; activeMonth: string }>("/api/works"),
  addWork: (name: string, paid_start: number | null) =>
    request<{ ok: boolean }>("/api/works", { method: "POST", body: JSON.stringify({ name, paid_start }) }),
  patchWork: (payload: { name: string; newName?: string; paid_start?: number | null; isolated?: boolean }) =>
    request<{ ok: boolean }>("/api/works", { method: "PATCH", body: JSON.stringify(payload) }),
  deleteWork: (name: string) => request<{ ok: boolean }>(`/api/works?name=${encodeURIComponent(name)}`, { method: "DELETE" }),

  records: (params: URLSearchParams) => request<{ records: RecordDTO[] }>(`/api/records?${params}`),
  addRecord: (payload: { userId: string; work: string; chapters: string[]; types: string[]; notes?: string }) =>
    request<{ ok: boolean; added: string[]; skipped: Array<{ chapter: string; reason: string }>; gained: number }>("/api/records", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteRecord: (payload: { userId: string; work_name: string; chapter: string; work_type: string; timestamp: string }) =>
    request<{ ok: boolean }>("/api/records", { method: "DELETE", body: JSON.stringify(payload) }),

  months: () => request<{ months: MonthDTO[]; activeMonth: string }>("/api/months"),
  addMonth: (payload: { key?: string; name?: string; activate?: boolean }) =>
    request<{ ok: boolean; key: string }>("/api/months", { method: "POST", body: JSON.stringify(payload) }),
  patchMonth: (payload: { key: string; name?: string; activate?: boolean }) =>
    request<{ ok: boolean }>("/api/months", { method: "PATCH", body: JSON.stringify(payload) }),
  deleteMonth: (key: string) => request<{ ok: boolean; removed: number }>(`/api/months?key=${key}`, { method: "DELETE" }),

  specialties: () => request<SpecialtiesDTO>("/api/specialties"),
  addSpecialty: (name: string, price: number) =>
    request<{ ok: boolean }>("/api/specialties", { method: "POST", body: JSON.stringify({ name, price }) }),
  patchSpecialty: (payload: { name: string; price?: number; active?: boolean; work?: string }) =>
    request<{ ok: boolean }>("/api/specialties", { method: "PATCH", body: JSON.stringify(payload) }),
  deleteSpecialty: (name: string, work?: string, toGlobal?: boolean) => {
    const p = new URLSearchParams({ name });
    if (work) p.set("work", work);
    if (toGlobal) p.set("toGlobal", "1");
    return request<{ ok: boolean }>(`/api/specialties?${p}`, { method: "DELETE" });
  },

  settings: () =>
    request<{
      settings: { currency: string; alert_threshold: number; allowed_channels: (number | string)[]; payment_day: number | null; active_month: string };
      activeMonthName: string;
    }>("/api/settings"),
  patchSettings: (payload: { currency?: string; alert_threshold?: number }) =>
    request<{ ok: boolean }>("/api/settings", { method: "PATCH", body: JSON.stringify(payload) }),

  live: () =>
    request<{ events: LiveEventDTO[]; totalRecords: number; dbUp: boolean; serverTime: string; pulse?: LiveEventDTO | null }>("/api/live"),
  syncDiscord: () => request<{ ok: boolean; synced: number }>("/api/sync/discord", { method: "POST" }),
};
