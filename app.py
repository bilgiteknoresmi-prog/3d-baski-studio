from flask import Flask, request, redirect, url_for, session, render_template_string, g
from datetime import datetime
import os
import urllib.parse

import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "degistir-bunu-123")

ADMIN_USER = "admin"

def get_admin_pass() -> str:
    return os.environ.get("ADMIN_PASS", "")

def get_whatsapp_number() -> str:
    return os.environ.get("WHATSAPP_NUMBER", "")

def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", "")

# --- küçük yardımcılar ---
def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def safe_int(value, default=0, minv=None, maxv=None):
    try:
        v = int(str(value).strip())
    except Exception:
        v = default
    if minv is not None:
        v = max(minv, v)
    if maxv is not None:
        v = min(maxv, v)
    return v

# --- PostgreSQL ---
def get_db():
    if "db" not in g:
        dsn = get_database_url()
        if not dsn:
            raise RuntimeError("DATABASE_URL environment variable is not set.")
        # Render/PG genelde SSL ister; URL içinde sslmode yoksa ekleyelim
        if "sslmode=" not in dsn:
            joiner = "&" if "?" in dsn else "?"
            dsn = dsn + f"{joiner}sslmode=require"
        g.db = psycopg2.connect(dsn)
    return g.db

@app.teardown_appcontext
def close_db(_err):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                material TEXT NOT NULL,
                price INTEGER NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                lead_time_days INTEGER NOT NULL DEFAULT 1,
                photo_url TEXT,
                stl_url TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
    db.commit()

def seed_products_if_empty():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM products;")
        n = cur.fetchone()[0]
        if n == 0:
            cur.execute("""
                INSERT INTO products(name, category, material, price, stock, lead_time_days, photo_url, stl_url)
                VALUES
                  (%s,%s,%s,%s,%s,%s,%s,%s),
                  (%s,%s,%s,%s,%s,%s,%s,%s),
                  (%s,%s,%s,%s,%s,%s,%s,%s);
            """, (
                "PS5 DualSense Stand (Ters Slotlu)", "Aksesuar", "PLA", 249, 15, 2, "", "",
                "Kablo Düzenleyici Klips Seti (10'lu)", "Organizasyon", "PETG", 129, 40, 1, "", "",
                "Masa Üstü Telefon Standı (Ayarlı)", "Stand", "PLA", 159, 25, 1, "", "",
            ))
    db.commit()

def fetch_products(q="", cat="", mat=""):
    q = (q or "").strip().lower()
    cat = (cat or "").strip()
    mat = (mat or "").strip()

    sql = "SELECT * FROM products WHERE 1=1"
    args = []

    if q:
        sql += " AND LOWER(name) LIKE %s"
        args.append(f"%{q}%")
    if cat:
        sql += " AND category = %s"
        args.append(cat)
    if mat:
        sql += " AND material = %s"
        args.append(mat)

    sql += " ORDER BY id DESC"

    db = get_db()
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, args)
        return cur.fetchall()

def fetch_product(pid: int):
    db = get_db()
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
        return cur.fetchone()

def distinct_values(col: str):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {col} FROM products ORDER BY {col};")
        vals = [r[0] for r in cur.fetchall()]
        return [v for v in vals if (v or "").strip()]

def fetch_messages():
    db = get_db()
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM messages ORDER BY id DESC;")
        return cur.fetchall()

def count_unread_messages():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM messages WHERE is_read = FALSE;")
        return cur.fetchone()[0]

def require_admin():
    if not session.get("is_admin"):
        return redirect(url_for("login"))
    return None

# İlk istek gelince DB hazırla (her worker için güvenli; seed count-check yapıyor)
@app.before_request
def _ensure_db_once():
    if not getattr(app, "_db_ready", False):
        init_db()
        seed_products_if_empty()
        app._db_ready = True

