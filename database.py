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

MONGODB_DB_NAME = "work_bot"

mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGODB_URI,
    serverSelectionTimeoutMS=8000,
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
    return False
