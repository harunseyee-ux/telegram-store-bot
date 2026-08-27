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

    con.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price TEXT NOT NULL,
            description TEXT DEFAULT '',
            photo TEXT DEFAULT '',
            stock INTEGER DEFAULT -1
        )
    """)

    try:
        con.execute("ALTER TABLE products ADD COLUMN stock INTEGER DEFAULT -1")
    except Exception:
        pass

    con.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            status TEXT DEFAULT 'pending_payment',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)

    # V2: keranjang
    con.execute("""
        CREATE TABLE IF NOT EXISTS cart(
            user_id INTEGER,
            product_id INTEGER,
            qty INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(user_id, product_id)
        )
    """)

    # V2: item-item dalam satu order
    con.execute("""
        CREATE TABLE IF NOT EXISTS order_items(
            order_id INTEGER,
            product_id INTEGER,
            qty INTEGER NOT NULL,
            price TEXT,
            name TEXT
        )
    """)

    con.commit()
    return con


def get_payment():
    con = db()
    row = con.execute(
        "SELECT value FROM settings WHERE key='payment_info'"
    ).fetchone()
    con.close()

    return row[0] if row and row[0] else PAYMENT_INFO


def set_payment(value):
    con = db()
    con.execute("""
        INSERT INTO settings(key,value)
        VALUES('payment_info',?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (value,))
    con.commit()
    con.close()


def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛒 Katalog", callback_data="catalog"),
            InlineKeyboardButton("🔎 Cari", callback_data="search")
        ],
        [
            InlineKeyboardButton("🧺 Keranjang", callback_data="cart")
        ],
        [
            InlineKeyboardButton("📦 Pesanan Saya", callback_data="orders"),
            InlineKeyboardButton("💳 Pembayaran", callback_data="payment")
        ],
        [
            InlineKeyboardButton("👨‍💻 Contact Admin", callback_data="support")
        ]
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 Kelola Produk",
                callback_data="adminlist"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 Kelola Pesanan",
                callback_data="adminorders"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Statistik Toko",
                callback_data="adminstats"
            )
        ],
        [
            InlineKeyboardButton(
                "💳 Edit Payment",
                callback_data="adminpayment"
            )
        ]
    ])


def order_buttons(oid, include_payment=True):
    rows = []

    if include_payment:
        rows.append([
            InlineKeyboardButton(
                "💳 INFO PEMBAYARAN",
                callback_data=f"payorder:{oid}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "📤 CARA KIRIM BUKTI",
            callback_data=f"proofhelp:{oid}"
        )
    ])

    rows.append([
        InlineKeyboardButton(
            "⬅️ Menu",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(rows)


def admin_order_buttons(oid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⚙️ PROSES",
                callback_data=f"setstatus:processing:{oid}"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ APPROVED",
                callback_data=f"setstatus:paid:{oid}"
            ),
            InlineKeyboardButton(
                "❌ REJECTED",
                callback_data=f"setstatus:rejected:{oid}"
            )
        ],
        [
            InlineKeyboardButton(
                "🏁 SELESAI",
                callback_data=f"setstatus:completed:{oid}"
            )
        ]
    ])


async def is_joined(update, context):
    if not REQUIRED_CHAT:
        return True

    try:
        member = await context.bot.get_chat_member(
            REQUIRED_CHAT,
            update.effective_user.id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception:
        return False


async def safe_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


# =========================================================
# FIX /START
# =========================================================

async def replace_menu(chat_id, context, text="🔥 *Menu Utama*"):
    old_id = context.user_data.get("last_menu_id")

    if old_id:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=old_id
            )
        except Exception:
            pass

    msg = await context.bot.send_message(
        chat_id,
        text,
        parse_mode="Markdown",
        reply_markup=menu()
    )

    context.user_data["last_menu_id"] = msg.message_id
    return msg


async def send_home(
    chat_id,
    context,
    text="🔥 *Menu Utama*"
):
    return await replace_menu(chat_id, context, text)


async def start(update, context):
    uid = update.effective_user.id
    uname = update.effective_user.username or ""

    con = db()

    con.execute("""
        INSERT INTO users(user_id, username)
        VALUES(?,?)
        ON CONFLICT(user_id)
        DO UPDATE SET username=excluded.username
    """, (uid, uname))

    con.commit()
    con.close()

    # Telegram tidak selalu mengizinkan bot menghapus
    # command user. Jadi jangan bergantung pada itu.
    await safe_delete(update.message)

    old_id = context.user_data.get("last_menu_id")

    if old_id:
        try:
            await context.bot.delete_message(
                chat_id=uid,
                message_id=old_id
            )
        except Exception:
            pass

    if not await is_joined(update, context):
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔗 JOIN GRUP",
                    url=f"https://t.me/{REQUIRED_CHAT.lstrip('@')}"
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ SUDAH JOIN",
                    callback_data="check_join"
                )
            ]
        ])

        msg = await context.bot.send_message(
            uid,
            "🔒 *Akses dikunci*\n\n"
            "Join grup wajib terlebih dahulu, "
            "lalu tekan *SUDAH JOIN*.",
            parse_mode="Markdown",
            reply_markup=kb
        )

        context.user_data["last_menu_id"] = msg.message_id
        return

    await replace_menu(
        uid,
        context,
        "🔥 *Selamat datang di Store!*\n"
        "Pilih menu di bawah."
    )


# =========================================================
# ADMIN NOTIFICATION
# =========================================================