# --- WhatsApp satın al ---
def whatsapp_buy_link(p):
    num = get_whatsapp_number().strip()
    if not num:
        return ""
    text = (
        "Merhaba, sipariş vermek istiyorum.\n\n"
        f"Ürün: {p['name']}\n"
        f"Kategori: {p['category']}\n"
        f"Malzeme: {p['material']}\n"
        f"Fiyat: {p['price']} TL\n"
        f"Stok: {p['stock']}\n"
        f"Üretim süresi: {p['lead_time_days']} gün\n"
        f"Ürün ID: #{p['id']}\n\n"
        "Adet: 1\n"
        "Renk/Not: "
    )
    return f"https://wa.me/{num}?text={urllib.parse.quote(text)}"

# --- UI ---
BASE_HTML = """
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{{ title }}</title>
  <style>
    :root { --bg:#0b0f1a; --card:#11182a; --text:#eaf0ff; --muted:#a8b3cf; --accent:#4da3ff; --line:#1f2a44; }
    body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; background:linear-gradient(180deg,#070a12, #0b0f1a); color:var(--text); }
    .wrap { max-width: 980px; margin: 0 auto; padding: 18px; }
    .nav { display:flex; gap:10px; align-items:center; justify-content:space-between; position: sticky; top:0;
      background:rgba(11,15,26,.85); backdrop-filter: blur(8px); border-bottom: 1px solid var(--line);
      padding: 12px 18px; z-index: 10; }
    .brand { display:flex; flex-direction:column; line-height:1.1; }
    .brand b { font-size: 16px; letter-spacing:.2px; }
    .brand small { color:var(--muted); }
    .links { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    a.btn, button.btn { display:inline-flex; align-items:center; justify-content:center; gap:8px; padding: 8px 12px;
      border-radius: 10px; border: 1px solid var(--line); color:var(--text); text-decoration:none;
      background: rgba(255,255,255,0.03); cursor: pointer; white-space: nowrap; }
    a.btn:hover, button.btn:hover { border-color: rgba(77,163,255,.6); }
    .btn.primary { background: rgba(77,163,255,.15); border-color: rgba(77,163,255,.6); }
    .btn.danger { border-color: rgba(255,80,80,.6); background: rgba(255,80,80,.08); }
    .btn.ok { border-color: rgba(120,255,160,.45); background: rgba(120,255,160,.08); }
    .grid { display:grid; grid-template-columns: 1.2fr .8fr; gap:14px; }
    @media (max-width: 900px){ .grid{ grid-template-columns: 1fr; } }
    .card { background: rgba(17,24,42,.85); border:1px solid var(--line); border-radius: 18px; padding: 16px; }
    h1 { margin: 0 0 10px; font-size: 28px; }
    h2 { margin: 0 0 10px; font-size: 18px; }
    p { margin: 8px 0; color:var(--muted); }
    .list { display:flex; flex-direction:column; gap:10px; margin-top:10px; }
    .item { display:flex; justify-content:space-between; gap:12px; padding: 12px; border-radius: 14px; border:1px solid var(--line); background: rgba(255,255,255,0.02); }
    .left { display:flex; gap:12px; align-items:flex-start; }
    .thumb { width:78px; height:78px; border-radius:14px; border:1px solid var(--line); background: rgba(0,0,0,.25);
             overflow:hidden; display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:12px; }
    .thumb img { width:100%; height:100%; object-fit:cover; display:block; }
    .meta { display:flex; flex-direction:column; gap:4px; }
    .meta b { font-size: 15px; }
    .sub { color:var(--muted); font-size:13px; line-height:1.25; }
    .pills { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
    .pill { font-size:12px; padding:4px 8px; border-radius:999px; border:1px solid var(--line); color:var(--muted); }
    input, textarea, select { width:100%; box-sizing:border-box; padding: 10px 12px; border-radius: 12px;
      border: 1px solid var(--line); background: rgba(0,0,0,.25); color: var(--text); outline:none; }
    input:focus, textarea:focus, select:focus { border-color: rgba(77,163,255,.7); }
    .row { display:flex; gap:10px; }
    .row > * { flex:1; }
    .actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .kpi { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
    .footer { padding: 22px 0; color: var(--muted); font-size: 13px; }
    .hr { height:1px; background: var(--line); margin: 12px 0; }
    .msg { border:1px solid rgba(255,80,80,.55); background: rgba(255,80,80,.08); padding:10px 12px; border-radius:14px; margin-bottom:12px; }
  </style>
</head>
<body>
  <div class="nav">
    <div class="brand">
      <b>3D Baskı Atölyesi</b>
      <small>Özel tasarım • Hızlı üretim</small>
    </div>
    <div class="links">
      <a class="btn" href="{{ url_for('home') }}">Ana Sayfa</a>
      <a class="btn" href="{{ url_for('products') }}">Ürünler</a>
      <a class="btn" href="{{ url_for('vision') }}">Vizyon & Misyon</a>
      <a class="btn" href="{{ url_for('contact') }}">İletişim</a>
      {% if session.get("is_admin") %}
        <a class="btn primary" href="{{ url_for('admin') }}">Panel</a>
        <a class="btn" href="{{ url_for('logout') }}">Çıkış</a>
      {% else %}
        <a class="btn primary" href="{{ url_for('login') }}">Yönetim</a>
      {% endif %}
    </div>
  </div>
  <div class="wrap">
    {{ body|safe }}
    <div class="footer">© {{ year }} • {{ now }}</div>
  </div>
</body>
</html>
"""

