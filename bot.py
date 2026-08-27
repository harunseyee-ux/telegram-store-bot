import os
import sqlite3
import telebot
from telebot import types

# ==========================================
# KONFIGURASI BOT & ADMIN
# ==========================================
TOKEN = "YOUR_BOT_TOKEN_HERE"  # Ganti dengan token bot Telegram Anda
ADMIN_ID = 123456789           # Ganti dengan Telegram User ID Admin (integer)
REQUIRED_CHANNEL = "@channelusername"  # Ganti username channel join (atau None jika tidak pakai)

HEADER_MENU_PHOTO = "https://picsum.photos/600/300"  # Bisa pakai URL gambar atau file_id Telegram

bot = telebot.TeleBot(TOKEN)

# Penyimpanan State Pengguna sementara di Memory
user_data = {}

def get_state(chat_id):
    return user_data.get(chat_id, {}).get('state')

def set_state(chat_id, state):
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]['state'] = state

# ==========================================
# DATABASE SETUP (SQLite)
# ==========================================
DB_NAME = "store_bot.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Tabel Produk
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT
        )
    ''')
    
    # Tabel Pembayaran (Metode & Info)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            method TEXT PRIMARY KEY,
            info TEXT NOT NULL
        )
    ''')
    
    # Tabel Keranjang Belanja
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cart (
            user_id INTEGER,
            product_id INTEGER,
            quantity INTEGER,
            PRIMARY KEY (user_id, product_id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# --- DATABASE HELPER FUNCTIONS ---
def db_get_all_products():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, description FROM products")
    rows = cursor.fetchall()
    conn.close()
    return rows

def db_get_product(product_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price, description FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def db_add_product(name, price, description):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)", (name, price, description))
    conn.commit()
    conn.close()

def db_update_product_desc(product_id, new_desc):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET description = ? WHERE id = ?", (new_desc, product_id))
    conn.commit()
    conn.close()

def db_set_payment_info(method, info):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO payments (method, info) VALUES (?, ?)", (method.lower(), info))
    conn.commit()
    conn.close()

def db_get_payment_info(method):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT info FROM payments WHERE method = ?", (method.lower(),))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def db_add_to_cart(user_id, product_id, qty=1):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE cart SET quantity = quantity + ? WHERE user_id = ? AND product_id = ?", (qty, user_id, product_id))
    else:
        cursor.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)", (user_id, product_id, qty))
    conn.commit()
    conn.close()