async def notify_admins(
    context,
    text,
    reply_markup=None,
    photo=None
):
    sent = []

    for admin_id in ADMIN_IDS:
        try:
            if photo:
                msg = await context.bot.send_photo(
                    admin_id,
                    photo=photo,
                    caption=text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            else:
                msg = await context.bot.send_message(
                    admin_id,
                    text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )

            sent.append(msg)

        except Exception:
            logging.exception(
                "Private admin notification failed"
            )

    if ADMIN_GROUP_ID:
        try:
            if photo:
                await context.bot.send_photo(
                    ADMIN_GROUP_ID,
                    photo=photo,
                    caption=text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    ADMIN_GROUP_ID,
                    text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )

        except Exception:
            logging.exception(
                "Admin group notification failed"
            )

    return sent


# =========================================================
# CART
# =========================================================

def stock_ok(con, pid, qty):
    row = con.execute(
        "SELECT stock FROM products WHERE id=?",
        (pid,)
    ).fetchone()

    if not row:
        return False

    stock = row[0]

    return stock < 0 or stock >= qty


def cart_rows(uid):
    con = db()

    rows = con.execute("""
        SELECT
            c.product_id,
            c.qty,
            p.name,
            p.price,
            p.stock,
            p.photo,
            p.description
        FROM cart c
        JOIN products p
            ON p.id=c.product_id
        WHERE c.user_id=?
        ORDER BY p.id DESC
    """, (uid,)).fetchall()

    con.close()

    return rows


def price_num(value):
    try:
        return int(
            re.sub(
                r"[^0-9]",
                "",
                str(value)
            ) or 0
        )
    except Exception:
        return 0


def cart_text(rows, discount=0):
    if not rows:
        return "🧺 *Keranjang kosong.*"

    total = sum(
        price_num(row[3]) * row[1]
        for row in rows
    )

    final = max(0, total - discount)

    text = "🧺 *KERANJANG*\n\n"

    text += "\n".join(
        f"• {row[2]} × {row[1]} — {row[3]}"
        for row in rows
    )

    text += (
        f"\n\n💰 Subtotal: `{total}`"
        f"\n🎟️ Diskon: `{discount}`"
        f"\n💳 Total: `{final}`"
    )

    return text


def cart_kb(rows):
    kb = []

    for row in rows:
        kb.append([
            InlineKeyboardButton(
                f"➖ {row[2]}",
                callback_data=f"cartminus:{row[0]}"
            ),
            InlineKeyboardButton(
                f"{row[1]} pcs",
                callback_data="noop"
            ),
            InlineKeyboardButton(
                f"➕ {row[2]}",
                callback_data=f"cartplus:{row[0]}"
            )
        ])

    kb.append([
        InlineKeyboardButton(
            "🗑️ Kosongkan",
            callback_data="cartclear"
        ),
        InlineKeyboardButton(
            "⚡ CHECKOUT",
            callback_data="checkout"
        )
    ])

    kb.append([
        InlineKeyboardButton(
            "⬅️ Menu",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(kb)


async def show_cart(
    uid,
    context,
    message=None
):
    rows = cart_rows(uid)

    text = cart_text(rows)

    if rows:
        kb = cart_kb(rows)
    else:
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🛒 Katalog",
                    callback_data="catalog"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Menu",
                    callback_data="home"
                )
            ]
        ])

    if message:
        try:
            await message.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=kb
            )
            return
        except Exception:
            pass

    await context.bot.send_message(
        uid,
        text,
        parse_mode="Markdown",
        reply_markup=kb
    )


# =========================================================
# ORDER CREATION
# =========================================================

async def create_order(uid, context, rows):
    con = db()

    for row in rows:
        pid = row[0]
        qty = row[1]

        if not stock_ok(con, pid, qty):
            con.close()
            return None, "Stok produk tidak cukup."

    cur = con.execute(
        """
        INSERT INTO orders(
            user_id,
            product_id,
            status
        )
        VALUES(?,?,?)
        """,
        (
            uid,
            rows[0][0],
            "pending_payment"
        )
    )

    oid = cur.lastrowid

    for row in rows:
        pid = row[0]
        qty = row[1]
        name = row[2]
        price = row[3]
        stock = row[4]

        con.execute(
            """
            INSERT INTO order_items(
                order_id,
                product_id,
                qty,
                price,
                name
            )
            VALUES(?,?,?,?,?)
            """,
            (
                oid,
                pid,
                qty,
                price,
                name
            )
        )

        if stock > 0:
            con.execute(
                """
                UPDATE products
                SET stock=stock-?
                WHERE id=?
                """,
                (qty, pid)
            )

    con.execute(
        "DELETE FROM cart WHERE user_id=?",
        (uid,)
    )

    con.commit()
    con.close()

    return oid, None


async def send_order_created(
    uid,
    context,
    oid
):
    con = db()

    rows = con.execute(
        """
        SELECT name,qty,price
        FROM order_items
        WHERE order_id=?
        """,
        (oid,)
    ).fetchall()

    con.close()

    total = sum(
        price_num(row[2]) * row[1]
        for row in rows
    )

    products = "\n".join(
        f"• {row[0]} × {row[1]} — {row[2]}"
        for row in rows
    )

    text = (
        "🧾 *ORDER BERHASIL DIBUAT*\n\n"
        f"🆔 ID Transaksi: `ORD-{oid:05d}`\n"
        f"📦 Produk:\n{products}\n"
        f"💰 Total: `{total}`\n"
        "📌 Status: Menunggu pembayaran\n\n"
        "💳 *Pembayaran:*\n"
        f"{get_payment()}\n\n"
        "Setelah bayar, kirim *foto bukti pembayaran* "
        "ke chat bot ini.\n"
        f"Tulis `ORD-{oid:05d}` di caption foto."
    )

    await context.bot.send_message(
        uid,
        text,
        parse_mode="Markdown",
        reply_markup=order_buttons(oid)
    )

    await notify_admins(
        context,
        (
            "🔔 *PESANAN BARU*\n\n"
            f"🆔 `ORD-{oid:05d}`\n"
            f"👤 User ID: `{uid}`\n"
            f"📦\n{products}\n"
            f"💰 Total: `{total}`\n"
            "📌 Status: Menunggu pembayaran"
        ),
        admin_order_buttons(oid)
    )


