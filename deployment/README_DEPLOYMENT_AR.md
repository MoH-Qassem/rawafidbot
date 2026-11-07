# نشر RAWAFED BOT على FadeHost (رفع ملفات — بدون GitHub)

هذه الحزمة تشغّل **البوت المالي الحقيقي** عبر `python main.py`، وليست قالب Echo.

## قبل الرفع

1. أوقف أي تشغيل محلي لنفس `BOT_TOKEN` (لا تشغّل نسختين معاً).
2. جهّز قيم البيئة من لوحة FadeHost (لا تضعها داخل الملفات المرفوعة).
3. إن كانت لديك قاعدة بيانات حالية: ارفعها يدوياً إلى المسار الدائم `/data/rawafed.db` **قبل** أو مع أول تشغيل. البوت **لا يحذف** قاعدة موجودة؛ يطبّق ترقيعات إضافية فقط.

## متغيرات البيئة المطلوبة

| المتغير | مثال | ملاحظات |
|---------|--------|---------|
| `BOT_TOKEN` | *(من BotFather)* | مطلوب — لا يُرفع في الملفات |
| `CEO_TELEGRAM_ID` | معرف رقمي | مطلوب |
| `DB_PATH` | `/data/rawafed.db` | مسار دائم على FadeHost |
| `TIMEZONE` | `Asia/Damascus` | للجدولة |
| `BUILD_ID` | `2.1.0+fadehost` | يظهر في السجلات |
| `LOG_LEVEL` | `INFO` | أو `DEBUG` مؤقتاً |

**لا تضبط على الإنتاج:**

- `ALLOW_ENV_MEMBER_BOOTSTRAP`
- `MEMBER_TELEGRAM_IDS` (التسجيل عبر المجموعة)

اختياري قديم: `DATABASE_URL` — يُتجاهل إذا وُجد `DB_PATH`.

## أوامر البناء والتشغيل في FadeHost

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python main.py`
- **Python:** 3.11 أو أحدث

## خطوات الرفع (واضحة)

1. من جهازك استخدم الملف: `deployment/rawafed-bot-fadehost.zip`
2. في لوحة FadeHost اختر المشروع / التطبيق الخاص بالبوت.
3. ارفع الـ ZIP أو فكّه بحيث يكون **`main.py` في جذر التطبيق** (وليس داخل مجلد إضافي).
4. املأ Environment Variables بالقائمة أعلاه.
5. تأكد أن المجلد `/data` متاح ودائم، وأن `DB_PATH=/data/rawafed.db`.
6. إن كنت تنقل قاعدة قديمة: انسخ `rawafed.db` إلى `/data/rawafed.db` عبر مدير الملفات أو SSH قبل البدء.
7. اضبط Start Command على `python main.py` ثم Start/Redeploy.
8. راقب Logs. يجب أن ترى تقريباً:

```text
BUILD_ID=...
MENU_VERSION=menu-v3-group-first-20261107
START_HANDLER=rawafed_bot.bot.handlers.start.cmd_start
db_path=/data/rawafed.db
telegram_bot_id=... username=@...
Bot polling started ...
```

9. في مجموعة الشركة أرسل `/start` لتحديث لوحة الأزرار إلى **menu-v3**.
10. تأكد أن الرسالة ترحّب بـ «محاسب روافد الذكي» وليس أي نص Echo/Hi alive.

## نقل قاعدة محلية إلى FadeHost

```text
محلياً:  data/rawafed.db
على السيرفر: /data/rawafed.db
```

1. أوقف البوت.
2. ارفع الملف إلى `/data/rawafed.db` (لا تستبدله بملف فارغ بالخطأ).
3. شغّل البوت — سيظهر في السجل: `Existing database detected … additive … only`.

النسخ الاحتياطي على الاستضافة يُحفظ تحت: `/data/backups/`.

## فشل شائع

| العرض | السبب | الحل |
|--------|--------|------|
| رسائل Echo / Hi alive | قالب FadeHost أو ملفات خاطئة | تأكد أن `main.py` هو ملف روافد وفي الجذر |
| `Polling already running` | نسخة أخرى لنفس التوكن | أوقف العملية الأخرى يدوياً |
| قائمة أزرار قديمة | كاش تيليجرام | أرسل `/start` |
| قاعدة فارغة بعد النشر | رفع بدون نسخ `/data` | استعد النسخة من نسخة احتياطية |

## ما لا تفعله

- لا ترفع `venv` أو `.env` أو قواعد `*.db` داخل حزمة الكود.
- لا تشغّل Polling محلياً مع الاستضافة لنفس التوكن.
- لا تفعّل `ALLOW_ENV_MEMBER_BOOTSTRAP` على الإنتاج.