def db_get_cart(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.id, p.name, p.price, c.quantity 
        FROM cart c 
        JOIN products p ON c.product_id = p.id 
        WHERE c.user_id = ?
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def db_clear_cart(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ==========================================
# COMPONENT BUILDERS (UI HELPER)
# ==========================================
def send_main_menu(chat_id):
    caption_text = (
        "👋 **Selamat Datang di Online Store!**\n\n"
        "Silakan pilih menu di bawah untuk menjelajahi katalog produk kami atau mengelola keranjang belanja Anda."
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🛍️ Katalog", callback_data="btn_catalog"),
        types.InlineKeyboardButton("🛒 Keranjang", callback_data="btn_cart"),
        types.InlineKeyboardButton("🔍 Cari", callback_data="btn_search"),
        types.InlineKeyboardButton("💳 Pembayaran", callback_data="btn_payment_info")
    )
    
    if chat_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("⚙️ Menu Admin", callback_data="btn_admin_menu"))
    
    # Kirim Foto dengan Caption dan Interaktif Menu
    bot.send_photo(chat_id, photo=HEADER_MENU_PHOTO, caption=caption_text, reply_markup=markup, parse_mode="Markdown")

def check_join_channel(user_id):
    if not REQUIRED_CHANNEL:
        return True
    try:
        member = bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return True

# ==========================================
# COMMAND HANDLERS
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    set_state(chat_id, None)
    
    if not check_join_channel(chat_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@','')}\"))
        markup.add(types.InlineKeyboardButton("✅ Sudah Join", callback_data="btn_check_join"))
        bot.send_message(chat_id, f"⚠️ Silakan bergabung ke channel {REQUIRED_CHANNEL} terlebih dahulu untuk menggunakan bot ini.", reply_markup=markup)
        return
        
    send_main_menu(chat_id)

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    if message.chat.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Anda tidak memiliki akses ke perintah ini.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ Tambah Produk", callback_data="admin_add_prod"),
        types.InlineKeyboardButton("📝 Edit Deskripsi", callback_data="admin_edit_desc"),
        types.InlineKeyboardButton("💳 Set Pembayaran", callback_data="admin_set_pay"),
        types.InlineKeyboardButton("💾 Backup DB", callback_data="admin_backup_db")
    )
    bot.send_message(message.chat.id, "🛠️ **Panel Kontrol Admin**", reply_markup=markup, parse_mode="Markdown")

# ==========================================
# CALLBACK QUERY ROUTER
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    bot.answer_callback_query(call.id)

    # --- MENU UTAMA & KATALOG ---
    if data == "btn_check_join":
        if check_join_channel(chat_id):
            bot.delete_message(chat_id, call.message.message_id)
            send_main_menu(chat_id)
        else:
            bot.send_message(chat_id, "❌ Anda belum terdeteksi bergabung ke channel.")

    elif data == "btn_catalog":
        products = db_get_all_products()
        if not products:
            bot.send_message(chat_id, "📦 Belum ada produk yang tersedia saat ini.")
            return
        
        markup = types.InlineKeyboardMarkup()
        for p in products:
            markup.add(types.InlineKeyboardButton(f"{p[1]} - Rp{p[2]:,.0f}", callback_data=f"prod_detail_{p[0]}"))
        bot.send_message(chat_id, "🛍️ **Daftar Produk:**", reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("prod_detail_"):
        pid = int(data.split("_")[2])
        product = db_get_product(pid)
        if product:
            text = f"📦 **{product[1]}**\n\n💰 **Harga:** Rp{product[2]:,.0f}\n📝 **Deskripsi:**\n{product[3] or '-'}"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Tambah ke Keranjang", callback_data=f"cart_add_{product[0]}"))
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("cart_add_"):
        pid = int(data.split("_")[2])
        db_add_to_cart(chat_id, pid, 1)
        bot.send_message(chat_id, "✅ Produk telah ditambahkan ke keranjang belanja.")

    elif data == "btn_cart":
        items = db_get_cart(chat_id)
        if not items:
            bot.send_message(chat_id, "🛒 Keranjang belanja Anda masih kosong.")
            return
        
        total = 0
        text = "🛒 **Keranjang Belanja Anda:**\n\n"
        for item in items:
            subtotal = item[2] * item[3]
            total += subtotal
            text += f"• **{item[1]}** ({item[3]}x) = Rp{subtotal:,.0f}\n"
        text += f"\n💰 **Total Bayar:** Rp{total:,.0f}"

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("💳 Checkout", callback_data="btn_checkout"),
            types.InlineKeyboardButton("🗑️ Kosongkan", callback_data="btn_clear_cart")
        )
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

    elif data == "btn_clear_cart":
        db_clear_cart(chat_id)
        bot.send_message(chat_id, "🗑️ Keranjang belanja telah dikosongkan.")

    elif data == "btn_checkout":
        items = db_get_cart(chat_id)
        if not items:
            bot.send_message(chat_id, "🛒 Keranjang Anda kosong.")
            return
        
        total = sum(item[2] * item[3] for item in items)
        bot.send_message(chat_id, f"✅ Silakan lakukan pembayaran sebesar **Rp{total:,.0f}**.\nPilih menu Pembayaran untuk instruksi transfer.", parse_mode="Markdown")
        db_clear_cart(chat_id)

    elif data == "btn_search":
        set_state(chat_id, "WAITING_SEARCH")
        bot.send_message(chat_id, "🔍 Masukkan nama produk yang ingin Anda cari:")

    elif data == "btn_payment_info":
        text = "💳 **Metode Pembayaran Tersedia:**\n\n"
        dana = db_get_payment_info('dana')
        gopay = db_get_payment_info('gopay')
        qris = db_get_payment_info('qris')

        text += f"🔹 **DANA:** `{dana or 'Belum diatur'}`\n"
        text += f"🔹 **GoPay:** `{gopay or 'Belum diatur'}`\n"
        bot.send_message(chat_id, text, parse_mode="Markdown")

        if qris:
            if qris.startswith("http") or qris.isalnum():
                bot.send_photo(chat_id, photo=qris, caption="📲 **QRIS Payment**")

    # --- ADMIN FEATURES ---
    elif data == "btn_admin_menu":
        cmd_admin(call.message)

    elif data == "admin_add_prod":
        if chat_id != ADMIN_ID: return
        set_state(chat_id, "WAITING_ADD_PROD")
        bot.send_message(chat_id, "📝 Kirimkan detail produk dengan format:\n\n`Nama Produk | Harga | Deskripsi`\n\n*Contoh:* `Voucher Game | 50000 | Kode voucher 50rb`", parse_mode="Markdown")

    elif data == "admin_edit_desc":
        if chat_id != ADMIN_ID: return
        products = db_get_all_products()
        if not products:
            bot.send_message(chat_id, "❌ Belum ada produk.")
            return
        
        markup = types.InlineKeyboardMarkup()
        for p in products:
            markup.add(types.InlineKeyboardButton(f"Edit Desc #{p[0]}: {p[1]}", callback_data=f"admin_select_desc_{p[0]}"))
        bot.send_message(chat_id, "📝 Pilih produk yang ingin diubah deskripsinya:", reply_markup=markup)

    elif data.startswith("admin_select_desc_"):
        pid = int(data.split("_")[3])
        if chat_id in user_data:
            user_data[chat_id]['edit_product_id'] = pid
        else:
            user_data[chat_id] = {'edit_product_id': pid}
            
        set_state(chat_id, "WAITING_NEW_DESC")
        bot.send_message(chat_id, f"📝 Masukkan deskripsi baru untuk Produk ID #{pid}:")

    elif data == "admin_set_pay":
        if chat_id != ADMIN_ID: return
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("DANA", callback_data="admin_pay_dana"),
            types.InlineKeyboardButton("GoPay", callback_data="admin_pay_gopay"),
            types.InlineKeyboardButton("QRIS (Foto)", callback_data="admin_pay_qris")
        )
        bot.send_message(chat_id, "💳 Pilih metode pembayaran yang ingin diatur:", reply_markup=markup)

    elif data in ["admin_pay_dana", "admin_pay_gopay"]:
        method = data.replace("admin_pay_", "")
        if chat_id not in user_data: user_data[chat_id] = {}
        user_data[chat_id]['payment_method'] = method
        set_state(chat_id, "WAITING_PAYMENT_DATA")
        bot.send_message(chat_id, f"📥 Kirimkan nomor/rekening untuk **{method.upper()}**:")

    elif data == "admin_pay_qris":
        if chat_id not in user_data: user_data[chat_id] = {}
        user_data[chat_id]['payment_method'] = 'qris'
        set_state(chat_id, "WAITING_QRIS_PHOTO")
        bot.send_message(chat_id, "🖼️ Silakan upload/kirimkan **foto QRIS**:")

    elif data == "admin_backup_db":
        if chat_id != ADMIN_ID: return
        if os.path.exists(DB_NAME):
            with open(DB_NAME, 'rb') as f:
                bot.send_document(chat_id, f, caption="💾 Backup database SQLite.")
        else:
            bot.send_message(chat_id, "❌ Database tidak ditemukan.")

