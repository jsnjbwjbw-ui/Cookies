import type { Store, AuditDoc } from "./store/types";

/** تسجيل عملية في مجموعة audit_log نفسها التي يستخدمها البوت */
export async function logAudit(
  store: Store,
  action: string,
  moderatorId: string | null,
  targetId: string | null,
  details: string,
  source: "dashboard" | "bot" = "dashboard"
): Promise<void> {
  const entry: AuditDoc = {
    action: `${action}${source === "dashboard" ? " (لوحة التحكم)" : ""}`,
    moderator_id: moderatorId,
    target_id: targetId,
    details,
    timestamp: new Date().toISOString(),
  };
  try {
    await store.logAudit(entry);
  } catch (e) {
    console.error("[AUDIT] فشل تسجيل العملية:", e);
  }
}