def page(title: str, body_html: str):
    return render_template_string(
        BASE_HTML,
        title=title,
        body=body_html,
        year=datetime.now().year,
        now=datetime.now().strftime("%d.%m.%Y %H:%M"),
        session=session
    )

# --- Routes ---
@app.get("/")
def home():
    total = len(fetch_products())
    categories = distinct_values("category")
    materials = distinct_values("material")
    unread = count_unread_messages() if session.get("is_admin") else None

    right_extra = ""
    if session.get("is_admin"):
        right_extra = f"""
        <div class="hr"></div>
        <p class="sub">Yönetim</p>
        <div class="actions" style="justify-content:flex-start">
          <a class="btn primary" href="/admin">Panele gir</a>
          <a class="btn" href="/admin/messages">Mesajlar ({unread})</a>
        </div>
        """

    body = f"""
    <div class="grid">
      <div class="card">
        <h1>Özel 3D Baskı Ürünler</h1>
        <p>Ürünlere bakabilir veya “Satın Al” ile WhatsApp’tan sipariş verebilirsin.</p>
        <div class="list" style="margin-top:14px">
          <div class="item">
            <div class="meta"><b>Ürün kataloğu</b><div class="sub">Mevcut ürünleri görüntüle</div></div>
            <a class="btn primary" href="/products">Ürünlere git</a>
          </div>
          <div class="item">
            <div class="meta"><b>Tasarım & Üretim</b><div class="sub">Vizyon ve misyon sayfasında detaylar</div></div>
            <a class="btn" href="/vision">Göz at</a>
          </div>
        </div>
      </div>
      <div class="card">
        <h2>Atölye Özeti</h2>
        <div class="kpi">
          <span class="pill">Toplam ürün: {total}</span>
          <span class="pill">Kategori: {len(categories)}</span>
          <span class="pill">Malzeme: {len(materials)}</span>
        </div>
        {right_extra}
      </div>
    </div>
    """
    return page("Ana Sayfa", body)