# ==========================================
# TEXT & PHOTO ROUTER HANDLER
# ==========================================
@bot.message_handler(content_types=['text'])
def receive_text(msg):
    chat_id = msg.chat.id
    current_state = get_state(chat_id)
    text = msg.text.strip()

    if not current_state:
        return

    # 1. PENCARIAN PRODUK
    if current_state == 'WAITING_SEARCH':
        set_state(chat_id, None)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, price FROM products WHERE name LIKE ?", (f"%{text}%",))
        results = cursor.fetchall()
        conn.close()

        if not results:
            bot.send_message(chat_id, f"❌ Produk dengan kata kunci '{text}' tidak ditemukan.")
            return

        markup = types.InlineKeyboardMarkup()
        for r in results:
            markup.add(types.InlineKeyboardButton(f"{r[1]} - Rp{r[2]:,.0f}", callback_data=f"prod_detail_{r[0]}"))
        bot.send_message(chat_id, f"🔎 Hasil pencarian '{text}':", reply_markup=markup)

    # 2. TAMBAH PRODUK (ADMIN)
    elif current_state == 'WAITING_ADD_PROD' and chat_id == ADMIN_ID:
        set_state(chat_id, None)
        try:
            parts = text.split("|")
            name = parts[0].strip()
            price = float(parts[1].strip())
            desc = parts[2].strip() if len(parts) > 2 else ""
            
            db_add_product(name, price, desc)
            bot.send_message(chat_id, f"✅ Produk **{name}** berhasil ditambahkan!", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(chat_id, "❌ Format salah. Gunakan: `Nama | Harga | Deskripsi`", parse_mode="Markdown")

    # 3. EDIT DESKRIPSI PRODUK (ADMIN)
    elif current_state == 'WAITING_NEW_DESC' and chat_id == ADMIN_ID:
        product_id = user_data.get(chat_id, {}).get('edit_product_id')
        if product_id:
            db_update_product_desc(product_id, text)
            set_state(chat_id, None)
            bot.send_message(chat_id, f"✅ Deskripsi Produk #{product_id} berhasil diperbarui!")

    # 4. FIX: PAYMENT DATA (DANA / GOPAY)
    elif current_state == 'WAITING_PAYMENT_DATA' and chat_id == ADMIN_ID:
        method = user_data.get(chat_id, {}).get('payment_method')
        if method:
            db_set_payment_info(method, text)
            set_state(chat_id, None)
            bot.send_message(chat_id, f"✅ Rekening/Nomor **{method.upper()}** berhasil disimpan:\n`{text}`", parse_mode="Markdown")

@bot.message_handler(content_types=['photo'])
def photo_router(msg):
    chat_id = msg.chat.id
    current_state = get_state(chat_id)

    # FIX: UPLOAD FOTO QRIS
    if current_state == 'WAITING_QRIS_PHOTO' and chat_id == ADMIN_ID:
        file_id = msg.photo[-1].file_id  # Ambil foto kualitas paling tinggi
        db_set_payment_info('qris', file_id)
        set_state(chat_id, None)
        bot.send_message(chat_id, "✅ Foto QRIS berhasil disimpan dan diperbarui!")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("🤖 Bot Store sedang berjalan...")
    bot.infinity_polling()