def order_items_text(oid):
    con = db()

    rows = con.execute(
        """
        SELECT name,qty
        FROM order_items
        WHERE order_id=?
        """,
        (oid,)
    ).fetchall()

    con.close()

    return ", ".join(
        f"{name} × {qty}"
        for name, qty in rows
    )


async def deliver_order(
    oid,
    uid,
    context
):
    """
    Delivery digital memakai Description produk.
    Jadi untuk sementara isi Description dengan
    konten/file-link produk digital.
    """

    con = db()

    rows = con.execute(
        """
        SELECT product_id,name,qty
        FROM order_items
        WHERE order_id=?
        """,
        (oid,)
    ).fetchall()

    con.close()

    delivered = False

    for pid, name, qty in rows:
        con = db()

        product = con.execute(
            """
            SELECT description
            FROM products
            WHERE id=?
            """,
            (pid,)
        ).fetchone()

        con.close()

        if product and product[0]:
            await context.bot.send_message(
                uid,
                (
                    f"🎁 *DELIVERY* — {name}\n\n"
                    f"{product[0]}"
                ),
                parse_mode="Markdown"
            )

            delivered = True

    if delivered:
        await context.bot.send_message(
            uid,
            (
                f"✅ *Order ORD-{oid:05d} "
                "sudah approved.*\n\n"
                "Produk digital sudah dikirim."
            ),
            parse_mode="Markdown"
        )
    else:
        await context.bot.send_message(
            uid,
            (
                f"✅ *Order ORD-{oid:05d} "
                "sudah approved.*\n\n"
                "Silakan tunggu proses pengiriman "
                "dari admin."
            ),
            parse_mode="Markdown"
        )


# =========================================================
# CALLBACK
# =========================================================

