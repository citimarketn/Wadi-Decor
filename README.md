# متجر وادي الديكور والمفروشات

```
wadi-decor/
├─ site/       ← الموقع (index.html + _headers) — يُرفع على Netlify
├─ server/     ← خادم الطلبات Flask (app.py) — يُرفع على Render
├─ firebase/   ← قواعد الحماية (firestore.rules) — تُلصق في Firebase
├─ netlify.toml
└─ .gitignore  ← يمنع رفع ملف المفتاح السري
```

## ترتيب الرفع
1. **GitHub:** مستودع خاص (Private) لكل الفولدر.
   ```
   cd Desktop/wadi-decor
   git init
   git add .
   git commit -m "first version"
   git branch -M main
   git remote add origin https://github.com/USERNAME/wadi-decor.git
   git push -u origin main
   ```
2. **Netlify:** Add new site ← Import from Git ← المستودع. اترك Build command فارغاً (netlify.toml يحدد فولدر site). انسخ رابط الموقع.
3. **Render:** New ← Web Service ← نفس المستودع.
   - Root Directory: `server`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Environment:
     - `FIREBASE_SERVICE_ACCOUNT` = محتوى ملف مفتاح الخادم JSON كاملاً
     - `ALLOWED_ORIGINS` = رابط Netlify (مثل https://wadi-decor.netlify.app) بدون / في النهاية
4. ضع رابط Render في `site/index.html` مكان `api:null` (بين علامتي تنصيص) ثم: `git add . && git commit -m "api url" && git push` وسيُحدَّث الموقع تلقائياً.
5. **Firebase ← Authentication ← Settings ← Authorized domains:** أضف نطاق Netlify.
6. **حسابات الإدارة:** سجّل حساباً على الموقع، انسخ الـ UID من Authentication ← Users، ثم في Firestore أنشئ مجموعة `admins` ومستنداً معرّفه = الـ UID وبداخله حقل `role` = `owner`. كرّر لكل مسؤول.
7. ادخل بحساب المسؤول ← القائمة ← لوحة التحكم ← "تحميل المنتجات والأقسام الافتراضية".
8. جرّب طلباً كاملاً.

## أسرار لا تُرفع أبداً
ملف مفتاح الخادم (JSON). يُلصق محتواه فقط في إعدادات Render.
