import type { Store } from "./types";
import { MongoStore } from "./mongo";
import { DemoStore } from "./demo";

let cached: Store | null = null;

/**
 * يختار المتجر المناسب:
 * - MONGODB_URI موجود → متجر Mongo حقيقي متصل بنفس قاعدة البوت (نفس البيانات لحظيًا).
 * - غير موجود → وضع تجريبي غني بالبيانات (للمعاينة والتطوير فقط).
 */
export function getStore(): Store {
  if (cached) return cached;
  const uri = process.env.MONGODB_URI;
  if (uri) {
    cached = new MongoStore(uri, process.env.MONGODB_DB_NAME || "work_bot");
  } else {
    cached = new DemoStore();
  }
  return cached;
}