async def callback(update, context):
    q = update.callback_query
    data = q.data

    if data == "noop":
        await q.answer()
        return

    await q.answer()

    if data == "check_join":
        if await is_joined(update, context):
            await safe_delete(q.message)

            await send_home(
                update.effective_user.id,
                context,
                "✅ *Verifikasi berhasil!*\n\n"
                "Selamat datang di Store 🔥"
            )
        else:
            await q.answer(
                "❌ Kamu belum join grup!",
                show_alert=True
            )

        return

    if not await is_joined(update, context):
        await q.answer(
            "❌ Join grup wajib dulu.",
            show_alert=True
        )
        return

    uid = update.effective_user.id

    # HOME
    if data == "home":
        await safe_delete(q.message)
        await send_home(uid, context)
        return

    # KATALOG
    if data == "catalog":
        con = db()

        rows = con.execute(
            """
            SELECT id,name,price,stock
            FROM products
            ORDER BY id DESC
            """
        ).fetchall()

        con.close()

        await safe_delete(q.message)

        if not rows:
            await context.bot.send_message(
                uid,
                "📭 Katalog masih kosong.",
                reply_markup=menu()
            )
            return

        kb = []

        for row in rows:
            stock_text = (
                "∞"
                if row[3] < 0
                else str(row[3])
            )

            kb.append([
                InlineKeyboardButton(
                    (
                        f"🛍️ {row[1]} • {row[2]} "
                        f"(Stok: {stock_text})"
                    ),
                    callback_data=f"product:{row[0]}"
                )
            ])

        kb.append([
            InlineKeyboardButton(
                "🔎 Cari Produk",
                callback_data="search"
            )
        ])

        kb.append([
            InlineKeyboardButton(
                "⬅️ Kembali",
                callback_data="home"
            )
        ])

        await context.bot.send_message(
            uid,
            "🛒 *Katalog Produk*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

        return

    # SEARCH
    if data == "search":
        context.user_data["searching"] = True

        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            (
                "🔎 Kirim nama/kata kunci produk "
                "yang mau dicari.\n\n"
                "Ketik /cancel untuk batal."
            )
        )

        return

    # CART
    if data == "cart":
        await safe_delete(q.message)
        await show_cart(uid, context)
        return

    # CART PLUS / MINUS
    if data.startswith("cartplus:") or data.startswith("cartminus:"):
        pid = int(data.split(":")[1])

        delta = (
            1
            if data.startswith("cartplus:")
            else -1
        )

        con = db()

        row = con.execute(
            """
            SELECT qty
            FROM cart
            WHERE user_id=?
            AND product_id=?
            """,
            (uid, pid)
        ).fetchone()

        if not row:
            con.close()

            await q.answer(
                "Produk tidak ada di keranjang.",
                show_alert=True
            )

            return

        new_qty = row[0] + delta

        if new_qty <= 0:
            con.execute(
                """
                DELETE FROM cart
                WHERE user_id=?
                AND product_id=?
                """,
                (uid, pid)
            )

        elif stock_ok(con, pid, new_qty):
            con.execute(
                """
                UPDATE cart
                SET qty=?
                WHERE user_id=?
                AND product_id=?
                """,
                (
                    new_qty,
                    uid,
                    pid
                )
            )

        else:
            con.close()

            await q.answer(
                "❌ Stok tidak cukup.",
                show_alert=True
            )

            return

        con.commit()
        con.close()

        await show_cart(
            uid,
            context,
            q.message
        )

        return

    # CLEAR CART
    if data == "cartclear":
        con = db()

        con.execute(
            "DELETE FROM cart WHERE user_id=?",
            (uid,)
        )

        con.commit()
        con.close()

        await show_cart(
            uid,
            context,
            q.message
        )

        return

    # PRODUCT DETAIL
    if data.startswith("product:"):
        pid = int(data.split(":")[1])

        con = db()

        product = con.execute(
            """
            SELECT
                id,
                name,
                price,
                description,
                photo,
                stock
            FROM products
            WHERE id=?
            """,
            (pid,)
        ).fetchone()

        con.close()

        if not product:
            await q.answer(
                "Produk tidak ditemukan.",
                show_alert=True
            )
            return

        await safe_delete(q.message)

        stock_text = (
            "Unlimited"
            if product[5] < 0
            else f"{product[5]} Pcs"
        )

        text = (
            f"🛍️ *{product[1]}*\n"
            f"💰 Harga: `{product[2]}`\n"
            f"📦 Stok: `{stock_text}`\n\n"
            "📝 Deskripsi:\n"
            f"{product[3] or 'Tidak ada deskripsi.'}"
        )

        if product[5] != 0:
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🛒 TAMBAH KE KERANJANG",
                        callback_data=f"addcart:{product[0]}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⚡ BELI SEKARANG",
                        callback_data=f"buy:{product[0]}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Katalog",
                        callback_data="catalog"
                    )
                ]
            ])
        else:
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Katalog",
                        callback_data="catalog"
                    )
                ]
            ])

        if product[4]:
            await context.bot.send_photo(
                uid,
                photo=product[4],
                caption=text,
                parse_mode="Markdown",
                reply_markup=kb
            )
        else:
            await context.bot.send_message(
                uid,
                text,
                parse_mode="Markdown",
                reply_markup=kb
            )

        return

    # ADD CART
    if data.startswith("addcart:"):
        pid = int(data.split(":")[1])

        con = db()

        product = con.execute(
            """
            SELECT name,stock
            FROM products
            WHERE id=?
            """,
            (pid,)
        ).fetchone()

        if not product:
            con.close()

            await q.answer(
                "Produk tidak ditemukan.",
                show_alert=True
            )

            return

        existing = con.execute(
            """
            SELECT qty
            FROM cart
            WHERE user_id=?
            AND product_id=?
            """,
            (uid, pid)
        ).fetchone()

        new_qty = (
            existing[0]
            if existing
            else 0
        ) + 1

        if (
            product[1] == 0
            or (
                product[1] > 0
                and new_qty > product[1]
            )
        ):
            con.close()

            await q.answer(
                "❌ Stok tidak cukup.",
                show_alert=True
            )

            return

        con.execute(
            """
            INSERT INTO cart(
                user_id,
                product_id,
                qty
            )
            VALUES(?,?,?)
            ON CONFLICT(user_id,product_id)
            DO UPDATE SET qty=excluded.qty
            """,
            (
                uid,
                pid,
                new_qty
            )
        )

        con.commit()
        con.close()

        await q.answer(
            f"✅ {product[0]} masuk keranjang"
        )

        return

    # BUY NOW
    if data.startswith("buy:"):
        pid = int(data.split(":")[1])

        con = db()

        product = con.execute(
            """
            SELECT
                id,
                name,
                price,
                stock,
                photo
            FROM products
            WHERE id=?
            """,
            (pid,)
        ).fetchone()

        con.close()

        if not product:
            await q.answer(
                "Produk tidak ditemukan.",
                show_alert=True
            )
            return

        if product[3] == 0:
            await q.answer(
                "❌ Stok habis.",
                show_alert=True
            )
            return

        rows = [(
            product[0],
            1,
            product[1],
            product[2],
            product[3],
            product[4],
            ""
        )]

        oid, error = await create_order(
            uid,
            context,
            rows
        )

        if error:
            await q.answer(
                "❌ " + error,
                show_alert=True
            )
            return

        await safe_delete(q.message)

        await send_order_created(
            uid,
            context,
            oid
        )

        return

    # CHECKOUT
    if data == "checkout":
        rows = cart_rows(uid)

        if not rows:
            await q.answer(
                "Keranjang kosong.",
                show_alert=True
            )
            return

        await safe_delete(q.message)

        text = (
            cart_text(rows)
            + "\n\nKlik konfirmasi untuk "
              "membuat order."
        )

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ KONFIRMASI CHECKOUT",
                    callback_data="checkout_confirm"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Keranjang",
                    callback_data="cart"
                )
            ]
        ])

        await context.bot.send_message(
            uid,
            text,
            parse_mode="Markdown",
            reply_markup=kb
        )

        return

    # CONFIRM CHECKOUT
    if data == "checkout_confirm":
        rows = cart_rows(uid)

        if not rows:
            await q.answer(
                "Keranjang kosong.",
                show_alert=True
            )
            return

        oid, error = await create_order(
            uid,
            context,
            rows
        )

        if error:
            await q.answer(
                "❌ " + error,
                show_alert=True
            )
            return

        await safe_delete(q.message)

        await send_order_created(
            uid,
            context,
            oid
        )

        return

    # PAYMENT ORDER
    if data.startswith("payorder:"):
        oid = int(data.split(":")[1])

        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            (
                f"💳 *Pembayaran ORD-{oid:05d}*\n\n"
                f"{get_payment()}\n\n"
                "Kirim foto bukti pembayaran "
                f"dengan caption `ORD-{oid:05d}`."
            ),
            parse_mode="Markdown",
            reply_markup=order_buttons(
                oid,
                False
            )
        )

        return

    # PROOF HELP
    if data.startswith("proofhelp:"):
        oid = int(data.split(":")[1])

        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            (
                "📤 *Cara Kirim Bukti*\n\n"
                "1. Bayar sesuai info pembayaran.\n"
                "2. Kirim foto bukti ke chat bot.\n"
                f"3. Caption wajib berisi `ORD-{oid:05d}`.\n"
                "4. Admin akan mengecek."
            ),
            parse_mode="Markdown",
            reply_markup=order_buttons(
                oid,
                False
            )
        )

        return

    # ORDERS
    if data == "orders":
        con = db()

        rows = con.execute(
            """
            SELECT
                o.id,
                o.status,
                COALESCE(
                    (
                        SELECT GROUP_CONCAT(
                            name || ' × ' || qty,
                            ', '
                        )
                        FROM order_items
                        WHERE order_id=o.id
                    ),
                    p.name
                ),
                p.price
            FROM orders o
            JOIN products p
                ON p.id=o.product_id
            WHERE o.user_id=?
            ORDER BY o.id DESC
            LIMIT 15
            """,
            (uid,)
        ).fetchall()

        con.close()

        if not rows:
            text = "📦 Belum ada pesanan."
        else:
            text = (
                "📦 *Pesanan Saya*\n\n"
                +
                "\n".join(
                    (
                        f"🆔 `ORD-{row[0]:05d}`\n"
                        f"📦 {row[2]}\n"
                        f"💰 {row[3]}\n"
                        f"📌 {STATUS_TEXT.get(row[1], row[1])}\n"
                    )
                    for row in rows
                )
            )

        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            text,
            parse_mode="Markdown",
            reply_markup=menu()
        )

        return

    # PAYMENT
    if data == "payment":
        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            f"💳 *Pembayaran*\n\n{get_payment()}",
            parse_mode="Markdown",
            reply_markup=menu()
        )

        return

    # SUPPORT
    if data == "support":
        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            (
                "👨‍💻 *Contact Admin*\n\n"
                f"{SUPPORT_USERNAME or 'Silakan hubungi admin toko.'}"
            ),
            parse_mode="Markdown",
            reply_markup=menu()
        )

        return

    # ADMIN HOME
    if data == "adminhome":
        if uid not in ADMIN_IDS:
            return

        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            "👑 *Admin Panel*",
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )

        return

    # ADMIN LIST
    if data == "adminlist":
        if uid not in ADMIN_IDS:
            return

        con = db()

        rows = con.execute(
            """
            SELECT id,name,price,stock
            FROM products
            ORDER BY id DESC
            """
        ).fetchall()

        con.close()

        await safe_delete(q.message)

        if not rows:
            await context.bot.send_message(
                uid,
                "🛒 Katalog kosong.",
                reply_markup=admin_menu()
            )
            return

        kb = []

        for pid, name, price, stock in rows:
            stock_text = (
                "∞"
                if stock < 0
                else str(stock)
            )

            kb.append([
                InlineKeyboardButton(
                    (
                        f"🛍️ {name} • {price} "
                        f"(Stok: {stock_text})"
                    ),
                    callback_data=f"adminview:{pid}"
                )
            ])

        kb.append([
            InlineKeyboardButton(
                "⬅️ Admin Panel",
                callback_data="adminhome"
            )
        ])

        await context.bot.send_message(
            uid,
            "👑 *Kelola Produk*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

        return

    # ADMIN STATS
    if data == "adminstats":
        if uid not in ADMIN_IDS:
            return

        await safe_delete(q.message)

        await send_admin_stats(
            uid,
            context
        )

        return

    # ADMIN PAYMENT
    if data == "adminpayment":
        if uid not in ADMIN_IDS:
            return

        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            (
                "💳 *Payment Saat Ini:*\n\n"
                f"{get_payment()}\n\n"
                "Untuk mengubah:\n"
                "`/setpayment isi payment baru`"
            ),
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )

        return

    # ADMIN ORDERS
    if data == "adminorders":
        if uid not in ADMIN_IDS:
            return

        con = db()

        rows = con.execute(
            """
            SELECT
                o.id,
                p.name,
                p.price,
                o.status
            FROM orders o
            JOIN products p
                ON p.id=o.product_id
            ORDER BY o.id DESC
            LIMIT 30
            """
        ).fetchall()

        con.close()

        await safe_delete(q.message)

        if rows:
            text = (
                "📦 *Order Terbaru*\n\n"
                +
                "\n".join(
                    (
                        f"ORD-{row[0]:05d} • "
                        f"{row[1]} • "
                        f"{row[2]} • "
                        f"{STATUS_TEXT.get(row[3], row[3])}"
                    )
                    for row in rows
                )
            )
        else:
            text = "📦 Belum ada order."

        await context.bot.send_message(
            uid,
            text,
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )

        return

    # ADMIN PRODUCT VIEW
    if data.startswith("adminview:"):
        if uid not in ADMIN_IDS:
            return

        pid = int(data.split(":")[1])

        con = db()

        product = con.execute(
            """
            SELECT
                id,
                name,
                price,
                description,
                photo,
                stock
            FROM products
            WHERE id=?
            """,
            (pid,)
        ).fetchone()

        con.close()

        if not product:
            await q.answer(
                "Produk tidak ditemukan.",
                show_alert=True
            )
            return

        await safe_delete(q.message)

        stock_text = (
            "Unlimited"
            if product[5] < 0
            else f"{product[5]} Pcs"
        )

        text = (
            "👑 *Kelola Produk*\n\n"
            f"🆔 ID: `{product[0]}`\n"
            f"🛍️ {product[1]}\n"
            f"💰 {product[2]}\n"
            f"📦 Stok: `{stock_text}`\n"
            f"📝 {product[3] or '-'}"
        )

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🗑️ HAPUS",
                    callback_data=f"admindelete:{product[0]}"
                ),
                InlineKeyboardButton(
                    "✏️ EDIT",
                    callback_data=f"adminedithelp:{product[0]}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Daftar Produk",
                    callback_data="adminlist"
                )
            ]
        ])

        if product[4]:
            await context.bot.send_photo(
                uid,
                photo=product[4],
                caption=text,
                parse_mode="Markdown",
                reply_markup=kb
            )
        else:
            await context.bot.send_message(
                uid,
                text,
                parse_mode="Markdown",
                reply_markup=kb
            )

        return

    # DELETE PRODUCT
    if data.startswith("admindelete:"):
        if uid not in ADMIN_IDS:
            return

        pid = int(data.split(":")[1])

        con = db()

        product = con.execute(
            "SELECT name FROM products WHERE id=?",
            (pid,)
        ).fetchone()

        if not product:
            con.close()

            await q.answer(
                "Produk tidak ditemukan.",
                show_alert=True
            )

            return

        con.execute(
            "DELETE FROM products WHERE id=?",
            (pid,)
        )

        con.commit()
        con.close()

        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            f"🗑️ Produk *{product[0]}* berhasil dihapus.",
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )

        return

    # EDIT HELP
    if data.startswith("adminedithelp:"):
        if uid not in ADMIN_IDS:
            return

        pid = int(data.split(":")[1])

        await safe_delete(q.message)

        await context.bot.send_message(
            uid,
            (
                f"✏️ *Edit Produk #{pid}*\n\n"
                f"`/edit {pid} | Nama Baru | Harga Baru | "
                "Deskripsi Baru | Stok`"
            ),
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )

        return

    # SET STATUS
    if data.startswith("setstatus:"):
        if uid not in ADMIN_IDS:
            return

        _, status, oid_text = data.split(":")
        oid = int(oid_text)

        if status not in STATUS_TEXT:
            await q.answer(
                "Status tidak valid.",
                show_alert=True
            )
            return

        con = db()

        row = con.execute(
            """
            SELECT
                o.user_id,
                p.name,
                p.price
            FROM orders o
            JOIN products p
                ON p.id=o.product_id
            WHERE o.id=?
            """,
            (oid,)
        ).fetchone()

        if not row:
            con.close()

            await q.answer(
                "Order tidak ditemukan.",
                show_alert=True
            )

            return

        con.execute(
            """
            UPDATE orders
            SET status=?
            WHERE id=?
            """,
            (status, oid)
        )

        con.commit()
        con.close()

        user_id, product, price = row

        items = order_items_text(oid)

        user_msg = (
            "📦 *Update Order*\n\n"
            f"🆔 `ORD-{oid:05d}`\n"
            f"📦 {items or product}\n"
            f"💰 {price}\n"
            f"📌 Status: *{STATUS_TEXT[status]}*"
        )

        if status == "paid":
            user_msg += (
                "\n\n"
                "🎁 Pembayaran dikonfirmasi. "
                "Pesanan kamu sedang diproses."
            )

        try:
            await context.bot.send_message(
                user_id,
                user_msg,
                parse_mode="Markdown"
            )
        except Exception:
            logging.exception(
                "User notification failed"
            )

        # APPROVED = kirim produk
        if status == "paid":
            await deliver_order(
                oid,
                user_id,
                context
            )

        await q.answer(
            f"Status: {STATUS_TEXT[status]}"
        )

        try:
            if q.message.photo:
                await q.edit_message_caption(
                    caption=(
                        f"{q.message.caption or ''}\n\n"
                        f"📌 STATUS: {STATUS_TEXT[status]}"
                    ),
                    reply_markup=admin_order_buttons(oid)
                )
            else:
                await q.edit_message_text(
                    text=(
                        f"{q.message.text or ''}\n\n"
                        f"📌 STATUS: {STATUS_TEXT[status]}"
                    ),
                    reply_markup=admin_order_buttons(oid)
                )
        except Exception:
            pass

        return


