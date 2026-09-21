"""
خادم الطلبات لمتجر وادي الديكور والمفروشات.

المبدأ: العميل يرسل فقط (معرّف المنتج + الكمية) وبيانات التوصيل.
الأسعار والإجمالي والشحن يقرؤها الخادم من Firestore ولا يثق بأي رقم قادم من المتصفح.
"""
import os, re, json, time, secrets, threading
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore, auth

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024  # 32KB كحد أقصى للطلب

_raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
firebase_admin.initialize_app(
    credentials.Certificate(json.loads(_raw)) if _raw else credentials.ApplicationDefault()
)
db = firestore.client()

ALLOWED = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
PHONE = re.compile(r"^01[0125]\d{8}$")
MAX_LINES, MAX_QTY = 50, 20


class Bad(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.msg, self.code = msg, code


def clean(v, mx):
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()[:mx]


# ---------- تحديد المعدل (لكل مستخدم، داخل العملية) ----------
_hits, _lock = {}, threading.Lock()


def limited(uid, limit=5, window=600):
    now = time.time()
    with _lock:
        q = [t for t in _hits.get(uid, []) if now - t < window]
        if len(q) >= limit:
            _hits[uid] = q
            return True
        q.append(now)
        _hits[uid] = q
        return False


# ---------- بناء الطلب (دالة نقية قابلة للاختبار) ----------
def parse_items(raw):
    if not isinstance(raw, list) or not raw:
        raise Bad("السلة فارغة.")
    merged = {}
    for it in raw:
        if not isinstance(it, dict):
            raise Bad("بيانات السلة غير صحيحة.")
        pid, q = it.get("id"), it.get("q")
        if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", pid):
            raise Bad("منتج غير صحيح في السلة.")
        if isinstance(q, bool) or not isinstance(q, int) or not (1 <= q <= MAX_QTY):
            raise Bad("الكمية غير صحيحة.")
        merged[pid] = merged.get(pid, 0) + q
        if merged[pid] > MAX_QTY:
            raise Bad("الحد الأقصى للكمية %d لكل منتج." % MAX_QTY)
    if len(merged) > MAX_LINES:
        raise Bad("عدد المنتجات في الطلب كبير.")
    return merged


def build_order(uid, data, products, shipping):
    """products: {id: dict} من قاعدة البيانات فقط."""
    if not isinstance(data, dict):
        raise Bad("طلب غير صحيح.")
    name, city = clean(data.get("name"), 80), clean(data.get("city"), 60)
    address, notes = clean(data.get("address"), 200), clean(data.get("notes"), 400)
    phone = re.sub(r"\D", "", str(data.get("phone") or ""))
    pay = "cod" if data.get("pay") == "cod" else "vodafone"
    if len(name) < 3:
        raise Bad("أدخل اسمك بالكامل.")
    if not PHONE.match(phone):
        raise Bad("أدخل رقم موبايل مصري صحيحًا.")
    if len(city) < 2 or len(address) < 5:
        raise Bad("أدخل المدينة والعنوان بالتفصيل.")

    merged = parse_items(data.get("items"))
    lines, total = [], 0
    for pid, q in merged.items():
        p = products.get(pid)
        if not p:
            raise Bad("أحد المنتجات لم يعد متاحًا، حدّث السلة.")
        price = p.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
            raise Bad("تعذر تسعير أحد المنتجات، تواصل مع المتجر.", 409)
        stock = p.get("stock")
        if isinstance(stock, (int, float)) and not isinstance(stock, bool) and stock < q:
            raise Bad("المتاح من «%s» %d فقط." % (p.get("name", ""), max(0, int(stock))))
        lines.append({"id": pid, "name": clean(p.get("name"), 120), "price": price, "q": q})
        total += price * q

    ship = shipping if isinstance(shipping, (int, float)) and shipping > 0 else 0
    now = time.gmtime()
    oid = "WD-%02d%02d%02d-%s" % (now.tm_year % 100, now.tm_mon, now.tm_mday, "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4)))
    return {
        "id": oid, "uid": uid, "name": name, "phone": phone, "city": city, "address": address,
        "notes": notes, "pay": pay, "items": lines, "shipping": ship,
        "total": total + ship, "status": "new", "ts": int(time.time() * 1000),
    }


# ---------- المسارات ----------
@app.after_request
def headers(resp):
    origin = request.headers.get("Origin", "").rstrip("/")
    if origin and origin in ALLOWED:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Max-Age"] = "600"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/health")
def health():
    return jsonify(ok=True)


@app.route("/api/orders", methods=["POST", "OPTIONS"])
def create_order():
    if request.method == "OPTIONS":
        return "", 204
    try:
        h = request.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            raise Bad("سجّل الدخول أولًا.", 401)
        try:
            uid = auth.verify_id_token(h[7:])["uid"]
        except Exception:
            raise Bad("انتهت الجلسة، سجّل الدخول من جديد.", 401)
        if limited(uid):
            raise Bad("محاولات كثيرة، انتظر بضع دقائق ثم أعد المحاولة.", 429)

        data = request.get_json(silent=True)
        merged = parse_items((data or {}).get("items") if isinstance(data, dict) else None)
        snaps = db.get_all([db.collection("products").document(i) for i in merged])
        products = {s.id: s.to_dict() for s in snaps if s.exists}
        st = db.document("settings/store").get()
        shipping = (st.to_dict() or {}).get("shipping", 0) if st.exists else 0

        order = build_order(uid, data, products, shipping)
        db.collection("orders").document(order["id"]).create(order)
        return jsonify(order=order), 201
    except Bad as e:
        return jsonify(error=e.msg), e.code
    except Exception:
        app.logger.exception("order failed")
        return jsonify(error="حدث خطأ في الخادم، حاول مرة أخرى."), 500


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5000)))