@app.get("/products")
def products():
    q = request.args.get("q", "")
    cat = request.args.get("cat", "")
    mat = request.args.get("mat", "")

    rows = fetch_products(q=q, cat=cat, mat=mat)
    categories = distinct_values("category")
    materials = distinct_values("material")

    options_cat = '<option value="">Tüm kategoriler</option>' + "".join(
        [f'<option value="{esc(c)}" {"selected" if c==cat else ""}>{esc(c)}</option>' for c in categories]
    )
    options_mat = '<option value="">Tüm malzemeler</option>' + "".join(
        [f'<option value="{esc(m)}" {"selected" if m==mat else ""}>{esc(m)}</option>' for m in materials]
    )

    items = ""
    for p in rows:
        photo = (p["photo_url"] or "").strip()
        photo_html = f'<img src="{esc(photo)}" alt="Ürün">' if photo else "Görsel"
        stl = (p["stl_url"] or "").strip()
        stl_btn = f'<a class="btn" href="{esc(stl)}" target="_blank" rel="noopener">STL</a>' if stl else ""
        buy_link = whatsapp_buy_link(p)
        buy_btn = f'<a class="btn primary" href="{buy_link}" target="_blank" rel="noopener">Satın Al</a>' if buy_link else ""
        admin_edit = f'<a class="btn" href="/admin/edit/{p["id"]}">Düzenle</a>' if session.get("is_admin") else ""

        items += f"""
        <div class="item">
          <div class="left">
            <div class="thumb">{photo_html}</div>
            <div class="meta">
              <b>{esc(p["name"])}</b>
              <div class="sub">{esc(p["category"])} • {esc(p["material"])} • {p["price"]} TL</div>
              <div class="pills">
                <span class="pill">Stok: {p["stock"]}</span>
                <span class="pill">Üretim: {p["lead_time_days"]} gün</span>
                <span class="pill">#{p["id"]}</span>
              </div>
            </div>
          </div>
          <div class="actions">{stl_btn}{buy_btn}{admin_edit}</div>
        </div>
        """

    body = f"""
    <div class="card">
      <h1>Ürünler</h1>
      <form method="get" action="/products" class="list" style="margin-top:12px">
        <div class="row">
          <input name="q" value="{esc(q)}" placeholder="Ara: örn. stand, kablo, ps5..." />
          <select name="cat">{options_cat}</select>
          <select name="mat">{options_mat}</select>
        </div>
        <div class="row">
          <button class="btn primary" type="submit">Filtrele</button>
          <a class="btn" href="/products">Sıfırla</a>
          {"<a class='btn' href='/admin'>Panel</a>" if session.get("is_admin") else ""}
        </div>
      </form>
      <div class="list" style="margin-top:14px">
        {items if items else "<p class='sub'>Ürün bulunamadı.</p>"}
      </div>
    </div>
    """
    return page("Ürünler", body)

@app.get("/vision")
def vision():
    body = """
    <div class="card">
      <h1>Vizyon & Misyon</h1>
      <div class="grid" style="margin-top:10px">
        <div class="card">
          <h2>Vizyon</h2>
          <p>Kullanışlı, estetik ve dayanıklı 3D baskı ürünleriyle çözüm sunmak.</p>
        </div>
        <div class="card">
          <h2>Misyon</h2>
          <p>Hızlı prototipleme ve üretim ile standlar, düzenleyiciler, aksesuarlar üretmek.</p>
          <p class="sub">PLA / PETG / TPU gibi malzemelerle ihtiyaca göre üretim.</p>
        </div>
      </div>
    </div>
    """
    return page("Vizyon & Misyon", body)

@app.get("/contact")
def contact():
    body = """
    <div class="grid">
      <div class="card">
        <h1>İletişim</h1>
        <p>Özel tasarım veya sipariş için mesaj bırak.</p>
        <form method="post" action="/contact/send" class="list" style="margin-top:12px">
          <div class="row">
            <input name="name" placeholder="Ad Soyad" required />
            <input name="email" placeholder="E-posta" required />
          </div>
          <textarea name="msg" rows="5" placeholder="İstediğin ürün / ölçü / renk / adet..." required></textarea>
          <button class="btn primary" type="submit">Gönder</button>
        </form>
      </div>
      <div class="card">
        <h2>Bilgi</h2>
        <p class="sub">Mesajlar yönetim panelinde listelenir.</p>
      </div>
    </div>
    """
    return page("İletişim", body)

