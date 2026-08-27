import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    MessageHandler, filters
)

TOKEN = os.getenv("BOT_TOKEN", "")
REQUIRED_CHAT = os.getenv("REQUIRED_CHAT", "")  # contoh: @namagrup
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
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
        status TEXT DEFAULT 'pending'
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

async def is_joined(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not REQUIRED_CHAT:
        return True
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHAT, update.effective_user.id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_joined(update, context):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 JOIN GRUP", url=f"https://t.me/{REQUIRED_CHAT.lstrip('@')}")],
            [InlineKeyboardButton("✅ SUDAH JOIN", callback_data="check_join")]
        ])
        await update.message.reply_text(
            "🔒 *Akses dikunci*\n\nSilakan join grup wajib terlebih dahulu, lalu tekan **SUDAH JOIN**.",
            parse_mode="Markdown", reply_markup=kb
        )
        return
    await update.message.reply_text("🔥 *Selamat datang di Store!*\nPilih menu di bawah.", parse_mode="Markdown", reply_markup=menu())

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    if q.data == "catalog":
        con = db()
        products = con.execute("SELECT id,name,price,description,photo FROM products").fetchall()
        con.close()
        if not products:
            await q.edit_message_text("📭 Katalog masih kosong.", reply_markup=menu())
            return
        buttons = [[InlineKeyboardButton(f"{p[1]} • {p[2]}", callback_data=f"product:{p[0]}")] for p in products]
        buttons.append([InlineKeyboardButton("⬅️ Kembali", callback_data="home")])
        await q.edit_message_text("🛒 *Katalog Produk*", parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(buttons))

    elif q.data.startswith("product:"):
        pid = int(q.data.split(":")[1])
        con = db()
        p = con.execute("SELECT id,name,price,description,photo FROM products WHERE id=?", (pid,)).fetchone()
        con.close()
        if not p:
            await q.answer("Produk tidak ditemukan.", show_alert=True)
            return
        text = f"🛍️ *{p[1]}*\n💰 Harga: `{p[2]}`\n\n{p[3]}"
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
        cur = con.execute("INSERT INTO orders(user_id,product_id) VALUES(?,?)",
                          (update.effective_user.id, pid))
        oid = cur.lastrowid
        con.commit()
        con.close()
        await q.edit_message_text(
            f"✅ *Order dibuat!*\n\n🆔 ID Transaksi: `ORD-{oid:05d}`\n📦 Produk: {p[1]}\n💰 Harga: {p[2]}\n\n"
            "Silakan lakukan pembayaran sesuai info pembayaran, lalu kirim bukti ke admin.",
            parse_mode="Markdown", reply_markup=menu()
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
            text = "📦 *Pesanan Saya*\n\n" + "\n".join(
                f"🆔 ORD-{r[0]:05d}\n📦 {r[1]}\n💰 {r[2]}\n📌 {r[3]}\n"
                for r in rows
            )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=menu())

    elif q.data == "payment":
        await q.edit_message_text(
            "💳 *Pembayaran*\n\nAtur info pembayaran kamu di variabel PAYMENT_INFO pada versi berikutnya.",
            parse_mode="Markdown", reply_markup=menu()
        )

    elif q.data == "support":
        await q.edit_message_text(
            "👨‍💻 *Contact Admin*\n\nHubungi admin toko untuk bantuan.",
            parse_mode="Markdown", reply_markup=menu()
        )

    elif q.data == "home":
        await q.edit_message_text("🔥 *Menu Utama*", parse_mode="Markdown", reply_markup=menu())

async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Format: /add NamaProduk | Harga | Deskripsi | PhotoFileID")
        return
    parts = " ".join(context.args).split("|")
    name = parts[0].strip()
    price = parts[1].strip()
    desc = parts[2].strip() if len(parts) > 2 else ""
    photo = parts[3].strip() if len(parts) > 3 else ""
    con = db()
    con.execute("INSERT INTO products(name,price,description,photo) VALUES(?,?,?,?)",
                (name, price, desc, photo))
    con.commit()
    con.close()
    await update.message.reply_text("✅ Produk berhasil ditambahkan.")

async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    con = db()
    rows = con.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall()
    con.close()
    await update.message.reply_text(
        "🛒 Produk:\n" + ("\n".join(f"#{r[0]} {r[1]} — {r[2]}" for r in rows) if rows else "Kosong.")
    )

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN belum diisi.")
    db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", admin_add))
    app.add_handler(CommandHandler("products", admin_products))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()

if __name__ == "__main__":
    main()
