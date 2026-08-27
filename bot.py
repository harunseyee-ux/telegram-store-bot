import os, sqlite3, logging, re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

TOKEN = os.getenv("BOT_TOKEN", "")
REQUIRED_CHAT = os.getenv("REQUIRED_CHAT", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
PAYMENT_INFO = os.getenv("PAYMENT_INFO", "Hubungi admin untuk info pembayaran.")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")
DB = "store.db"

logging.basicConfig(level=logging.INFO)

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
    con.commit()
    return con

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Katalog", callback_data="catalog")],
        [InlineKeyboardButton("📦 Pesanan Saya", callback_data="orders")],
        [InlineKeyboardButton("💳 Pembayaran", callback_data="payment")],
        [InlineKeyboardButton("👨‍💻 Contact Admin", callback_data="support")]
    ])

def order_keyboard(oid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 INFO PEMBAYARAN", callback_data=f"payorder:{oid}")],
        [InlineKeyboardButton("📤 CARA KIRIM BUKTI", callback_data=f"proofhelp:{oid}")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="home")]
    ])

async def is_joined(update, context):
    if not REQUIRED_CHAT:
        return True
    try:
        m = await context.bot.get_chat_member(REQUIRED_CHAT, update.effective_user.id)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False

async def start(update, context):
    if not await is_joined(update, context):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 JOIN GRUP", url=f"https://t.me/{REQUIRED_CHAT.lstrip('@')}")],
            [InlineKeyboardButton("✅ SUDAH JOIN", callback_data="check_join")]
        ])
        await update.message.reply_text(
            "🔒 *Akses dikunci*\n\nJoin grup wajib terlebih dahulu, lalu tekan *SUDAH JOIN*.",
            parse_mode="Markdown", reply_markup=kb
        )
        return
    await update.message.reply_text(
        "🔥 *Selamat datang di Store!*\nPilih menu di bawah.",
        parse_mode="Markdown", reply_markup=menu()
    )