@app.post("/contact/send")
def contact_send():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    msg = (request.form.get("msg") or "").strip()

    if not (name and email and msg):
        return page("Hata", '<div class="card"><div class="msg">Lütfen tüm alanları doldur.</div><a class="btn primary" href="/contact">Geri dön</a></div>')

    db = get_db()
    with db.cursor() as cur:
        cur.execute("INSERT INTO messages(name, email, message) VALUES(%s,%s,%s)", (name, email, msg))
    db.commit()

    return page("Gönderildi", '<div class="card"><h1>Mesaj alındı</h1><p class="sub">En kısa sürede dönüş yapılacak.</p><a class="btn primary" href="/">Ana sayfaya dön</a></div>')

@app.get("/login")
def login():
    body = """
    <div class="card" style="max-width:520px">
      <h1>Yönetim Giriş</h1>
      <form method="post" action="/login" class="list" style="margin-top:12px">
        <input name="username" placeholder="Kullanıcı adı" required />
        <input name="password" type="password" placeholder="Şifre" required />
        <button class="btn primary" type="submit">Giriş</button>
      </form>
    </div>
    """
    return page("Giriş", body)

@app.post("/login")
def login_post():
    u = (request.form.get("username") or "").strip()
    p = (request.form.get("password") or "")
    if u == ADMIN_USER and p == get_admin_pass():
        session["is_admin"] = True
        return redirect(url_for("admin"))
    return page("Hata", '<div class="card" style="max-width:520px"><div class="msg">Kullanıcı adı veya şifre yanlış.</div><a class="btn primary" href="/login">Tekrar dene</a></div>')

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.get("/admin")
def admin():
    r = require_admin()
    if r: return r
    unread = count_unread_messages()
    body = f"""
    <div class="grid">
      <div class="card">
        <h1>Panel</h1>
        <div class="list" style="margin-top:12px">
          <div class="item">
            <div class="meta"><b>Ürün yönetimi</b><div class="sub">Ürün ekle / düzenle</div></div>
            <a class="btn primary" href="/admin/products">Ürünler</a>
          </div>
          <div class="item">
            <div class="meta"><b>Mesajlar</b><div class="sub">{unread} okunmamış mesaj</div></div>
            <a class="btn primary" href="/admin/messages">Mesajlar</a>
          </div>
        </div>
      </div>
      <div class="card">
        <h2>Durum</h2>
        <div class="kpi">
          <span class="pill">Okunmamış: {unread}</span>
          <span class="pill">WhatsApp: {"Ayarlı" if get_whatsapp_number().strip() else "Kapalı"}</span>
          <span class="pill">DB: PostgreSQL</span>
        </div>
      </div>
    </div>
    """
    return page("Panel", body)

