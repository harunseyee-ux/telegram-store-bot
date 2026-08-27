import os, sqlite3, logging, re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

TOKEN = os.getenv("BOT_TOKEN", "")
REQUIRED_CHAT = os.getenv("REQUIRED_CHAT", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID", "").strip()
PAYMENT_INFO = os.getenv("PAYMENT_INFO", "Hubungi admin untuk info pembayaran.")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")
DB = "store.db"
logging.basicConfig(level=logging.INFO)

STATUS_TEXT = {
    "pending_payment": "Menunggu pembayaran",
    "proof_received": "Bukti diterima",
    "processing": "Sedang diproses",
    "paid": "Pembayaran dikonfirmasi",
    "rejected": "Ditolak",
    "completed": "Selesai",
}

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price TEXT NOT NULL,
        description TEXT DEFAULT '',
        photo TEXT DEFAULT ''
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        status TEXT DEFAULT 'pending_payment'
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    )""")
    con.commit()
    return con

def get_payment():
    con = db()
    row = con.execute("SELECT value FROM settings WHERE key='payment_info'").fetchone()
    con.close()
    return row[0] if row and row[0] else PAYMENT_INFO

def set_payment(value):
    con = db()
    con.execute("INSERT INTO settings(key,value) VALUES('payment_info',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
    con.commit(); con.close()

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Katalog", callback_data="catalog")],
        [InlineKeyboardButton("📦 Pesanan Saya", callback_data="orders")],
        [InlineKeyboardButton("💳 Pembayaran", callback_data="payment")],
        [InlineKeyboardButton("👨‍💻 Contact Admin", callback_data="support")]
    ])

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Kelola Produk", callback_data="adminlist")],
        [InlineKeyboardButton("📦 Kelola Pesanan", callback_data="adminorders")],
        [InlineKeyboardButton("💳 Edit Payment", callback_data="adminpayment")],
    ])

def order_buttons(oid, include_payment=True):
    rows = []
    if include_payment:
        rows.append([InlineKeyboardButton("💳 INFO PEMBAYARAN", callback_data=f"payorder:{oid}")])
    rows.append([InlineKeyboardButton("📤 CARA KIRIM BUKTI", callback_data=f"proofhelp:{oid}")])
    rows.append([InlineKeyboardButton("⬅️ Menu", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def admin_order_buttons(oid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ PROSES", callback_data=f"setstatus:processing:{oid}")],
        [InlineKeyboardButton("✅ APPROVED", callback_data=f"setstatus:paid:{oid}"), InlineKeyboardButton("❌ REJECTED", callback_data=f"setstatus:rejected:{oid}")],
        [InlineKeyboardButton("🏁 SELESAI", callback_data=f"setstatus:completed:{oid}")]
    ])

async def is_joined(update, context):
    if not REQUIRED_CHAT:
        return True
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHAT, update.effective_user.id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

async def safe_delete(message):
    try:
        await message.delete()
    except Exception:
        pass

async def send_home(chat_id, context, text="🔥 *Menu Utama*"):
    await context.bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=menu())

async def start(update, context):
    if not await is_joined(update, context):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 JOIN GRUP", url=f"https://t.me/{REQUIRED_CHAT.lstrip('@')}")],
            [InlineKeyboardButton("✅ SUDAH JOIN", callback_data="check_join")]
        ])
        await update.message.reply_text("🔒 *Akses dikunci*\n\nJoin grup wajib terlebih dahulu, lalu tekan *SUDAH JOIN*.", parse_mode="Markdown", reply_markup=kb)
        return
    await update.message.reply_text("🔥 *Selamat datang di Store!*\nPilih menu di bawah.", parse_mode="Markdown", reply_markup=menu())

async def notify_admins(context, text, reply_markup=None, photo=None):
    sent = []
    for admin_id in ADMIN_IDS:
        try:
            if photo:
                m = await context.bot.send_photo(admin_id, photo=photo, caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            else:
                m = await context.bot.send_message(admin_id, text, parse_mode="Markdown", reply_markup=reply_markup)
            sent.append(m)
        except Exception:
            logging.exception("Private admin notification failed for %s", admin_id)
    if ADMIN_GROUP_ID:
        try:
            if photo:
                await context.bot.send_photo(ADMIN_GROUP_ID, photo=photo, caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            else:
                await context.bot.send_message(ADMIN_GROUP_ID, text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            logging.exception("Admin group notification failed")
    return sent

async def callback(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "check_join":
        if await is_joined(update, context):
            await safe_delete(q.message)
            await send_home(update.effective_user.id, context, "✅ *Verifikasi berhasil!*\n\nSelamat datang di Store 🔥")
        else:
            await q.answer("❌ Kamu belum join grup!", show_alert=True)
        return

    if not await is_joined(update, context):
        await q.answer("❌ Join grup wajib dulu.", show_alert=True)
        return

    if data == "home":
        await safe_delete(q.message)
        await send_home(update.effective_user.id, context)

    elif data == "catalog":
        con = db(); rows = con.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall(); con.close()
        await safe_delete(q.message)
        if not rows:
            await context.bot.send_message(update.effective_user.id, "📭 Katalog masih kosong.", reply_markup=menu())
            return
        kb = [[InlineKeyboardButton(f"🛍️ {r[1]} • {r[2]}", callback_data=f"product:{r[0]}")] for r in rows]
        kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data="home")])
        await context.bot.send_message(update.effective_user.id, "🛒 *Katalog Produk*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("product:"):
        pid = int(data.split(":")[1]); con=db()
        p=con.execute("SELECT id,name,price,description,photo FROM products WHERE id=?",(pid,)).fetchone(); con.close()
        if not p: await q.answer("Produk tidak ditemukan.",show_alert=True); return
        await safe_delete(q.message)
        text=f"🛍️ *{p[1]}*\n💰 Harga: `{p[2]}`\n\n{p[3] or 'Tidak ada deskripsi.'}"
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 BELI",callback_data=f"buy:{p[0]}")],[InlineKeyboardButton("⬅️ Katalog",callback_data="catalog")]])
        if p[4]:
            await context.bot.send_photo(update.effective_user.id,photo=p[4],caption=text,parse_mode="Markdown",reply_markup=kb)
        else:
            await context.bot.send_message(update.effective_user.id,text,parse_mode="Markdown",reply_markup=kb)

    elif data.startswith("buy:"):
        pid=int(data.split(":")[1]); con=db()
        p=con.execute("SELECT id,name,price FROM products WHERE id=?",(pid,)).fetchone()
        if not p: con.close(); await q.answer("Produk tidak ditemukan.",show_alert=True); return
        cur=con.execute("INSERT INTO orders(user_id,product_id,status) VALUES(?,?,?)",(update.effective_user.id,pid,"pending_payment")); oid=cur.lastrowid
        con.commit(); con.close()
        await safe_delete(q.message)
        text=(f"🧾 *ORDER BERHASIL DIBUAT*\n\n🆔 ID Transaksi: `ORD-{oid:05d}`\n📦 Produk: {p[1]}\n💰 Harga: {p[2]}\n📌 Status: Menunggu pembayaran\n\n💳 *Pembayaran:*\n{get_payment()}\n\nSetelah bayar, kirim *foto bukti pembayaran* ke chat bot ini.\nTulis `ORD-{oid:05d}` di caption foto.")
        await context.bot.send_message(update.effective_user.id,text,parse_mode="Markdown",reply_markup=order_buttons(oid))
        admin_text=(f"🔔 *PESANAN BARU*\n\n🆔 `ORD-{oid:05d}`\n👤 User ID: `{update.effective_user.id}`\n📦 {p[1]}\n💰 {p[2]}\n📌 Status: Menunggu pembayaran")
        await notify_admins(context,admin_text,admin_order_buttons(oid))

    elif data.startswith("payorder:"):
        oid=int(data.split(":")[1]); await safe_delete(q.message)
        await context.bot.send_message(update.effective_user.id,f"💳 *Pembayaran ORD-{oid:05d}*\n\n{get_payment()}\n\nKirim foto bukti pembayaran dengan caption `ORD-{oid:05d}`.",parse_mode="Markdown",reply_markup=order_buttons(oid,False))

    elif data.startswith("proofhelp:"):
        oid=int(data.split(":")[1]); await safe_delete(q.message)
        await context.bot.send_message(update.effective_user.id,f"📤 *Cara Kirim Bukti*\n\n1. Bayar sesuai info pembayaran.\n2. Kirim foto bukti ke chat bot.\n3. Caption wajib berisi `ORD-{oid:05d}`.\n4. Admin akan mengecek.",parse_mode="Markdown",reply_markup=order_buttons(oid,False))

    elif data == "orders":
        con=db(); rows=con.execute("SELECT o.id,p.name,p.price,o.status FROM orders o JOIN products p ON p.id=o.product_id WHERE o.user_id=? ORDER BY o.id DESC",(update.effective_user.id,)).fetchall(); con.close()
        text="📦 Belum ada pesanan." if not rows else "📦 *Pesanan Saya*\n\n"+"\n".join(f"🆔 ORD-{r[0]:05d}\n📦 {r[1]}\n💰 {r[2]}\n📌 {STATUS_TEXT.get(r[3],r[3])}\n" for r in rows)
        await safe_delete(q.message); await context.bot.send_message(update.effective_user.id,text,parse_mode="Markdown",reply_markup=menu())

    elif data == "payment":
        await safe_delete(q.message); await context.bot.send_message(update.effective_user.id,f"💳 *Pembayaran*\n\n{get_payment()}",parse_mode="Markdown",reply_markup=menu())

    elif data == "support":
        await safe_delete(q.message); await context.bot.send_message(update.effective_user.id,f"👨‍💻 *Contact Admin*\n\n{SUPPORT_USERNAME or 'Silakan hubungi admin toko.'}",parse_mode="Markdown",reply_markup=menu())

    elif data == "adminlist":
        if update.effective_user.id not in ADMIN_IDS: return
        con=db(); rows=con.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall(); con.close()
        await safe_delete(q.message)
        if not rows: await context.bot.send_message(update.effective_user.id,"🛒 Katalog kosong.",reply_markup=admin_menu()); return
        kb=[[InlineKeyboardButton(f"🛍️ {n} • {p}",callback_data=f"adminview:{pid}")] for pid,n,p in rows]
        kb.append([InlineKeyboardButton("⬅️ Admin Panel",callback_data="adminhome")])
        await context.bot.send_message(update.effective_user.id,"👑 *Kelola Produk*",parse_mode="Markdown",reply_markup=InlineKeyboardMarkup(kb))

    elif data == "adminhome":
        if update.effective_user.id not in ADMIN_IDS: return
        await safe_delete(q.message); await context.bot.send_message(update.effective_user.id,"👑 *Admin Panel*",parse_mode="Markdown",reply_markup=admin_menu())

    elif data == "adminpayment":
        if update.effective_user.id not in ADMIN_IDS: return
        await safe_delete(q.message); await context.bot.send_message(update.effective_user.id,"💳 *Payment Saat Ini:*\n\n"+get_payment()+"\n\nUntuk mengubah: kirim `/setpayment isi payment baru`",parse_mode="Markdown",reply_markup=admin_menu())

    elif data == "adminorders":
        if update.effective_user.id not in ADMIN_IDS: return
        con=db(); rows=con.execute("SELECT o.id,p.name,p.price,o.status FROM orders o JOIN products p ON p.id=o.product_id ORDER BY o.id DESC LIMIT 30").fetchall(); con.close()
        await safe_delete(q.message)
        text="📦 *Order Terbaru*\n\n"+"\n".join(f"ORD-{r[0]:05d} • {r[1]} • {r[2]} • {STATUS_TEXT.get(r[3],r[3])}" for r in rows) if rows else "📦 Belum ada order."
        await context.bot.send_message(update.effective_user.id,text,parse_mode="Markdown",reply_markup=admin_menu())

    elif data.startswith("adminview:"):
        if update.effective_user.id not in ADMIN_IDS: return
        pid=int(data.split(":")[1]); con=db(); p=con.execute("SELECT id,name,price,description,photo FROM products WHERE id=?",(pid,)).fetchone(); con.close()
        if not p: await q.answer("Produk tidak ditemukan.",show_alert=True); return
        await safe_delete(q.message)
        text=f"👑 *Kelola Produk*\n\n🆔 ID: `{p[0]}`\n🛍️ {p[1]}\n💰 {p[2]}\n📝 {p[3] or '-'}"
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ HAPUS",callback_data=f"admindelete:{p[0]}"),InlineKeyboardButton("✏️ EDIT",callback_data=f"adminedithelp:{p[0]}")],[InlineKeyboardButton("⬅️ Daftar Produk",callback_data="adminlist")]])
        if p[4]: await context.bot.send_photo(update.effective_user.id,photo=p[4],caption=text,parse_mode="Markdown",reply_markup=kb)
        else: await context.bot.send_message(update.effective_user.id,text,parse_mode="Markdown",reply_markup=kb)

    elif data.startswith("admindelete:"):
        if update.effective_user.id not in ADMIN_IDS: return
        pid=int(data.split(":")[1]); con=db(); p=con.execute("SELECT name FROM products WHERE id=?",(pid,)).fetchone()
        if not p: con.close(); await q.answer("Produk tidak ditemukan.",show_alert=True); return
        con.execute("DELETE FROM products WHERE id=?",(pid,)); con.commit(); con.close(); await safe_delete(q.message)
        await context.bot.send_message(update.effective_user.id,f"🗑️ Produk *{p[0]}* berhasil dihapus.",parse_mode="Markdown",reply_markup=admin_menu())

    elif data.startswith("adminedithelp:"):
        if update.effective_user.id not in ADMIN_IDS: return
        pid=int(data.split(":")[1]); await safe_delete(q.message)
        await context.bot.send_message(update.effective_user.id,f"✏️ *Edit Produk #{pid}*\n\n`/edit {pid} | Nama Baru | Harga Baru | Deskripsi Baru`",parse_mode="Markdown",reply_markup=admin_menu())

    elif data.startswith("setstatus:"):
        if update.effective_user.id not in ADMIN_IDS: return
        _,status,oid_text=data.split(":"); oid=int(oid_text)
        con=db(); row=con.execute("SELECT o.user_id,p.name,p.price FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=?",(oid,)).fetchone()
        if not row: con.close(); await q.answer("Order tidak ditemukan.",show_alert=True); return
        con.execute("UPDATE orders SET status=? WHERE id=?",(status,oid)); con.commit(); con.close()
        user_id,product,price=row
        user_msg=f"📦 *Update Order*\n\n🆔 `ORD-{oid:05d}`\n📦 {product}\n💰 {price}\n📌 Status: *{STATUS_TEXT[status]}*"
        try: await context.bot.send_message(user_id,user_msg,parse_mode="Markdown")
        except Exception: logging.exception("User notification failed")
        await q.answer(f"Status: {STATUS_TEXT[status]}")
        try:
            if q.message.photo:
                await q.edit_message_caption(caption=f"{q.message.caption or ''}\n\n📌 STATUS: {STATUS_TEXT[status]}",reply_markup=admin_order_buttons(oid))
            else:
                await q.edit_message_text(f"{q.message.text or ''}\n\n📌 STATUS: {STATUS_TEXT[status]}",reply_markup=admin_order_buttons(oid))
        except Exception:
            pass

async def admin_add(update,context):
    if update.effective_user.id not in ADMIN_IDS: return
    raw=update.message.text.partition(" ")[2].strip(); parts=[x.strip() for x in raw.split("|")]
    if len(parts)<2: await update.message.reply_text("Format: /add Nama | Harga | Deskripsi"); return
    name,price=parts[0],parts[1]; desc=parts[2] if len(parts)>2 else ""
    con=db(); con.execute("INSERT INTO products(name,price,description) VALUES(?,?,?)",(name,price,desc)); con.commit(); con.close(); await update.message.reply_text(f"✅ Produk *{name}* berhasil ditambahkan.",parse_mode="Markdown")

async def admin_photo(update,context):
    uid=update.effective_user.id; caption=(update.message.caption or "").strip()
    if uid in ADMIN_IDS and caption.lower().startswith("/add"):
        parts=[x.strip() for x in caption.partition(" ")[2].strip().split("|")]
        if len(parts)<2: await update.message.reply_text("❌ Format: /add Nama | Harga | Deskripsi"); return
        name,price=parts[0],parts[1]; desc=parts[2] if len(parts)>2 else ""; photo_id=update.message.photo[-1].file_id
        con=db(); con.execute("INSERT INTO products(name,price,description,photo) VALUES(?,?,?,?)",(name,price,desc,photo_id)); con.commit(); con.close(); await update.message.reply_text(f"✅ Produk *{name}* + foto berhasil ditambahkan.",parse_mode="Markdown"); return

    match=re.search(r"ORD-(\d+)",caption.upper())
    if not match: await update.message.reply_text("📸 Caption bukti wajib berisi ID seperti `ORD-00001`.",parse_mode="Markdown"); return
    oid=int(match.group(1)); con=db(); row=con.execute("SELECT o.user_id,p.name,p.price FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=?",(oid,)).fetchone()
    if not row: con.close(); await update.message.reply_text("❌ ID transaksi tidak ditemukan."); return
    user_id,product,price=row
    if user_id!=uid: con.close(); await update.message.reply_text("❌ Order ini bukan milik kamu."); return
    con.execute("UPDATE orders SET status='proof_received' WHERE id=?",(oid,)); con.commit(); con.close()
    await update.message.reply_text(f"📸 Bukti `ORD-{oid:05d}` diterima. Tunggu admin.",parse_mode="Markdown")
    admin_text=f"🔔 *BUKTI PEMBAYARAN BARU*\n\n🆔 `ORD-{oid:05d}`\n👤 User ID: `{uid}`\n📦 {product}\n💰 {price}\n📌 Status: Bukti diterima"
    await notify_admins(context,admin_text,admin_order_buttons(oid),photo=update.message.photo[-1].file_id)

async def admin_products(update,context):
    if update.effective_user.id not in ADMIN_IDS: return
    await update.message.reply_text("👑 *Admin Panel*",parse_mode="Markdown",reply_markup=admin_menu())

async def admin_delete(update,context):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(context.args)!=1 or not context.args[0].isdigit(): await update.message.reply_text("Format: /delete ID_PRODUK"); return
    pid=int(context.args[0]); con=db(); row=con.execute("SELECT name FROM products WHERE id=?",(pid,)).fetchone()
    if not row: con.close(); await update.message.reply_text("❌ Produk tidak ditemukan."); return
    con.execute("DELETE FROM products WHERE id=?",(pid,)); con.commit(); con.close(); await update.message.reply_text(f"🗑️ Produk *{row[0]}* dihapus.",parse_mode="Markdown")

async def admin_edit(update,context):
    if update.effective_user.id not in ADMIN_IDS: return
    parts=[x.strip() for x in update.message.text.partition(" ")[2].strip().split("|")]
    if len(parts)<3 or not parts[0].isdigit(): await update.message.reply_text("Format: /edit ID | Nama | Harga | Deskripsi"); return
    pid=int(parts[0]); name=parts[1]; price=parts[2]; desc=parts[3] if len(parts)>3 else ""
    con=db(); cur=con.execute("UPDATE products SET name=?,price=?,description=? WHERE id=?",(name,price,desc,pid)); con.commit(); con.close(); await update.message.reply_text("✏️ Produk berhasil diedit." if cur.rowcount else "❌ Produk tidak ditemukan.")

async def admin_setpayment(update,context):
    if update.effective_user.id not in ADMIN_IDS: return
    value=update.message.text.partition(" ")[2].strip()
    if not value: await update.message.reply_text("Format: /setpayment QRIS: xxx | DANA: xxx | Bank: xxx"); return
    set_payment(value); await update.message.reply_text("✅ Info pembayaran berhasil disimpan.")

async def adminpanel(update,context):
    if update.effective_user.id not in ADMIN_IDS: return
    await update.message.reply_text("👑 *Admin Panel*",parse_mode="Markdown",reply_markup=admin_menu())

def main():
    if not TOKEN: raise RuntimeError("BOT_TOKEN belum diisi.")
    db(); app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("add",admin_add)); app.add_handler(CommandHandler("products",admin_products)); app.add_handler(CommandHandler("delete",admin_delete)); app.add_handler(CommandHandler("edit",admin_edit)); app.add_handler(CommandHandler("setpayment",admin_setpayment)); app.add_handler(CommandHandler("admin",adminpanel))
    app.add_handler(MessageHandler(filters.PHOTO,admin_photo)); app.add_handler(CallbackQueryHandler(callback)); app.run_polling()

if __name__=="__main__": main()