async def callback(update, context):
    q = update.callback_query
    await q.answer()

    if q.data == "check_join":
        if await is_joined(update, context):
            await q.edit_message_text("✅ Verifikasi berhasil!\n\nSelamat datang di Store 🔥", reply_markup=menu())
        else:
            await q.answer("❌ Kamu belum join grup!", show_alert=True)
        return

    if not await is_joined(update, context):
        await q.answer("❌ Join grup wajib dulu.", show_alert=True)
        return

    if q.data == "home":
        await q.edit_message_text("🔥 *Menu Utama*", parse_mode="Markdown", reply_markup=menu())

    elif q.data == "catalog":
        con = db()
        rows = con.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall()
        con.close()
        if not rows:
            await q.edit_message_text("📭 Katalog masih kosong.", reply_markup=menu())
            return
        kb = [[InlineKeyboardButton(f"🛍️ {r[1]} • {r[2]}", callback_data=f"product:{r[0]}")] for r in rows]
        kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data="home")])
        await q.edit_message_text("🛒 *Katalog Produk*", parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("product:"):
        pid = int(q.data.split(":")[1])
        con = db()
        p = con.execute("SELECT id,name,price,description,photo FROM products WHERE id=?", (pid,)).fetchone()
        con.close()
        if not p:
            await q.answer("Produk tidak ditemukan.", show_alert=True)
            return
        text = f"🛍️ *{p[1]}*\n💰 Harga: `{p[2]}`\n\n{p[3] or 'Tidak ada deskripsi.'}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 BELI", callback_data=f"buy:{p[0]}")],
            [InlineKeyboardButton("⬅️ Katalog", callback_data="catalog")]
        ])
        if p[4]:
            try:
                await q.message.reply_photo(photo=p[4], caption=text, parse_mode="Markdown", reply_markup=kb)
                await q.message.delete()
            except Exception:
                await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        else:
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

    elif q.data.startswith("buy:"):
        pid = int(q.data.split(":")[1])
        con = db()
        p = con.execute("SELECT id,name,price FROM products WHERE id=?", (pid,)).fetchone()
        if not p:
            con.close()
            await q.answer("Produk tidak ditemukan.", show_alert=True)
            return
        cur = con.execute(
            "INSERT INTO orders(user_id,product_id,status) VALUES(?,?,?)",
            (update.effective_user.id, pid, "pending_payment")
        )
        oid = cur.lastrowid
        con.commit()
        con.close()

        text = (
            f"🧾 *ORDER BERHASIL DIBUAT*\n\n"
            f"🆔 ID Transaksi: `ORD-{oid:05d}`\n"
            f"📦 Produk: {p[1]}\n"
            f"💰 Harga: {p[2]}\n"
            f"📌 Status: Menunggu pembayaran\n\n"
            f"💳 *Pembayaran:*\n{PAYMENT_INFO}\n\n"
            "Setelah bayar, kirim *foto bukti pembayaran* ke chat bot ini.\n"
            f"Tulis `ORD-{oid:05d}` di caption foto."
        )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=order_keyboard(oid))

    elif q.data.startswith("payorder:"):
        oid = int(q.data.split(":")[1])
        await q.edit_message_text(
            f"💳 *Pembayaran Order ORD-{oid:05d}*\n\n{PAYMENT_INFO}\n\n"
            "Setelah transfer, kirim foto bukti + caption `ORD-%05d`." % oid,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="home")]])
        )

    elif q.data.startswith("proofhelp:"):
        oid = int(q.data.split(":")[1])
        await q.edit_message_text(
            f"📤 *Cara Kirim Bukti*\n\n"
            f"1. Bayar sesuai info pembayaran.\n"
            f"2. Kirim foto bukti pembayaran di chat bot.\n"
            f"3. Caption foto harus berisi `ORD-{oid:05d}`.\n"
            "4. Admin akan mengecek dan mengonfirmasi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="home")]])
        )

    elif q.data == "orders":
        con = db()
        rows = con.execute("""
            SELECT o.id,p.name,p.price,o.status FROM orders o
            JOIN products p ON p.id=o.product_id
            WHERE o.user_id=? ORDER BY o.id DESC
        """, (update.effective_user.id,)).fetchall()
        con.close()
        if not rows:
            text = "📦 Belum ada pesanan."
        else:
            status_map = {
                "pending_payment": "Menunggu pembayaran",
                "proof_received": "Bukti diterima",
                "paid": "Pembayaran dikonfirmasi",
                "rejected": "Bukti ditolak"
            }
            text = "📦 *Pesanan Saya*\n\n" + "\n".join(
                f"🆔 ORD-{r[0]:05d}\n📦 {r[1]}\n💰 {r[2]}\n📌 {status_map.get(r[3], r[3])}\n"
                for r in rows
            )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=menu())

    elif q.data == "payment":
        await q.edit_message_text(f"💳 *Pembayaran*\n\n{PAYMENT_INFO}",
                                  parse_mode="Markdown", reply_markup=menu())

    elif q.data == "support":
        target = SUPPORT_USERNAME if SUPPORT_USERNAME else "Silakan hubungi admin toko."
        await q.edit_message_text(f"👨‍💻 *Contact Admin*\n\n{target}",
                                  parse_mode="Markdown", reply_markup=menu())

    elif q.data.startswith("adminview:"):
        if update.effective_user.id not in ADMIN_IDS:
            await q.answer("❌ Kamu bukan admin.", show_alert=True)
            return
        pid=int(q.data.split(":")[1])
        con=db()
        p=con.execute("SELECT id,name,price,description,photo FROM products WHERE id=?",(pid,)).fetchone()
        con.close()
        if not p:
            await q.answer("Produk tidak ditemukan.", show_alert=True)
            return
        text=f"👑 *Kelola Produk*\n\n🆔 ID: `{p[0]}`\n🛍️ {p[1]}\n💰 {p[2]}\n📝 {p[3] or '-'}"
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ HAPUS",callback_data=f"admindelete:{p[0]}"),
             InlineKeyboardButton("✏️ EDIT",callback_data=f"adminedithelp:{p[0]}")],
            [InlineKeyboardButton("⬅️ Daftar Produk",callback_data="adminlist")]
        ])
        if p[4]:
            try:
                await q.message.reply_photo(photo=p[4],caption=text,parse_mode="Markdown",reply_markup=kb)
                await q.message.delete()
            except Exception:
                await q.edit_message_text(text,parse_mode="Markdown",reply_markup=kb)
        else:
            await q.edit_message_text(text,parse_mode="Markdown",reply_markup=kb)

    elif q.data.startswith("admindelete:"):
        if update.effective_user.id not in ADMIN_IDS:
            await q.answer("❌ Kamu bukan admin.", show_alert=True)
            return
        pid=int(q.data.split(":")[1])
        con=db()
        p=con.execute("SELECT name FROM products WHERE id=?",(pid,)).fetchone()
        if not p:
            con.close()
            await q.answer("Produk tidak ditemukan.",show_alert=True)
            return
        con.execute("DELETE FROM products WHERE id=?",(pid,))
        con.commit(); con.close()
        await q.edit_message_text(f"🗑️ Produk *{p[0]}* berhasil dihapus.",parse_mode="Markdown")

    elif q.data.startswith("adminedithelp:"):
        if update.effective_user.id not in ADMIN_IDS:
            await q.answer("❌ Kamu bukan admin.", show_alert=True)
            return
        pid=int(q.data.split(":")[1])
        await q.edit_message_text(
            f"✏️ *Edit Produk #{pid}*\n\n"
            f"Kirim perintah:\n"
            f"`/edit {pid} | Nama Baru | Harga Baru | Deskripsi Baru`",
            parse_mode="Markdown"
        )

    elif q.data=="adminlist":
        if update.effective_user.id not in ADMIN_IDS:
            await q.answer("❌ Kamu bukan admin.", show_alert=True)
            return
        con=db()
        rows=con.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall()
        con.close()
        if not rows:
            await q.edit_message_text("🛒 Katalog kosong.")
            return
        buttons=[[InlineKeyboardButton(f"🛍️ {n} • {p}",callback_data=f"adminview:{pid}")]
                 for pid,n,p in rows]
        await q.edit_message_text(
            "👑 *Kelola Produk*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif q.data.startswith("approve:") or q.data.startswith("reject:"):
        if update.effective_user.id not in ADMIN_IDS:
            await q.answer("❌ Kamu bukan admin.", show_alert=True)
            return

        action, oid_text = q.data.split(":")
        oid = int(oid_text)
        new_status = "paid" if action == "approve" else "rejected"

        con = db()
        row = con.execute("""
            SELECT o.user_id,p.name,p.price,o.status
            FROM orders o JOIN products p ON p.id=o.product_id
            WHERE o.id=?
        """, (oid,)).fetchone()
        con.execute("UPDATE orders SET status=? WHERE id=?", (new_status, oid))
        con.commit()
        con.close()

        if not row:
            await q.edit_message_caption(caption="❌ Order tidak ditemukan.")
            return

        user_id, product, price, old_status = row
        if action == "approve":
            msg = f"✅ *Pembayaran dikonfirmasi!*\n\n🆔 `ORD-{oid:05d}`\n📦 {product}\n💰 {price}\n\nAdmin akan memproses pesanan kamu."
            admin_text = f"✅ Order ORD-{oid:05d} dikonfirmasi oleh admin."
        else:
            msg = f"❌ *Bukti pembayaran ditolak.*\n\n🆔 `ORD-{oid:05d}`\n📦 {product}\n\nSilakan hubungi admin atau kirim bukti pembayaran yang benar."
            admin_text = f"❌ Order ORD-{oid:05d} ditolak oleh admin."

        try:
            await context.bot.send_message(user_id, msg, parse_mode="Markdown")
        except Exception:
            pass

        try:
            if q.message.photo:
                await q.edit_message_caption(caption=admin_text)
            else:
                await q.edit_message_text(admin_text)
        except Exception:
            pass

async def admin_add(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    raw = update.message.text.partition(" ")[2].strip()
    parts = [x.strip() for x in raw.split("|")]
    if len(parts) < 2:
        await update.message.reply_text(
            "Format:\n/add Nama Produk | Harga | Deskripsi\n\n"
            "Atau kirim FOTO dengan caption:\n/add Nama Produk | Harga | Deskripsi"
        )
        return
    name, price = parts[0], parts[1]
    desc = parts[2] if len(parts) > 2 else ""
    con = db()
    con.execute("INSERT INTO products(name,price,description) VALUES(?,?,?)", (name,price,desc))
    con.commit()
    con.close()
    await update.message.reply_text(f"✅ Produk *{name}* berhasil ditambahkan.", parse_mode="Markdown")

async def admin_photo(update, context):
    uid = update.effective_user.id

    # Admin tambah produk dengan foto
    if uid in ADMIN_IDS:
        caption = (update.message.caption or "").strip()
        if caption.lower().startswith("/add"):
            raw = caption.partition(" ")[2].strip()
            parts = [x.strip() for x in raw.split("|")]
            if len(parts) < 2:
                await update.message.reply_text("❌ Format: /add Nama Produk | Harga | Deskripsi")
                return
            name, price = parts[0], parts[1]
            desc = parts[2] if len(parts) > 2 else ""
            photo_id = update.message.photo[-1].file_id
            con = db()
            con.execute("INSERT INTO products(name,price,description,photo) VALUES(?,?,?,?)",
                        (name,price,desc,photo_id))
            con.commit()
            con.close()
            await update.message.reply_text(
                f"✅ Produk *{name}* + foto berhasil ditambahkan ke katalog.",
                parse_mode="Markdown"
            )
            return

    # Bukti pembayaran dari user
    caption = (update.message.caption or "").upper()
    match = re.search(r"ORD-(\d+)", caption)
    if not match:
        await update.message.reply_text(
            "📸 Bukti diterima belum bisa dicocokkan.\n"
            "Pastikan caption foto berisi ID transaksi, contoh: `ORD-00001`.",
            parse_mode="Markdown"
        )
        return

    oid = int(match.group(1))
    con = db()
    row = con.execute("""
        SELECT o.user_id,p.name,p.price,o.status
        FROM orders o JOIN products p ON p.id=o.product_id
        WHERE o.id=?
    """, (oid,)).fetchone()

    if not row:
        con.close()
        await update.message.reply_text("❌ ID transaksi tidak ditemukan.")
        return

    user_id, product, price, status = row
    if user_id != uid:
        con.close()
        await update.message.reply_text("❌ Order ini bukan milik kamu.")
        return

    con.execute("UPDATE orders SET status='proof_received' WHERE id=?", (oid,))
    con.commit()
    con.close()

    await update.message.reply_text(
        f"📸 Bukti pembayaran untuk `ORD-{oid:05d}` sudah diterima.\n"
        "⏳ Tunggu admin melakukan pengecekan.",
        parse_mode="Markdown"
    )

    admin_caption = (
        f"🔔 *BUKTI PEMBAYARAN BARU*\n\n"
        f"🆔 `ORD-{oid:05d}`\n"
        f"👤 User ID: `{uid}`\n"
        f"📦 {product}\n"
        f"💰 {price}\n"
        "📌 Status: Bukti diterima"
    )
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ KONFIRMASI", callback_data=f"approve:{oid}"),
        InlineKeyboardButton("❌ TOLAK", callback_data=f"reject:{oid}")
    ]])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=update.message.photo[-1].file_id,
                caption=admin_caption,
                parse_mode="Markdown",
                reply_markup=buttons
            )
        except Exception:
            logging.exception("Gagal mengirim bukti ke admin %s", admin_id)

