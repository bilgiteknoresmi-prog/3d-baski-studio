from flask import Flask, request, redirect, url_for, session, render_template_string, g
from datetime import datetime
import sqlite3
import os
import urllib.parse

app = Flask(__name__)
app.secret_key = "degistir-bunu-123"

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "site.db")
ENV_PATH = os.path.join(BASE_DIR, ".env")

ADMIN_USER = "admin"

# --- mini .env loader (ek paket yok) ---
def load_env_file(path: str):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

load_env_file(ENV_PATH)

def get_admin_pass() -> str:
    return os.environ.get("ADMIN_PASS", "")

def get_whatsapp_number() -> str:
    return os.environ.get("WHATSAPP_NUMBER", "")

# --- HTML yardımcıları ---
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

# --- DB ---
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_err):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            material TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            lead_time_days INTEGER NOT NULL DEFAULT 1,
            photo_url TEXT,
            stl_url TEXT,
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    db.commit()

def seed_products_if_empty():
    db = get_db()
    n = db.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    if n == 0:
        now = datetime.utcnow().isoformat(timespec="seconds")
        db.executemany("""
            INSERT INTO products(name, category, material, price, stock, lead_time_days, photo_url, stl_url, created_at)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, [
            ("PS5 DualSense Stand (Ters Slotlu)", "Aksesuar", "PLA", 249, 15, 2, "", "", now),
            ("Kablo Düzenleyici Klips Seti (10'lu)", "Organizasyon", "PETG", 129, 40, 1, "", "", now),
            ("Masa Üstü Telefon Standı (Ayarlı)", "Stand", "PLA", 159, 25, 1, "", "", now),
        ])
        db.commit()

def distinct_values(col: str):
    rows = get_db().execute(f"SELECT DISTINCT {col} AS v FROM products ORDER BY v").fetchall()
    return [r["v"] for r in rows if (r["v"] or "").strip()]

def fetch_products(q="", cat="", mat=""):
    q = (q or "").strip().lower()
    cat = (cat or "").strip()
    mat = (mat or "").strip()
    sql = "SELECT * FROM products WHERE 1=1"
    args = []
    if q:
        sql += " AND LOWER(name) LIKE ?"
        args.append(f"%{q}%")
    if cat:
        sql += " AND category = ?"
        args.append(cat)
    if mat:
        sql += " AND material = ?"
        args.append(mat)
    sql += " ORDER BY id DESC"
    return get_db().execute(sql, args).fetchall()

def fetch_product(pid: int):
    return get_db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()

def fetch_messages():
    return get_db().execute("SELECT * FROM messages ORDER BY id DESC").fetchall()

def count_unread_messages():
    return get_db().execute("SELECT COUNT(*) AS n FROM messages WHERE is_read=0").fetchone()["n"]

# --- Sayfa şablonu ---
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
    .nav {
      display:flex; gap:10px; align-items:center; justify-content:space-between;
      position: sticky; top:0; background:rgba(11,15,26,.85); backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--line);
      padding: 12px 18px; z-index: 10;
    }
    .brand { display:flex; flex-direction:column; line-height:1.1; }
    .brand b { font-size: 16px; letter-spacing:.2px; }
    .brand small { color:var(--muted); }
    .links { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    a.btn, button.btn {
      display:inline-flex; align-items:center; justify-content:center; gap:8px;
      padding: 8px 12px; border-radius: 10px;
      border: 1px solid var(--line); color:var(--text); text-decoration:none;
      background: rgba(255,255,255,0.03);
      cursor: pointer; white-space: nowrap;
    }
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

    input, textarea, select {
      width:100%; box-sizing:border-box; padding: 10px 12px; border-radius: 12px;
      border: 1px solid var(--line); background: rgba(0,0,0,.25); color: var(--text); outline:none;
    }
    input:focus, textarea:focus, select:focus { border-color: rgba(77,163,255,.7); }
    .row { display:flex; gap:10px; }
    .row > * { flex:1; }
    .actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .kpi { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
    .footer { padding: 22px 0; color: var(--muted); font-size: 13px; }
    .hr { height:1px; background: var(--line); margin: 12px 0; }
    .msg { border:1px solid rgba(255,80,80,.55); background: rgba(255,80,80,.08); padding:10px 12px; border-radius:14px; margin-bottom:12px; }
    .badge { display:inline-flex; align-items:center; gap:6px; }
    .dot { width:8px; height:8px; border-radius:99px; background: rgba(120,255,160,.8); box-shadow: 0 0 0 3px rgba(120,255,160,.14); }
    .dot.gray { background: rgba(170,180,200,.8); box-shadow: 0 0 0 3px rgba(170,180,200,.14); }
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

def require_admin():
    if not session.get("is_admin"):
        return redirect(url_for("login"))
    return None

@app.before_request
def _startup():
    init_db()
    seed_products_if_empty()

# --- WhatsApp satın al linki ---
def whatsapp_buy_link(product_row):
    num = get_whatsapp_number().strip()
    if not num:
        return ""  # numara yoksa buton göstermeyelim
    p = product_row
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
    encoded = urllib.parse.quote(text)
    return f"https://wa.me/{num}?text={encoded}"

# --- ROUTES ---
@app.get("/")
def home():
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
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
        <p>
          Stand, aksesuar, düzenleyici ve kişiye özel ürünler üretiyoruz.
          Katalogdan ürünlere bakabilir, sipariş için “Satın Al” ile WhatsApp’tan yazabilirsin.
        </p>

        <div class="list" style="margin-top:14px">
          <div class="item">
            <div class="meta">
              <b>Ürün kataloğu</b>
              <div class="sub">Mevcut ürünleri görüntüle</div>
            </div>
            <a class="btn primary" href="/products">Ürünlere git</a>
          </div>

          <div class="item">
            <div class="meta">
              <b>Tasarım & Üretim</b>
              <div class="sub">Vizyon ve misyon sayfasında detaylar</div>
            </div>
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
          <div class="actions">
            {stl_btn}
            {buy_btn}
            {admin_edit}
          </div>
        </div>
        """

    body = f"""
    <div class="card">
      <h1>Ürünler</h1>
      <p>Katalog: 3D baskı ürünleri.</p>

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
          <p>
            Kullanışlı, estetik ve dayanıklı 3D baskı ürünleriyle
            her masada/evde çözüm sunan bir atölye olmak.
          </p>
        </div>
        <div class="card">
          <h2>Misyon</h2>
          <p>
            Hızlı prototipleme ve üretim ile standlar, düzenleyiciler, aksesuarlar
            ve kişiye özel tasarımlar üretmek.
          </p>
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
        <h2>Çalışma</h2>
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
        body = """
        <div class="card">
          <div class="msg">Lütfen tüm alanları doldur.</div>
          <a class="btn primary" href="/contact">Geri dön</a>
        </div>
        """
        return page("Hata", body)

    now = datetime.utcnow().isoformat(timespec="seconds")
    db = get_db()
    db.execute(
        "INSERT INTO messages(name, email, message, is_read, created_at) VALUES(?,?,?,?,?)",
        (name, email, msg, 0, now)
    )
    db.commit()

    body = """
    <div class="card">
      <h1>Mesaj alındı</h1>
      <p class="sub">En kısa sürede dönüş yapılacak.</p>
      <div style="margin-top:12px"><a class="btn primary" href="/">Ana sayfaya dön</a></div>
    </div>
    """
    return page("Gönderildi", body)

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
    body = """
    <div class="card" style="max-width:520px">
      <div class="msg">Kullanıcı adı veya şifre yanlış.</div>
      <a class="btn primary" href="/login">Tekrar dene</a>
    </div>
    """
    return page("Hata", body)

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
        <p class="sub">Hızlı işlemler</p>

        <div class="list" style="margin-top:12px">
          <div class="item">
            <div class="meta">
              <b>Ürün ekle / düzenle</b>
              <div class="sub">Katalog yönetimi</div>
            </div>
            <a class="btn primary" href="/admin/products">Ürünler</a>
          </div>

          <div class="item">
            <div class="meta">
              <b>Mesajlar</b>
              <div class="sub">{unread} okunmamış mesaj</div>
            </div>
            <a class="btn primary" href="/admin/messages">Mesajları aç</a>
          </div>
        </div>
      </div>

      <div class="card">
        <h2>Durum</h2>
        <div class="kpi">
          <span class="pill">Okunmamış: {unread}</span>
          <span class="pill">WhatsApp: {"Ayarlı" if get_whatsapp_number().strip() else "Kapalı"}</span>
          <span class="pill">Şifre: .env</span>
        </div>
        <div class="hr"></div>
        <p class="sub">Not: .env yoksa giriş çalışmaz (ADMIN_PASS boş kalır).</p>
      </div>
    </div>
    """
    return page("Panel", body)

# --- Admin Products ---
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
        <p class="sub">Yeni ürün ekle</p>

        <form method="post" action="/admin/add" class="list" style="margin-top:12px">
          <input name="name" placeholder="Ürün adı" required />

          <div class="row">
            <input name="category" placeholder="Kategori (örn. Stand, Aksesuar...)" required />
            <select name="material" required>
              <option value="PLA">PLA</option>
              <option value="PETG">PETG</option>
              <option value="TPU">TPU</option>
              <option value="ABS">ABS</option>
              <option value="Diğer">Diğer</option>
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

    now = datetime.utcnow().isoformat(timespec="seconds")
    db = get_db()
    db.execute("""
        INSERT INTO products(name, category, material, price, stock, lead_time_days, photo_url, stl_url, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
    """, (name, category, material, price, stock, lead, photo_url, stl_url, now))
    db.commit()

    return redirect(url_for("admin_products"))

@app.post("/admin/delete")
def admin_delete():
    r = require_admin()
    if r: return r

    pid = safe_int(request.form.get("id"), 0, 0)
    db = get_db()
    db.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit()
    return redirect(url_for("admin_products"))

def material_options(selected: str) -> str:
    opts = ["PLA", "PETG", "TPU", "ABS", "Diğer"]
    return "".join([f'<option value="{esc(o)}" {"selected" if o==selected else ""}>{esc(o)}</option>' for o in opts])

@app.get("/admin/edit/<int:pid>")
def admin_edit(pid: int):
    r = require_admin()
    if r: return r

    p = fetch_product(pid)
    if not p:
        body = """
        <div class="card">
          <div class="msg">Ürün bulunamadı.</div>
          <a class="btn primary" href="/admin/products">Geri dön</a>
        </div>
        """
        return page("Düzenle", body)

    body = f"""
    <div class="card" style="max-width: 760px">
      <h1>Ürün Düzenle</h1>
      <p class="sub">#{p["id"]}</p>

      <form method="post" action="/admin/edit/{p["id"]}" class="list" style="margin-top:12px">
        <input name="name" value="{esc(p["name"])}" placeholder="Ürün adı" required />

        <div class="row">
          <input name="category" value="{esc(p["category"])}" placeholder="Kategori" required />
          <select name="material" required>{material_options(p["material"] or "")}</select>
        </div>

        <div class="row">
          <input name="price" type="number" min="0" step="1" value="{p["price"]}" placeholder="Fiyat (TL)" required />
          <input name="stock" type="number" min="0" step="1" value="{p["stock"]}" placeholder="Stok" required />
        </div>

        <div class="row">
          <input name="lead_time_days" type="number" min="0" step="1" value="{p["lead_time_days"]}" placeholder="Üretim süresi (gün)" required />
          <input name="photo_url" value="{esc(p["photo_url"] or "")}" placeholder="Foto linki (opsiyonel)" />
        </div>

        <input name="stl_url" value="{esc(p["stl_url"] or "")}" placeholder="STL linki (opsiyonel)" />

        <div class="row">
          <button class="btn primary" type="submit">Kaydet</button>
          <a class="btn" href="/admin/products">İptal</a>
          <a class="btn" href="/products">Kataloğu aç</a>
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
    db.execute("""
        UPDATE products
        SET name=?, category=?, material=?, price=?, stock=?, lead_time_days=?, photo_url=?, stl_url=?
        WHERE id=?
    """, (name, category, material, price, stock, lead, photo_url, stl_url, pid))
    db.commit()
    return redirect(url_for("admin_products"))

# --- Admin Messages ---
@app.get("/admin/messages")
def admin_messages():
    r = require_admin()
    if r: return r

    rows = fetch_messages()
    items = ""
    for m in rows:
        is_read = int(m["is_read"] or 0)
        dot = '<span class="dot gray"></span>' if is_read else '<span class="dot"></span>'
        status = "Okundu" if is_read else "Yeni"
        items += f"""
        <div class="item">
          <div class="meta">
            <div class="badge">{dot}<b>{esc(m["name"])}</b> <span class="pill">{status}</span></div>
            <div class="sub">{esc(m["email"])} • {esc(m["created_at"])}</div>
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

    unread = count_unread_messages()
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
    db.execute("UPDATE messages SET is_read=1 WHERE id=?", (mid,))
    db.commit()
    return redirect(url_for("admin_messages"))

@app.post("/admin/messages/delete")
def admin_message_delete():
    r = require_admin()
    if r: return r
    mid = safe_int(request.form.get("id"), 0, 0)
    db = get_db()
    db.execute("DELETE FROM messages WHERE id=?", (mid,))
    db.commit()
    return redirect(url_for("admin_messages"))

print("ENV_PATH:", ENV_PATH)
print("ENV exists:", os.path.exists(ENV_PATH))

print("WHATSAPP_NUMBER:", os.environ.get("WHATSAPP_NUMBER"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)