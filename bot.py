import os
import re
import logging
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Configuration
TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
REQUIRED_CHAT = os.getenv("REQUIRED_CHAT", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID", "").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")
DEFAULT_PAYMENT = os.getenv("PAYMENT_INFO", "Hubungi admin untuk info pembayaran.")

logging.basicConfig(level=logging.INFO)
pool: asyncpg.Pool = None

STATUS_TEXT = {
    "pending_payment": "Menunggu Pembayaran",
    "proof_received": "Bukti Diterima",
    "processing": "Sedang Diproses",
    "paid": "Pembayaran Dikonfirmasi",
    "rejected": "Ditolak",
    "completed": "Selesai",
}

# Database Initialization
async def init_db(app):
    global pool
    dsn = DATABASE_URL.replace("postgres://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                price TEXT NOT NULL,
                stock INT DEFAULT -1,
                description TEXT DEFAULT '',
                photo TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                product_id INT REFERENCES products(id) ON DELETE CASCADE,
                status TEXT DEFAULT 'pending_payment',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT ''
            );
        """)

async def get_payment_info() -> str:
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT value FROM settings WHERE key='payment_info'")
        return val if val else DEFAULT_PAYMENT

# Helpers & Keyboards
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Katalog", callback_data="catalog")],
        [InlineKeyboardButton("📦 Pesanan Saya", callback_data="orders")],
        [InlineKeyboardButton("💳 Pembayaran", callback_data="payment")],
        [InlineKeyboardButton("👨‍💻 Contact Admin", callback_data="support")]
    ])

def admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Kelola Produk", callback_data="admin_list")],
        [InlineKeyboardButton("📦 Kelola Pesanan", callback_data="admin_orders")],
        [InlineKeyboardButton("📊 Statistik", callback_data="admin_stats")],
        [InlineKeyboardButton("💳 Payment Info", callback_data="admin_payment")]
    ])

def admin_order_buttons(order_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ PROSES", callback_data=f"setstatus:processing:{order_id}")],
        [InlineKeyboardButton("✅ APPROVED", callback_data=f"setstatus:paid:{order_id}"),
         InlineKeyboardButton("❌ REJECTED", callback_data=f"setstatus:rejected:{order_id}")],
        [InlineKeyboardButton("🏁 SELESAI", callback_data=f"setstatus:completed:{order_id}")]
    ])

async def is_joined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not REQUIRED_CHAT:
        return True
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHAT, update.effective_user.id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

# Handlers
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users(user_id, username) VALUES($1, $2) ON CONFLICT(user_id) DO UPDATE SET username=$2",
            user.id, user.username or ""
        )

    if not await is_joined(update, context):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 JOIN GRUP", url=f"https://t.me/{REQUIRED_CHAT.lstrip('@')}")],
            [InlineKeyboardButton("✅ SUDAH JOIN", callback_data="check_join")]
        ])
        await update.message.reply_text("🔒 *Akses Ditingkatkan*\n\nWajib join grup terlebih dahulu!", parse_mode="Markdown", reply_markup=kb)
        return

    await update.message.reply_text("🔥 *Selamat datang di Store!*", parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    user_id = update.effective_user.id

    if data == "check_join":
        if await is_joined(update, context):
            await q.message.delete()
            await context.bot.send_message(user_id, "✅ *Verifikasi Berhasil!*", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        else:
            await q.answer("❌ Kamu belum join!", show_alert=True)
        return

    if not await is_joined(update, context):
        await q.answer("❌ Wajib join grup dulu.", show_alert=True)
        return

    if data == "home":
        await q.message.delete()
        await context.bot.send_message(user_id, "🔥 *Menu Utama*", parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif data == "catalog":
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, price, stock FROM products ORDER BY id DESC")
        await q.message.delete()
        if not rows:
            await context.bot.send_message(user_id, "📭 Katalog masih kosong.", reply_markup=main_menu_keyboard())
            return
        
        kb = []
        for r in rows:
            stk_str = "∞" if r['stock'] < 0 else str(r['stock'])
            kb.append([InlineKeyboardButton(f"🛍️ {r['name']} • {r['price']} (Stok: {stk_str})", callback_data=f"product:{r['id']}")])
        kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data="home")])
        await context.bot.send_message(user_id, "🛒 *Katalog Produk*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("product:"):
        pid = int(data.split(":")[1])
        async with pool.acquire() as conn:
            p = await conn.fetchrow("SELECT * FROM products WHERE id=$1", pid)
        if not p:
            await q.answer("Produk tidak ditemukan.", show_alert=True)
            return
        await q.message.delete()
        stk_str = "Unlimited" if p['stock'] < 0 else f"{p['stock']} Pcs"
        text = f"🛍️ *{p['name']}*\n💰 Harga: `{p['price']}`\n📦 Stok: `{stk_str}`\n\n📝 Deskripsi:\n{p['description'] or '-'}"
        
        kb_btn = []
        if p['stock'] != 0:
            kb_btn.append([InlineKeyboardButton("🛒 BELI", callback_data=f"buy:{p['id']}")])
        kb_btn.append([InlineKeyboardButton("⬅️ Katalog", callback_data="catalog")])

        if p['photo']:
            await context.bot.send_photo(user_id, photo=p['photo'], caption=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_btn))
        else:
            await context.bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_btn))

    elif data.startswith("buy:"):
        pid = int(data.split(":")[1])
        async with pool.acquire() as conn:
            p = await conn.fetchrow("SELECT name, price, stock FROM products WHERE id=$1", pid)
            if not p:
                await q.answer("Produk tidak ditemukan.", show_alert=True)
                return
            if p['stock'] == 0:
                await q.answer("Maaf, stok produk ini habis!", show_alert=True)
                return
            
            # Kurangi stok jika bukan unlimited (-1)
            if p['stock'] > 0:
                await conn.execute("UPDATE products SET stock = stock - 1 WHERE id=$1", pid)

            oid = await conn.fetchval("INSERT INTO orders(user_id, product_id, status) VALUES($1, $2, 'pending_payment') RETURNING id", user_id, pid)

        await q.message.delete()
        pay_info = await get_payment_info()
        text = (f"🧾 *ORDER BERHASIL DIBUAT*\n\n🆔 ID Transaksi: `ORD-{oid:05d}`\n📦 Produk: {p['name']}\n💰 Harga: {p['price']}\n\n"
                f"💳 *Info Pembayaran:*\n{pay_info}\n\nKirim foto bukti pembayaran ke bot ini dengan caption `ORD-{oid:05d}`.")
        await context.bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif data == "orders":
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT o.id, p.name, p.price, o.status 
                FROM orders o JOIN products p ON p.id=o.product_id 
                WHERE o.user_id=$1 ORDER BY o.id DESC LIMIT 15
            """, user_id)
        await q.message.delete()
        text = "📦 Belum ada pesanan." if not rows else "📦 *Pesanan Saya*\n\n" + "\n".join(
            f"🆔 `ORD-{r['id']:05d}` | {r['name']}\n💰 {r['price']} | Status: *{STATUS_TEXT.get(r['status'], r['status'])}*\n" for r in rows
        )
        await context.bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif data == "payment":
        pay_info = await get_payment_info()
        await q.message.delete()
        await context.bot.send_message(user_id, f"💳 *Info Pembayaran*\n\n{pay_info}", parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif data == "support":
        await q.message.delete()
        await context.bot.send_message(user_id, f"👨‍💻 Contact Admin: @{SUPPORT_USERNAME.lstrip('@') or 'Admin'}", reply_markup=main_menu_keyboard())

    # Admin Callback Handlers
    elif data == "admin_stats" and user_id in ADMIN_IDS:
        async with pool.acquire() as conn:
            tot_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            tot_orders = await conn.fetchval("SELECT COUNT(*) FROM orders")
            tot_paid = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status IN ('paid', 'completed')")
            tot_products = await conn.fetchval("SELECT COUNT(*) FROM products")
        
        text = (f"📊 *STATISTIK TOKO*\n\n"
                f"👤 Total Pengguna: `{tot_users}`\n"
                f"🛍️ Total Produk: `{tot_products}`\n"
                f"📦 Total Transaksi: `{tot_orders}`\n"
                f"✅ Transaksi Sukses: `{tot_paid}`")
        await q.message.delete()
        await context.bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=admin_menu_keyboard())

    elif data.startswith("setstatus:") and user_id in ADMIN_IDS:
        _, status, oid_str = data.split(":")
        oid = int(oid_str)
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT o.user_id, p.name FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=$1", oid)
            if row:
                await conn.execute("UPDATE orders SET status=$1 WHERE id=$2", status, oid)
                try:
                    await context.bot.send_message(row['user_id'], f"📦 Update Status `ORD-{oid:05d}`\n📌 Status: *{STATUS_TEXT[status]}*", parse_mode="Markdown")
                except Exception:
                    pass
        await q.answer(f"Status diubah: {STATUS_TEXT[status]}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    caption = (update.message.caption or "").strip()

    # Admin tambah produk bergambar (/add Nama | Harga | Stok | Deskripsi)
    if uid in ADMIN_IDS and caption.lower().startswith("/add"):
        parts = [x.strip() for x in caption.partition(" ")[2].split("|")]
        if len(parts) >= 2:
            name, price = parts[0], parts[1]
            stk = -1 if len(parts) < 3 or not parts[2].isdigit() else int(parts[2])
            desc = parts[3] if len(parts) > 3 else ""
            photo_id = update.message.photo[-1].file_id
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO products(name, price, stock, description, photo) VALUES($1,$2,$3,$4,$5)", name, price, stk, desc, photo_id)
            await update.message.reply_text(f"✅ Produk *{name}* + foto berhasil ditambahkan.", parse_mode="Markdown")
            return

    match = re.search(r"ORD-(\d+)", caption.upper())
    if not match:
        await update.message.reply_text("📸 Caption foto wajib menyertakan ID transaksi, contoh: `ORD-00001`", parse_mode="Markdown")
        return

    oid = int(match.group(1))
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT o.user_id, p.name, p.price FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=$1", oid)
        if not row or row['user_id'] != uid:
            await update.message.reply_text("❌ Pesanan tidak ditemukan atau bukan milikmu.")
            return
        await conn.execute("UPDATE orders SET status='proof_received' WHERE id=$1", oid)

    await update.message.reply_text(f"📸 Bukti `ORD-{oid:05d}` terkirim. Menunggu verifikasi admin.", parse_mode="Markdown")
    
    admin_msg = f"🔔 *BUKTI PEMBAYARAN BARU*\n\n🆔 `ORD-{oid:05d}`\n👤 User: `{uid}`\n📦 {row['name']}\n💰 {row['price']}"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(admin_id, photo=update.message.photo[-1].file_id, caption=admin_msg, parse_mode="Markdown", reply_markup=admin_order_buttons(oid))
        except Exception:
            pass

# Commands Admin Baru
async def add_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    raw = update.message.text.partition(" ")[2].strip()
    parts = [x.strip() for x in raw.split("|")]
    if len(parts) < 2:
        await update.message.reply_text("Format: `/add Nama | Harga | Stok | Deskripsi`\n*(Stok isi -1 untuk unlimited)*", parse_mode="Markdown")
        return
    name, price = parts[0], parts[1]
    stk = -1 if len(parts) < 3 or not parts[2].lstrip('-').isdigit() else int(parts[2])
    desc = parts[3] if len(parts) > 3 else ""
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO products(name, price, stock, description) VALUES($1, $2, $3, $4)", name, price, stk, desc)
    await update.message.reply_text(f"✅ Produk *{name}* berhasil ditambahkan.", parse_mode="Markdown")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    msg = update.message.text.partition(" ")[2].strip()
    if not msg:
        await update.message.reply_text("Format: `/bc Pesan Pengumuman`", parse_mode="Markdown")
        return

    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    
    success, fail = 0, 0
    for u in users:
        try:
            await context.bot.send_message(u['user_id'], f"📢 *PENGUMUMAN*\n\n{msg}", parse_mode="Markdown")
            success += 1
        except Exception:
            fail += 1

    await update.message.reply_text(f"🚀 *Broadcast Selesai*\n✅ Berhasil: {success}\n❌ Gagal: {fail}", parse_mode="Markdown")

async def cek_order_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.partition(" ")[2].strip()
    match = re.search(r"(\d+)", raw)
    if not match:
        await update.message.reply_text("Format: `/cek ORD-00001`", parse_mode="Markdown")
        return
    oid = int(match.group(1))
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT o.id, o.user_id, p.name, p.price, o.status, o.created_at 
            FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=$1
        """, oid)

    if not row:
        await update.message.reply_text("❌ Pesanan tidak ditemukan.")
        return

    text = (f"🔍 *DETAIL PESANAN*\n\n🆔 `ORD-{row['id']:05d}`\n👤 User ID: `{row['user_id']}`\n"
            f"📦 Produk: {row['name']}\n💰 Harga: {row['price']}\n📌 Status: *{STATUS_TEXT.get(row['status'], row['status'])}*")
    await update.message.reply_text(text, parse_mode="Markdown")

def main():
    if not TOKEN or not DATABASE_URL:
        raise RuntimeError("BOT_TOKEN dan DATABASE_URL wajib diisi di Variables Railway!")
    
    app = ApplicationBuilder().token(TOKEN).post_init(init_db).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("add", add_product_cmd))
    app.add_handler(CommandHandler("bc", broadcast_cmd))
    app.add_handler(CommandHandler("cek", cek_order_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