async def admin_products(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    con=db()
    rows=con.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("🛒 Katalog masih kosong.")
        return

    buttons=[]
    for pid,name,price in rows:
        buttons.append([InlineKeyboardButton(
            f"🛍️ {name} • {price}", callback_data=f"adminview:{pid}"
        )])
    await update.message.reply_text(
        "👑 *Kelola Produk*\n\nPilih produk yang mau diedit atau dihapus:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def admin_delete(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Format: /delete ID_PRODUK")
        return
    pid=int(context.args[0])
    con=db()
    row=con.execute("SELECT name FROM products WHERE id=?",(pid,)).fetchone()
    if not row:
        con.close()
        await update.message.reply_text("❌ Produk tidak ditemukan.")
        return
    con.execute("DELETE FROM products WHERE id=?",(pid,))
    con.commit()
    con.close()
    await update.message.reply_text(f"🗑️ Produk *{row[0]}* berhasil dihapus.",parse_mode="Markdown")

async def admin_edit(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    raw=update.message.text.partition(" ")[2].strip()
    parts=[x.strip() for x in raw.split("|")]
    if len(parts)<3 or not parts[0].isdigit():
        await update.message.reply_text(
            "Format:\n/edit ID | Nama Baru | Harga Baru | Deskripsi Baru"
        )
        return
    pid=int(parts[0]); name=parts[1]; price=parts[2]; desc=parts[3] if len(parts)>3 else ""
    con=db()
    cur=con.execute(
        "UPDATE products SET name=?,price=?,description=? WHERE id=?",
        (name,price,desc,pid)
    )
    con.commit(); con.close()
    if cur.rowcount:
        await update.message.reply_text("✏️ Produk berhasil diedit.")
    else:
        await update.message.reply_text("❌ Produk tidak ditemukan.")

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN belum diisi.")
    db()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("add",admin_add))
    app.add_handler(CommandHandler("products",admin_products))
    app.add_handler(CommandHandler("delete",admin_delete))
    app.add_handler(CommandHandler("edit",admin_edit))
    app.add_handler(MessageHandler(filters.PHOTO,admin_photo))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()

if __name__=="__main__":
    main()