@app.get("/admin/products")
def admin_products():
    r = require_admin()
    if r: return r

    rows = fetch_products()
    items = ""
    for p in rows:
        items += f"""
        <div class="item">
          <div class="meta">
            <b>{esc(p["name"])}</b>
            <div class="sub">{esc(p["category"])} • {esc(p["material"])} • {p["price"]} TL</div>
            <div class="pills">
              <span class="pill">Stok: {p["stock"]}</span>
              <span class="pill">Üretim: {p["lead_time_days"]} gün</span>
              <span class="pill">#{p["id"]}</span>
            </div>
          </div>
          <div class="actions">
            <a class="btn primary" href="/admin/edit/{p["id"]}">Düzenle</a>
            <form method="post" action="/admin/delete" style="margin:0">
              <input type="hidden" name="id" value="{p["id"]}" />
              <button class="btn danger" type="submit">Sil</button>
            </form>
          </div>
        </div>
        """

    body = f"""
    <div class="grid">
      <div class="card">
        <h1>Ürün Yönetimi</h1>
        <form method="post" action="/admin/add" class="list" style="margin-top:12px">
          <input name="name" placeholder="Ürün adı" required />
          <div class="row">
            <input name="category" placeholder="Kategori" required />
            <select name="material" required>
              <option value="PLA">PLA</option><option value="PETG">PETG</option><option value="TPU">TPU</option>
              <option value="ABS">ABS</option><option value="Diğer">Diğer</option>
            </select>
          </div>
          <div class="row">
            <input name="price" type="number" min="0" step="1" placeholder="Fiyat (TL)" required />
            <input name="stock" type="number" min="0" step="1" placeholder="Stok" required />
          </div>
          <div class="row">
            <input name="lead_time_days" type="number" min="0" step="1" placeholder="Üretim süresi (gün)" required />
            <input name="photo_url" placeholder="Foto linki (opsiyonel)" />
          </div>
          <input name="stl_url" placeholder="STL linki (opsiyonel)" />
          <button class="btn primary" type="submit">Ekle</button>
        </form>
        <div class="hr"></div>
        <div class="actions" style="justify-content:flex-start">
          <a class="btn" href="/products">Kataloğu aç</a>
          <a class="btn" href="/admin">Panele dön</a>
        </div>
      </div>
      <div class="card">
        <h2>Mevcut Ürünler</h2>
        <div class="list" style="margin-top:10px">
          {items if items else "<p class='sub'>Ürün yok.</p>"}
        </div>
      </div>
    </div>
    """
    return page("Ürün Yönetimi", body)

