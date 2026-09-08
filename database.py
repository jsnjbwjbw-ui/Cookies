import os

from config import MONGODB_URI
import motor.motor_asyncio

# ═══════════════════════════════════════════════════════════════
# طبقة قاعدة البيانات مع حماية من فقدان البيانات:
#   1) اسم قاعدة البيانات قابل للضبط عبر متغير البيئة MONGODB_DB_NAME
#      (الافتراضي work_bot) — نفس الرابط = نفس البيانات على أي استضافة.
#   2) حالة اتصال db_ready تُدار عبر ping_db/ensure_db_ready.
#   3) الأوامر ترفض العمل عندما تكون قاعدة البيانات غير متاحة
#      (DatabaseUnavailableError) بدل القراءة فارغة ثم الكتابة فوقها.
# ═══════════════════════════════════════════════════════════════

# Currency symbol (can be changed by admin)
CURRENCY = "$"

MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "work_bot")

mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=8000,
    connectTimeoutMS=20000,
    socketTimeoutMS=30000,
    retryWrites=True,
    appName="cookies-tracker",
)
db = mongo_client[MONGODB_DB_NAME]
collection = db["records"]              # unified collection (records + works blob docs)
settings_collection = db["settings"]
audit_collection = db["audit_log"]
stats_collection = db["stats"]          # doc لكل شهر: _id = "stats:{month_key}"
members_collection = db["members"]      # الأعضاء المحفوظون عبر كل الشهور
months_collection = db["months"]        # أشهر النظام: _id = "YYYY-MM"
azora_collection = db["azora"]          # حالة وكاش نظام أزورا (منفصلة تمامًا)

# حالة الاتصال العامة (تُحدَّث من ping_db / ensure_db_ready)
db_ready = False


class DatabaseUnavailableError(Exception):
    """تُرفع عندما تكون قاعدة البيانات غير قابلة للوصول —
    الهدف: إيقاف الأمر فورًا بدل متابته ببيانات فارغة ثم الكتابة فوق القديمة."""


async def ping_db() -> bool:
    """فحص اتصال حقيقي بقاعدة البيانات."""
    global db_ready
    try:
        await mongo_client.admin.command("ping")
        db_ready = True
        return True
    except Exception as e:
        db_ready = False
        print(f"[ERROR] MongoDB ping failed: {e}")
        return False


async def ensure_db_ready(force: bool = False) -> bool:
    """True إذا كانت قاعدة البيانات متاحة. force=True يفحص من جديد حتى لو كانت الحالة سليمة."""
    global db_ready
    if db_ready and not force:
        return True
    return await ping_db()


async def wait_for_database(max_attempts: int = 8, delay: float = 3.0) -> bool:
    """محاولات اتصال متكررة عند الإقلاع — حتى لا يبدأ البوت بذاكرة فارغة."""
    for attempt in range(1, max_attempts + 1):
        if await ping_db():
            print(f"[LOG] MongoDB connection successful (attempt {attempt})")
            return True
        print(f"[WARNING] MongoDB not reachable — attempt {attempt}/{max_attempts}, retrying in {delay:.0f}s…")
        if attempt < max_attempts:
            import asyncio
            await asyncio.sleep(delay)
    print("[ERROR] MongoDB unreachable after retries — سيرفض البوت الكتابة حتى يعود الاتصال لحماية بياناتك.")
    print("[HINT] شغّل /تشخيص في السيرفر لمعرفة السبب والحل بدقة.")
    return False


async def diagnose_db() -> dict:
    """تشخيص مصنّف: يفحص الاتصال ويصنّف الفشل إلى سبب واضح مع الحل المقترح.
    يعيد {ok, latency_ms, category, problem, fix, uri_masked, db_name} —
    category: none / config / dns / auth / timeout / tls / unknown"""
    import time
    from urllib.parse import urlsplit

    result = {
        "ok": False, "latency_ms": None, "category": "unknown",
        "problem": "", "fix": "", "db_name": MONGODB_DB_NAME,
        "uri_masked": "—",
    }
    try:
        parts = urlsplit(MONGODB_URI)
        host = parts.hostname or "—"
        db_part = (parts.path or "/").lstrip("/")
        result["uri_masked"] = f"{parts.scheme}://***:***@{host}" + (f"/{db_part}" if db_part else "")
        if db_part and db_part != MONGODB_DB_NAME:
            result["db_name"] = f"{MONGODB_DB_NAME} (مسار الرابط يقول {db_part})"
    except Exception:
        result["uri_masked"] = "رابط غير قابل للقراءة — تحقق من MONGODB_URI"

    start = time.monotonic()
    try:
        await mongo_client.admin.command("ping")
        result["ok"] = True
        result["latency_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "none"
        return result
    except Exception as e:
        msg = str(e)
        lower = msg.lower()
        ename = type(e).__name__.lower()
        if "invaliduri" in ename or "invalid uri" in lower or "scheme" in lower:
            result["category"] = "config"
            result["problem"] = "صيغة MONGODB_URI نفسها غير صالحة."
            result["fix"] = "يجب أن يبدأ الرابط بـ mongodb+srv:// أو mongodb:// — انسخه من Atlas حرفيًا."
        elif ("getaddrinfo" in lower or "dnstimeout" in lower or "cannot resolve" in lower
              or "name or service not known" in lower):
            result["category"] = "dns"
            result["problem"] = "لا يمكن حل اسم المضيف في الرابط (DNS)."
            result["fix"] = "الرابط فيه خطأ إملائي أو المجموعة محذوفة — انسخ رابط اتصال جديد من Atlas."
        elif "authentication" in lower or "auth failed" in lower or "bad auth" in lower or "-18" in lower:
            result["category"] = "auth"
            result["problem"] = "اسم المستخدم أو كلمة المرور مرفوضة."
            result["fix"] = "في Atlas: Database Access — تأكد من المستخدم وكلمة المرور ورمّز الرموز الخاصة في الرابط."
        elif "ssl" in lower or "tls" in lower or "certificate" in lower:
            result["category"] = "tls"
            result["problem"] = "فشل التحقق الأمني للاتصال (TLS)."
            result["fix"] = "تأكد أن الرابط mongodb+srv:// من Atlas حرفيًا دون تعديل يدوي."
        elif "timed out" in lower or "timeout" in lower or "serverselection" in lower:
            result["category"] = "timeout"
            result["problem"] = "انتهت المهلة دون وصول للسيرفر — الاتصال محجوب أو الرابط لعنوان غير حي."
            result["fix"] = ("الأرجح Network Access في Atlas لا يسمح بعناوين الاستضافة — أضف 0.0.0.0/0.\n"
                             "أو MONGODB_URI لرابط داخلي (مثل Railway الداخلي) لا يعمل خارجيًا — "
                             "استخدم MongoDB Atlas الخارجي mongodb+srv://")
        else:
            result["problem"] = msg[:260]
            result["fix"] = "أعد فحص MONGODB_URI، وإن استمرت شارك هذه الرسالة مع دعم الاستضافة."
        result["latency_ms"] = int((time.monotonic() - start) * 1000)
        return result
