import sqlite3
import json
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from datetime import datetime

app = Flask(__name__)
app.secret_key = "dine_quick_secret_2024"

# Use absolute path resolving to protect against Flask reloader path shifting
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dine_quick.db")

# ─── Database Setup ────────────────────────────────────────────────────────────

def get_db():
    # SAFETY NET: Create the directory path dynamically if it somehow doesn't exist
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            icon TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            available INTEGER DEFAULT 1,
            prep_time INTEGER DEFAULT 10,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );

        CREATE TABLE IF NOT EXISTS tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            seats INTEGER DEFAULT 4
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Placed',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY(table_id) REFERENCES tables(id)
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(item_id) REFERENCES menu_items(id)
        );
    """)

    # Default settings
    cur.execute("INSERT OR IGNORE INTO settings VALUES ('tax_rate', '5.0')")
    cur.execute("INSERT OR IGNORE INTO settings VALUES ('restaurant_name', 'Dine Quick')")
    cur.execute("INSERT OR IGNORE INTO settings VALUES ('currency_symbol', '₹')")

    # Seed categories
    cats = [("Starters", "🥗", 1), ("Mains", "🍛", 2), ("Drinks", "🥤", 3), ("Desserts", "🍮", 4)]
    for name, icon, order in cats:
        cur.execute("INSERT OR IGNORE INTO categories(name, icon, sort_order) VALUES (?,?,?)",
                    (name, icon, order))

    # Seed menu items
    items = [
        # Starters
        (1, "Paneer Tikka", "Marinated cottage cheese grilled in tandoor", 220, 1, 12),
        (1, "Veg Spring Rolls", "Crispy rolls with mixed veggies & dipping sauce", 160, 1, 8),
        (1, "Chicken Wings", "Spiced wings with garlic aioli", 280, 1, 15),
        (1, "Masala Papad", "Topped with onion, tomato & green chilli", 80, 1, 5),
        (1, "Soup of the Day", "Chef's special seasonal soup", 120, 1, 10),
        # Mains
        (2, "Butter Chicken", "Classic creamy tomato-based curry with naan", 380, 1, 20),
        (2, "Dal Makhani", "Black lentils slow-cooked overnight, rice included", 260, 1, 18),
        (2, "Paneer Kadai", "Cottage cheese in spiced bell pepper gravy", 300, 1, 18),
        (2, "Biryani (Veg)", "Fragrant basmati rice with seasonal vegetables", 280, 1, 22),
        (2, "Biryani (Chicken)", "Aromatic chicken biryani with raita", 360, 1, 25),
        (2, "Tandoori Roti", "Whole wheat bread from the tandoor", 30, 1, 5),
        (2, "Garlic Naan", "Leavened bread brushed with garlic butter", 60, 1, 7),
        # Drinks
        (3, "Mango Lassi", "Thick yogurt-based mango smoothie", 120, 1, 5),
        (3, "Masala Chai", "Spiced Indian tea with milk", 60, 1, 5),
        (3, "Fresh Lime Soda", "Sweet or salted, chilled", 80, 1, 3),
        (3, "Mineral Water", "500ml chilled bottle", 40, 1, 2),
        (3, "Cold Coffee", "Blended with ice cream, chilled", 140, 1, 7),
        # Desserts
        (4, "Gulab Jamun", "Soft milk-solid dumplings in rose syrup (2 pcs)", 110, 1, 8),
        (4, "Kulfi", "Traditional Indian ice cream — rose or pistachio", 130, 1, 5),
        (4, "Kheer", "Creamy rice pudding with cardamom & nuts", 100, 1, 10),
    ]
    for item in items:
        cat_id, name, desc, price, avail, prep = item
        cur.execute("""INSERT OR IGNORE INTO menu_items(category_id,name,description,price,available,prep_time)
                       SELECT ?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM menu_items WHERE name=?)""",
                    (cat_id, name, desc, price, avail, prep, name))

    # Seed tables
    for i in range(1, 13):
        seats = 2 if i <= 2 else (6 if i >= 11 else 4)
        cur.execute("INSERT OR IGNORE INTO tables(number, name, seats) VALUES (?,?,?)",
                    (i, f"Table {i}", seats))

    conn.commit()
    conn.close()

# ─── Helpers ───────────────────────────────────────────────────────────────────

def get_setting(key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def get_all_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def get_order_total(order_id):
    conn = get_db()
    row = conn.execute("""SELECT COALESCE(SUM(quantity * unit_price), 0) as subtotal
                          FROM order_items WHERE order_id=?""", (order_id,)).fetchone()
    conn.close()
    return row["subtotal"] if row else 0

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ─── Customer Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    conn = get_db()
    tables = conn.execute("SELECT * FROM tables ORDER BY number").fetchall()
    conn.close()
    settings = get_all_settings()
    return render_template("index.html", tables=tables, settings=settings)

@app.route("/table/<int:table_number>")
def table_menu(table_number):
    conn = get_db()
    table = conn.execute("SELECT * FROM tables WHERE number=?", (table_number,)).fetchone()
    if not table:
        conn.close()
        return "Table not found", 404
    categories = conn.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()
    items = conn.execute("""SELECT m.*, c.name as cat_name FROM menu_items m
                            JOIN categories c ON m.category_id=c.id
                            ORDER BY m.category_id, m.name""").fetchall()
    # Active orders for this table
    orders = conn.execute("""SELECT o.*, t.name as table_name FROM orders o
                              JOIN tables t ON o.table_id=t.id
                              WHERE o.table_id=? AND o.status != 'Served'
                              ORDER BY o.created_at DESC""", (table["id"],)).fetchall()
    conn.close()
    settings = get_all_settings()
    return render_template("menu.html", table=table, categories=categories,
                           items=items, orders=orders, settings=settings)

@app.route("/table/<int:table_number>/order-status")
def order_status(table_number):
    conn = get_db()
    table = conn.execute("SELECT * FROM tables WHERE number=?", (table_number,)).fetchone()
    if not table:
        conn.close()
        return "Table not found", 404
    orders = conn.execute("""SELECT o.id, o.status, o.created_at, o.updated_at, o.notes
                              FROM orders o WHERE o.table_id=?
                              ORDER BY o.created_at DESC LIMIT 10""", (table["id"],)).fetchall()
    result = []
    for o in orders:
        oi = conn.execute("""SELECT oi.quantity, oi.unit_price, m.name
                              FROM order_items oi JOIN menu_items m ON oi.item_id=m.id
                              WHERE oi.order_id=?""", (o["id"],)).fetchall()
        subtotal = sum(row["quantity"] * row["unit_price"] for row in oi)
        tax_rate = float(get_setting("tax_rate", "5"))
        tax = subtotal * tax_rate / 100
        result.append({
            "id": o["id"],
            "status": o["status"],
            "created_at": o["created_at"],
            "updated_at": o["updated_at"],
            "notes": o["notes"],
            "items": [{"name": r["name"], "quantity": r["quantity"], "unit_price": r["unit_price"]} for r in oi],
            "subtotal": round(subtotal, 2),
            "tax": round(tax, 2),
            "total": round(subtotal + tax, 2)
        })
    conn.close()
    return jsonify(result)

# ─── API: Menu ─────────────────────────────────────────────────────────────────

@app.route("/api/menu")
def api_menu():
    conn = get_db()
    items = conn.execute("""SELECT m.*, c.name as category_name, c.icon as category_icon
                            FROM menu_items m JOIN categories c ON m.category_id=c.id
                            ORDER BY c.sort_order, m.name""").fetchall()
    conn.close()
    return jsonify([dict(i) for i in items])

# ─── API: Orders ───────────────────────────────────────────────────────────────

@app.route("/api/orders", methods=["POST"])
def place_order():
    data = request.json
    table_number = data.get("table_number")
    cart = data.get("cart", [])
    notes = data.get("notes", "")
    if not table_number or not cart:
        return jsonify({"error": "Missing table or cart"}), 400
    conn = get_db()
    table = conn.execute("SELECT * FROM tables WHERE number=?", (table_number,)).fetchone()
    if not table:
        conn.close()
        return jsonify({"error": "Invalid table"}), 404
    ts = now_str()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders(table_id,status,created_at,updated_at,notes) VALUES (?,?,?,?,?)",
                (table["id"], "Placed", ts, ts, notes))
    order_id = cur.lastrowid
    for cart_item in cart:
        item = conn.execute("SELECT * FROM menu_items WHERE id=?", (cart_item["id"],)).fetchone()
        if item:
            cur.execute("INSERT INTO order_items(order_id,item_id,quantity,unit_price) VALUES (?,?,?,?)",
                        (order_id, item["id"], cart_item["quantity"], item["price"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "order_id": order_id})

@app.route("/api/orders/<int:order_id>/status", methods=["PATCH"])
def update_order_status(order_id):
    data = request.json
    new_status = data.get("status")
    valid = ["Placed", "Cooking", "Served"]
    if new_status not in valid:
        return jsonify({"error": "Invalid status"}), 400
    conn = get_db()
    conn.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                 (new_status, now_str(), order_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/orders/active")
def active_orders():
    conn = get_db()
    orders = conn.execute("""SELECT o.id, o.status, o.created_at, o.updated_at, o.notes,
                                     t.number as table_number, t.name as table_name
                              FROM orders o JOIN tables t ON o.table_id=t.id
                              WHERE o.status IN ('Placed','Cooking')
                              ORDER BY o.created_at ASC""").fetchall()
    result = []
    for o in orders:
        items = conn.execute("""SELECT oi.quantity, oi.unit_price, m.name, m.prep_time
                                 FROM order_items oi JOIN menu_items m ON oi.item_id=m.id
                                 WHERE oi.order_id=?""", (o["id"],)).fetchall()
        result.append({
            "id": o["id"],
            "status": o["status"],
            "created_at": o["created_at"],
            "updated_at": o["updated_at"],
            "notes": o["notes"],
            "table_number": o["table_number"],
            "table_name": o["table_name"],
            "items": [{"name": r["name"], "quantity": r["quantity"],
                       "unit_price": r["unit_price"], "prep_time": r["prep_time"]} for r in items]
        })
    conn.close()
    return jsonify(result)

@app.route("/api/orders/all")
def all_orders():
    conn = get_db()
    orders = conn.execute("""SELECT o.id, o.status, o.created_at, o.updated_at, o.notes,
                                     t.number as table_number, t.name as table_name
                              FROM orders o JOIN tables t ON o.table_id=t.id
                              ORDER BY o.created_at DESC LIMIT 100""").fetchall()
    result = []
    for o in orders:
        items = conn.execute("""SELECT oi.quantity, oi.unit_price, m.name
                                 FROM order_items oi JOIN menu_items m ON oi.item_id=m.id
                                 WHERE oi.order_id=?""", (o["id"],)).fetchall()
        subtotal = sum(r["quantity"] * r["unit_price"] for r in items)
        tax_rate = float(get_setting("tax_rate", "5"))
        result.append({
            "id": o["id"],
            "status": o["status"],
            "created_at": o["created_at"],
            "updated_at": o["updated_at"],
            "notes": o["notes"],
            "table_number": o["table_number"],
            "table_name": o["table_name"],
            "items": [{"name": r["name"], "quantity": r["quantity"], "unit_price": r["unit_price"]} for r in items],
            "subtotal": round(subtotal, 2),
            "tax": round(subtotal * tax_rate / 100, 2),
            "total": round(subtotal * (1 + tax_rate / 100), 2)
        })
    conn.close()
    return jsonify(result)

# ─── Kitchen Route ─────────────────────────────────────────────────────────────

@app.route("/kitchen")
def kitchen():
    settings = get_all_settings()
    return render_template("kitchen.html", settings=settings)

# ─── Admin Routes ──────────────────────────────────────────────────────────────

@app.route("/admin")
def admin():
    conn = get_db()
    categories = conn.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()
    items = conn.execute("""SELECT m.*, c.name as cat_name FROM menu_items m
                            JOIN categories c ON m.category_id=c.id
                            ORDER BY c.sort_order, m.name""").fetchall()
    conn.close()
    settings = get_all_settings()
    return render_template("admin.html", categories=categories, items=items, settings=settings)

@app.route("/api/admin/items", methods=["POST"])
def admin_add_item():
    d = request.json
    conn = get_db()
    conn.execute("""INSERT INTO menu_items(category_id,name,description,price,available,prep_time)
                    VALUES (?,?,?,?,?,?)""",
                 (d["category_id"], d["name"], d.get("description",""),
                  float(d["price"]), int(d.get("available", 1)), int(d.get("prep_time", 10))))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/admin/items/<int:item_id>", methods=["PATCH"])
def admin_update_item(item_id):
    d = request.json
    conn = get_db()
    fields = []
    vals = []
    for col in ["name", "description", "price", "available", "prep_time", "category_id"]:
        if col in d:
            fields.append(f"{col}=?")
            vals.append(d[col])
    if fields:
        vals.append(item_id)
        conn.execute(f"UPDATE menu_items SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/admin/items/<int:item_id>", methods=["DELETE"])
def admin_delete_item(item_id):
    conn = get_db()
    conn.execute("DELETE FROM menu_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/admin/settings", methods=["PATCH"])
def admin_update_settings():
    d = request.json
    conn = get_db()
    for k, v in d.items():
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (k, str(v)))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/admin/stats")
def admin_stats():
    conn = get_db()
    total_orders = conn.execute("SELECT COUNT(*) as c FROM orders").fetchone()["c"]
    active_orders = conn.execute("SELECT COUNT(*) as c FROM orders WHERE status IN ('Placed','Cooking')").fetchone()["c"]
    served_today = conn.execute("""SELECT COUNT(*) as c FROM orders
                                   WHERE status='Served' AND date(created_at)=date('now')""").fetchone()["c"]
    revenue_today = conn.execute("""SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0) as r
                                    FROM order_items oi JOIN orders o ON oi.order_id=o.id
                                    WHERE o.status='Served' AND date(o.created_at)=date('now')""").fetchone()["r"]
    conn.close()
    return jsonify({
        "total_orders": total_orders,
        "active_orders": active_orders,
        "served_today": served_today,
        "revenue_today": round(revenue_today, 2)
    })

# ─── Safe Execution Block ──────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ensure init_db runs completely within Flask's application context framework
    with app.app_context():
        init_db()
    app.run(debug=True, port=5000)