@app.post("/admin/add")
def admin_add():
    r = require_admin()
    if r: return r

    name = (request.form.get("name") or "").strip()
    category = (request.form.get("category") or "").strip()
    material = (request.form.get("material") or "").strip()
    price = safe_int(request.form.get("price"), 0, 0)
    stock = safe_int(request.form.get("stock"), 0, 0)
    lead = safe_int(request.form.get("lead_time_days"), 1, 0)
    photo_url = (request.form.get("photo_url") or "").strip()
    stl_url = (request.form.get("stl_url") or "").strip()

    if not (name and category and material):
        return redirect(url_for("admin_products"))

    db = get_db()
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO products(name, category, material, price, stock, lead_time_days, photo_url, stl_url)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
        """, (name, category, material, price, stock, lead, photo_url, stl_url))
    db.commit()
    return redirect(url_for("admin_products"))

@app.post("/admin/delete")
def admin_delete():
    r = require_admin()
    if r: return r

    pid = safe_int(request.form.get("id"), 0, 0)
    db = get_db()
    with db.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id=%s", (pid,))
    db.commit()
    return redirect(url_for("admin_products"))

@app.get("/admin/edit/<int:pid>")
def admin_edit(pid: int):
    r = require_admin()
    if r: return r
    p = fetch_product(pid)
    if not p:
        return page("Düzenle", '<div class="card"><div class="msg">Ürün bulunamadı.</div><a class="btn primary" href="/admin/products">Geri dön</a></div>')

    def mat_opts(sel):
        opts = ["PLA","PETG","TPU","ABS","Diğer"]
        return "".join([f'<option value="{esc(o)}" {"selected" if o==sel else ""}>{esc(o)}</option>' for o in opts])

    body = f"""
    <div class="card" style="max-width: 760px">
      <h1>Ürün Düzenle</h1>
      <p class="sub">#{p["id"]}</p>
      <form method="post" action="/admin/edit/{p["id"]}" class="list" style="margin-top:12px">
        <input name="name" value="{esc(p["name"])}" required />
        <div class="row">
          <input name="category" value="{esc(p["category"])}" required />
          <select name="material" required>{mat_opts(p["material"] or "")}</select>
        </div>
        <div class="row">
          <input name="price" type="number" min="0" step="1" value="{p["price"]}" required />
          <input name="stock" type="number" min="0" step="1" value="{p["stock"]}" required />
        </div>
        <div class="row">
          <input name="lead_time_days" type="number" min="0" step="1" value="{p["lead_time_days"]}" required />
          <input name="photo_url" value="{esc(p["photo_url"] or "")}" />
        </div>
        <input name="stl_url" value="{esc(p["stl_url"] or "")}" />
        <div class="row">
          <button class="btn primary" type="submit">Kaydet</button>
          <a class="btn" href="/admin/products">İptal</a>
        </div>
      </form>
    </div>
    """
    return page("Düzenle", body)

@app.post("/admin/edit/<int:pid>")
def admin_edit_post(pid: int):
    r = require_admin()
    if r: return r

    if not fetch_product(pid):
        return redirect(url_for("admin_products"))

    name = (request.form.get("name") or "").strip()
    category = (request.form.get("category") or "").strip()
    material = (request.form.get("material") or "").strip()
    price = safe_int(request.form.get("price"), 0, 0)
    stock = safe_int(request.form.get("stock"), 0, 0)
    lead = safe_int(request.form.get("lead_time_days"), 1, 0)
    photo_url = (request.form.get("photo_url") or "").strip()
    stl_url = (request.form.get("stl_url") or "").strip()

    if not (name and category and material):
        return redirect(url_for("admin_edit", pid=pid))

    db = get_db()
    with db.cursor() as cur:
        cur.execute("""
            UPDATE products
            SET name=%s, category=%s, material=%s, price=%s, stock=%s, lead_time_days=%s, photo_url=%s, stl_url=%s
            WHERE id=%s
        """, (name, category, material, price, stock, lead, photo_url, stl_url, pid))
    db.commit()
    return redirect(url_for("admin_products"))

@app.get("/admin/messages")
def admin_messages():
    r = require_admin()
    if r: return r

    rows = fetch_messages()
    unread = count_unread_messages()

    items = ""
    for m in rows:
        status = "Okundu" if m["is_read"] else "Yeni"
        items += f"""
        <div class="item">
          <div class="meta">
            <b>{esc(m["name"])}</b> <span class="pill">{status}</span>
            <div class="sub">{esc(m["email"])} • {m["created_at"]}</div>
            <div class="sub" style="margin-top:6px; white-space:pre-wrap">{esc(m["message"])}</div>
          </div>
          <div class="actions">
            <form method="post" action="/admin/messages/read" style="margin:0">
              <input type="hidden" name="id" value="{m["id"]}">
              <button class="btn ok" type="submit">Okundu</button>
            </form>
            <form method="post" action="/admin/messages/delete" style="margin:0">
              <input type="hidden" name="id" value="{m["id"]}">
              <button class="btn danger" type="submit">Sil</button>
            </form>
          </div>
        </div>
        """

    body = f"""
    <div class="card">
      <h1>Mesajlar</h1>
      <p class="sub">{unread} okunmamış mesaj</p>
      <div class="actions" style="justify-content:flex-start; margin-top:10px">
        <a class="btn" href="/admin">Panele dön</a>
        <a class="btn" href="/admin/products">Ürünler</a>
      </div>
      <div class="list" style="margin-top:14px">
        {items if items else "<p class='sub'>Mesaj yok.</p>"}
      </div>
    </div>
    """
    return page("Mesajlar", body)

@app.post("/admin/messages/read")
def admin_message_read():
    r = require_admin()
    if r: return r
    mid = safe_int(request.form.get("id"), 0, 0)
    db = get_db()
    with db.cursor() as cur:
        cur.execute("UPDATE messages SET is_read=TRUE WHERE id=%s", (mid,))
    db.commit()
    return redirect(url_for("admin_messages"))

@app.post("/admin/messages/delete")
def admin_message_delete():
    r = require_admin()
    if r: return r
    mid = safe_int(request.form.get("id"), 0, 0)
    db = get_db()
    with db.cursor() as cur:
        cur.execute("DELETE FROM messages WHERE id=%s", (mid,))
    db.commit()
    return redirect(url_for("admin_messages"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