# =========================================================
# ADMIN
# =========================================================

async def send_admin_stats(
    chat_id,
    context
):
    con = db()

    total_users = con.execute(
        "SELECT COUNT(DISTINCT user_id) FROM users"
    ).fetchone()[0]

    total_products = con.execute(
        "SELECT COUNT(*) FROM products"
    ).fetchone()[0]

    total_orders = con.execute(
        "SELECT COUNT(*) FROM orders"
    ).fetchone()[0]

    total_paid = con.execute(
        """
        SELECT COUNT(*)
        FROM orders
        WHERE status IN ('paid','completed')
        """
    ).fetchone()[0]

    con.close()

    text = (
        "📊 *STATISTIK TOKO*\n\n"
        f"👤 Total Pengguna: `{total_users}`\n"
        f"🛍️ Total Produk: `{total_products}`\n"
        f"📦 Total Transaksi: `{total_orders}`\n"
        f"✅ Transaksi Berhasil: `{total_paid}`"
    )

    await context.bot.send_message(
        chat_id,
        text,
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )


async def admin_add(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    raw = update.message.text.partition(" ")[2].strip()

    parts = [
        x.strip()
        for x in raw.split("|")
    ]

    if len(parts) < 2:
        await update.message.reply_text(
            (
                "Format:\n"
                "`/add Nama | Harga | Deskripsi | Stok`\n\n"
                "Stok `-1` = unlimited."
            ),
            parse_mode="Markdown"
        )
        return

    name = parts[0]
    price = parts[1]
    desc = parts[2] if len(parts) > 2 else ""

    stock = (
        int(parts[3])
        if len(parts) > 3
        and parts[3].lstrip("-").isdigit()
        else -1
    )

    con = db()

    con.execute(
        """
        INSERT INTO products(
            name,
            price,
            description,
            stock
        )
        VALUES(?,?,?,?)
        """,
        (
            name,
            price,
            desc,
            stock
        )
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        f"✅ Produk *{name}* berhasil ditambahkan.",
        parse_mode="Markdown"
    )


async def admin_photo(update, context):
    uid = update.effective_user.id
    caption = (
        update.message.caption or ""
    ).strip()

    # ADD PRODUK + FOTO
    if (
        uid in ADMIN_IDS
        and caption.lower().startswith("/add")
    ):
        parts = [
            x.strip()
            for x in caption.partition(" ")[2]
            .strip()
            .split("|")
        ]

        if len(parts) < 2:
            await update.message.reply_text(
                (
                    "❌ Format:\n"
                    "`/add Nama | Harga | "
                    "Deskripsi | Stok`"
                ),
                parse_mode="Markdown"
            )
            return

        name = parts[0]
        price = parts[1]
        desc = (
            parts[2]
            if len(parts) > 2
            else ""
        )

        stock = (
            int(parts[3])
            if len(parts) > 3
            and parts[3].lstrip("-").isdigit()
            else -1
        )

        photo_id = update.message.photo[-1].file_id

        con = db()

        con.execute(
            """
            INSERT INTO products(
                name,
                price,
                description,
                photo,
                stock
            )
            VALUES(?,?,?,?,?)
            """,
            (
                name,
                price,
                desc,
                photo_id,
                stock
            )
        )

        con.commit()
        con.close()

        await update.message.reply_text(
            (
                f"✅ Produk *{name}* "
                "+ foto berhasil ditambahkan."
            ),
            parse_mode="Markdown"
        )

        return

    # BUKTI PEMBAYARAN
    match = re.search(
        r"ORD-(\d+)",
        caption.upper()
    )

    if not match:
        await update.message.reply_text(
            (
                "📸 Caption bukti wajib berisi "
                "ID seperti `ORD-00001`."
            ),
            parse_mode="Markdown"
        )
        return

    oid = int(match.group(1))

    con = db()

    row = con.execute(
        """
        SELECT
            o.user_id,
            p.name,
            p.price
        FROM orders o
        JOIN products p
            ON p.id=o.product_id
        WHERE o.id=?
        """,
        (oid,)
    ).fetchone()

    if not row:
        con.close()

        await update.message.reply_text(
            "❌ ID transaksi tidak ditemukan."
        )
        return

    user_id, product, price = row

    if user_id != uid:
        con.close()

        await update.message.reply_text(
            "❌ Order ini bukan milik kamu."
        )
        return

    con.execute(
        """
        UPDATE orders
        SET status='proof_received'
        WHERE id=?
        """,
        (oid,)
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        (
            f"📸 Bukti `ORD-{oid:05d}` diterima.\n"
            "Tunggu admin."
        ),
        parse_mode="Markdown"
    )

    items = order_items_text(oid)

    await notify_admins(
        context,
        (
            "🔔 *BUKTI PEMBAYARAN BARU*\n\n"
            f"🆔 `ORD-{oid:05d}`\n"
            f"👤 User ID: `{uid}`\n"
            f"📦 {items or product}\n"
            f"💰 {price}\n"
            "📌 Status: Bukti diterima"
        ),
        admin_order_buttons(oid),
        photo=update.message.photo[-1].file_id
    )


# =========================================================
# SEARCH
# =========================================================

async def search_message(update, context):
    if not context.user_data.get("searching"):
        return

    term = update.message.text.strip()

    if not term:
        return

    con = db()

    rows = con.execute(
        """
        SELECT id,name,price,stock
        FROM products
        WHERE name LIKE ?
        OR description LIKE ?
        ORDER BY id DESC
        """,
        (
            f"%{term}%",
            f"%{term}%"
        )
    ).fetchall()

    con.close()

    context.user_data["searching"] = False

    if not rows:
        await update.message.reply_text(
            f"🔎 Tidak ada produk untuk `{term}`.",
            parse_mode="Markdown",
            reply_markup=menu()
        )
        return

    kb = []

    for row in rows:
        stock_text = (
            "∞"
            if row[3] < 0
            else str(row[3])
        )

        kb.append([
            InlineKeyboardButton(
                (
                    f"🛍️ {row[1]} • {row[2]} "
                    f"(Stok: {stock_text})"
                ),
                callback_data=f"product:{row[0]}"
            )
        ])

    kb.append([
        InlineKeyboardButton(
            "⬅️ Menu",
            callback_data="home"
        )
    ])

    await update.message.reply_text(
        f"🔎 *Hasil pencarian:* `{term}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def cancel(update, context):
    context.user_data["searching"] = False

    await update.message.reply_text(
        "❌ Pencarian dibatalkan.",
        reply_markup=menu()
    )


# =========================================================
# OTHER COMMANDS
# =========================================================

async def show_chat_id(update, context):
    if update.effective_chat.type in (
        "group",
        "supergroup"
    ):
        await update.message.reply_text(
            (
                "🆔 *ID Grup Ini:*\n"
                f"`{update.effective_chat.id}`\n\n"
                "Masukkan ke Railway → Variables → "
                "`ADMIN_GROUP_ID`."
            ),
            parse_mode="Markdown"
        )

    else:
        await update.message.reply_text(
            (
                "🆔 Chat ID kamu: "
                f"`{update.effective_chat.id}`"
            ),
            parse_mode="Markdown"
        )


async def admin_broadcast(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    msg = update.message.text.partition(" ")[2].strip()

    if not msg:
        await update.message.reply_text(
            "Format: `/bc Pesan broadcast kamu`",
            parse_mode="Markdown"
        )
        return

    con = db()

    users = con.execute(
        "SELECT DISTINCT user_id FROM users"
    ).fetchall()

    con.close()

    success = 0
    fail = 0

    for (user_id,) in users:
        try:
            await context.bot.send_message(
                user_id,
                f"📢 *PENGUMUMAN*\n\n{msg}",
                parse_mode="Markdown"
            )
            success += 1

        except Exception:
            fail += 1

    await update.message.reply_text(
        (
            "📢 *Broadcast Selesai*\n\n"
            f"✅ Berhasil: `{success}`\n"
            f"❌ Gagal: `{fail}`"
        ),
        parse_mode="Markdown"
    )


async def check_order_cmd(update, context):
    raw = update.message.text.partition(" ")[2].strip()

    match = re.search(
        r"(\d+)",
        raw
    )

    if not match:
        await update.message.reply_text(
            "Format: `/cek ORD-00001`",
            parse_mode="Markdown"
        )
        return

    oid = int(match.group(1))

    con = db()

    row = con.execute(
        """
        SELECT
            o.id,
            o.user_id,
            p.name,
            p.price,
            o.status
        FROM orders o
        JOIN products p
            ON p.id=o.product_id
        WHERE o.id=?
        """,
        (oid,)
    ).fetchone()

    con.close()

    if not row:
        await update.message.reply_text(
            "❌ Order tidak ditemukan."
        )
        return

    items = order_items_text(oid)

    await update.message.reply_text(
        (
            "🔍 *DETAIL PESANAN*\n\n"
            f"🆔 `ORD-{row[0]:05d}`\n"
            f"👤 User ID: `{row[1]}`\n"
            f"📦 Produk: {items or row[2]}\n"
            f"💰 {row[3]}\n"
            f"📌 Status: "
            f"*{STATUS_TEXT.get(row[4], row[4])}*"
        ),
        parse_mode="Markdown"
    )


async def admin_stats_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    await send_admin_stats(
        update.effective_user.id,
        context
    )


async def admin_products(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    await update.message.reply_text(
        "👑 *Admin Panel*",
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )


async def admin_delete(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if (
        len(context.args) != 1
        or not context.args[0].isdigit()
    ):
        await update.message.reply_text(
            "Format: /delete ID_PRODUK"
        )
        return

    pid = int(context.args[0])

    con = db()

    row = con.execute(
        "SELECT name FROM products WHERE id=?",
        (pid,)
    ).fetchone()

    if not row:
        con.close()

        await update.message.reply_text(
            "❌ Produk tidak ditemukan."
        )
        return

    con.execute(
        "DELETE FROM products WHERE id=?",
        (pid,)
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        f"🗑️ Produk *{row[0]}* dihapus.",
        parse_mode="Markdown"
    )


async def admin_edit(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    parts = [
        x.strip()
        for x in update.message.text
        .partition(" ")[2]
        .strip()
        .split("|")
    ]

    if (
        len(parts) < 3
        or not parts[0].isdigit()
    ):
        await update.message.reply_text(
            (
                "Format:\n"
                "`/edit ID | Nama | Harga | "
                "Deskripsi | Stok`"
            ),
            parse_mode="Markdown"
        )
        return

    pid = int(parts[0])
    name = parts[1]
    price = parts[2]

    desc = (
        parts[3]
        if len(parts) > 3
        else ""
    )

    stock = (
        int(parts[4])
        if len(parts) > 4
        and parts[4].lstrip("-").isdigit()
        else -1
    )

    con = db()

    cur = con.execute(
        """
        UPDATE products
        SET
            name=?,
            price=?,
            description=?,
            stock=?
        WHERE id=?
        """,
        (
            name,
            price,
            desc,
            stock,
            pid
        )
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        (
            "✏️ Produk berhasil diedit."
            if cur.rowcount
            else "❌ Produk tidak ditemukan."
        )
    )


async def admin_setpayment(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    value = update.message.text.partition(" ")[2].strip()

    if not value:
        await update.message.reply_text(
            (
                "Format:\n"
                "`/setpayment QRIS: xxx | "
                "DANA: xxx | Bank: xxx`"
            ),
            parse_mode="Markdown"
        )
        return

    set_payment(value)

    await update.message.reply_text(
        "✅ Info pembayaran berhasil disimpan."
    )


async def adminpanel(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    await update.message.reply_text(
        "👑 *Admin Panel*",
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN belum diisi."
        )

    db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("add", admin_add)
    )

    app.add_handler(
        CommandHandler("products", admin_products)
    )

    app.add_handler(
        CommandHandler("delete", admin_delete)
    )

    app.add_handler(
        CommandHandler("edit", admin_edit)
    )

    app.add_handler(
        CommandHandler("setpayment", admin_setpayment)
    )

    app.add_handler(
        CommandHandler("admin", adminpanel)
    )

    app.add_handler(
        CommandHandler("id", show_chat_id)
    )

    app.add_handler(
        CommandHandler("bc", admin_broadcast)
    )

    app.add_handler(
        CommandHandler("stats", admin_stats_cmd)
    )

    app.add_handler(
        CommandHandler("cek", check_order_cmd)
    )

    app.add_handler(
        CommandHandler("cancel", cancel)
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            admin_photo
        )
    )

    # Dipakai untuk fitur search.
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            search_message
        )
    )

    app.add_handler(
        CallbackQueryHandler(callback)
    )

    app.run_polling()


if __name__ == "__main__":
    main()