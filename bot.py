import os, sqlite3, logging, re, shutil, zipfile
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

TOKEN = os.getenv('BOT_TOKEN', '')
REQUIRED_CHAT = os.getenv('REQUIRED_CHAT', '')
ADMIN_IDS = {int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()}
ADMIN_GROUP_ID = os.getenv('ADMIN_GROUP_ID', '').strip()
SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME', '')
DB = 'store.db'

logging.basicConfig(level=logging.INFO)

STATUS_TEXT = {
    'pending_payment': 'Menunggu pembayaran',
    'proof_received': 'Bukti diterima',
    'processing': 'Sedang diproses',
    'paid': 'Pembayaran dikonfirmasi',
    'rejected': 'Ditolak',
    'completed': 'Selesai',
}


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row

    c.execute('''
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price TEXT NOT NULL,
            description TEXT DEFAULT '',
            photo TEXT DEFAULT '',
            stock INTEGER DEFAULT -1,
            delivery_text TEXT DEFAULT '',
            delivery_file_id TEXT DEFAULT ''
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            status TEXT DEFAULT 'pending_payment',
            quantity INTEGER DEFAULT 1,
            total_price TEXT DEFAULT '',
            voucher_code TEXT DEFAULT '',
            payment_method TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS cart(
            user_id INTEGER,
            product_id INTEGER,
            quantity INTEGER DEFAULT 1,
            PRIMARY KEY(user_id,product_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS vouchers(
            code TEXT PRIMARY KEY,
            discount_percent INTEGER DEFAULT 0,
            stock INTEGER DEFAULT -1,
            active INTEGER DEFAULT 1
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    ''')

    for sql in [
        "ALTER TABLE products ADD COLUMN delivery_text TEXT DEFAULT ''",
        "ALTER TABLE products ADD COLUMN delivery_file_id TEXT DEFAULT ''",
        "ALTER TABLE orders ADD COLUMN quantity INTEGER DEFAULT 1",
        "ALTER TABLE orders ADD COLUMN total_price TEXT DEFAULT ''",
        "ALTER TABLE orders ADD COLUMN voucher_code TEXT DEFAULT ''",
        "ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT ''",
    ]:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass

    c.commit()
    return c


def setting(k, default=''):
    c = db()

    r = c.execute(
        'SELECT value FROM settings WHERE key=?',
        (k,)
    ).fetchone()

    c.close()

    return r['value'] if r and r['value'] else default


def set_setting(k, v):
    c = db()

    c.execute(
        '''
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        ''',
        (k, v)
    )

    c.commit()
    c.close()


def store_name():
    return setting('store_name', 'My Store')


def payment_value(method):
    return setting(
        f'payment_{method.lower()}',
        ''
    )


def money_number(value):
    try:
        return int(
            re.sub(
                r'[^0-9]',
                '',
                str(value)
            ) or 0
        )
    except Exception:
        return 0


def format_money(value):
    try:
        return f"Rp{int(value):,}".replace(',', '.')
    except Exception:
        return str(value)


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '🛒 Katalog',
                callback_data='catalog'
            ),
            InlineKeyboardButton(
                '🔎 Cari',
                callback_data='search'
            )
        ],
        [
            InlineKeyboardButton(
                '🧺 Keranjang',
                callback_data='cart'
            )
        ],
        [
            InlineKeyboardButton(
                '📦 Pesanan Saya',
                callback_data='orders'
            ),
            InlineKeyboardButton(
                '💳 Pembayaran',
                callback_data='payment'
            )
        ],
        [
            InlineKeyboardButton(
                '👨‍💻 Contact Admin',
                callback_data='support'
            )
        ]
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '🛒 Produk',
                callback_data='adminlist'
            ),
            InlineKeyboardButton(
                '📦 Order',
                callback_data='adminorders'
            )
        ],
        [
            InlineKeyboardButton(
                '💳 Metode Pembayaran',
                callback_data='adminpayment'
            )
        ],
        [
            InlineKeyboardButton(
                '🏪 Nama Store',
                callback_data='adminstore'
            )
        ],
        [
            InlineKeyboardButton(
                '💾 Backup Data',
                callback_data='backup'
            )
        ],
        [
            InlineKeyboardButton(
                '📊 Statistik',
                callback_data='adminstats'
            )
        ]
    ])


def payment_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '💙 DANA',
                callback_data='paymethod:DANA'
            ),
            InlineKeyboardButton(
                '💚 GO-PAY',
                callback_data='paymethod:GOPAY'
            )
        ],
        [
            InlineKeyboardButton(
                '🟦 QRIS',
                callback_data='paymethod:QRIS'
            )
        ],
        [
            InlineKeyboardButton(
                '⬅️ Kembali',
                callback_data='home'
            )
        ]
    ])


def admin_payment_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '💙 Atur DANA',
                callback_data='setpay:DANA'
            ),
            InlineKeyboardButton(
                '💚 Atur GO-PAY',
                callback_data='setpay:GOPAY'
            )
        ],
        [
            InlineKeyboardButton(
                '🟦 Upload QRIS',
                callback_data='uploadqris'
            )
        ],
        [
            InlineKeyboardButton(
                '⬅️ Admin Panel',
                callback_data='adminhome'
            )
        ]
    ])


def order_admin_buttons(oid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '⚙️ PROSES',
                callback_data=f'setstatus:processing:{oid}'
            )
        ],
        [
            InlineKeyboardButton(
                '✅ APPROVED',
                callback_data=f'setstatus:paid:{oid}'
            ),
            InlineKeyboardButton(
                '❌ REJECT',
                callback_data=f'setstatus:rejected:{oid}'
            )
        ],
        [
            InlineKeyboardButton(
                '🏁 SELESAI',
                callback_data=f'setstatus:completed:{oid}'
            )
        ]
    ])


def order_user_buttons(oid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '💳 Pilih Pembayaran',
                callback_data=f'choosepay:{oid}'
            )
        ],
        [
            InlineKeyboardButton(
                '📤 Kirim Bukti Pembayaran',
                callback_data=f'proofhelp:{oid}'
            )
        ],
        [
            InlineKeyboardButton(
                '⬅️ Menu',
                callback_data='home'
            )
        ]
    ])


async def safe_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


async def joined(update, context):
    if not REQUIRED_CHAT:
        return True

    try:
        member = await context.bot.get_chat_member(
            REQUIRED_CHAT,
            update.effective_user.id
        )

        return member.status in (
            'member',
            'administrator',
            'creator'
        )

    except Exception:
        return False


async def replace_home(chat_id, context, text=None):
    old_id = context.user_data.get('last_menu_id')

    if old_id:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=old_id
            )
        except Exception:
            pass

    text = text or (
        f'🔥 *{store_name()}*\n\n'
        'Selamat datang! Pilih menu di bawah.'
    )

    msg = await context.bot.send_message(
        chat_id,
        text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

    context.user_data['last_menu_id'] = msg.message_id

    return msg


async def start(update, context):
    uid = update.effective_user.id
    username = update.effective_user.username or ''

    c = db()

    c.execute(
        '''
        INSERT INTO users(user_id,username)
        VALUES(?,?)
        ON CONFLICT(user_id)
        DO UPDATE SET username=excluded.username
        ''',
        (uid, username)
    )

    c.commit()
    c.close()

    await safe_delete(update.message)

    if not await joined(update, context):
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    '🔗 JOIN GRUP',
                    url=f"https://t.me/{REQUIRED_CHAT.lstrip('@')}"
                )
            ],
            [
                InlineKeyboardButton(
                    '✅ SUDAH JOIN',
                    callback_data='checkjoin'
                )
            ]
        ])

        msg = await context.bot.send_message(
            uid,
            (
                f'🔒 *{store_name()}*\n\n'
                'Silakan join grup terlebih dahulu.'
            ),
            parse_mode='Markdown',
            reply_markup=kb
        )

        context.user_data['last_menu_id'] = msg.message_id
        return

    await replace_home(uid, context)


async def notify_admins(
    context,
    text,
    reply_markup=None,
    photo=None
):
    for admin_id in ADMIN_IDS:
        try:
            if photo:
                await context.bot.send_photo(
                    admin_id,
                    photo=photo,
                    caption=text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    admin_id,
                    text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
        except Exception:
            logging.exception(
                'Failed notifying admin %s',
                admin_id
            )

    if ADMIN_GROUP_ID:
        try:
            if photo:
                await context.bot.send_photo(
                    ADMIN_GROUP_ID,
                    photo=photo,
                    caption=text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:
                await context.bot.send_message(
                    ADMIN_GROUP_ID,
                    text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
        except Exception:
            logging.exception(
                'Failed notifying admin group'
            )


def cart_items(uid):
    c = db()

    rows = c.execute(
        '''
        SELECT
            c.product_id,
            c.quantity,
            p.name,
            p.price,
            p.stock,
            p.description,
            p.photo,
            p.delivery_text,
            p.delivery_file_id
        FROM cart c
        JOIN products p
          ON p.id=c.product_id
        WHERE c.user_id=?
        ORDER BY p.id DESC
        ''',
        (uid,)
    ).fetchall()

    c.close()

    return rows


def product_available(c, pid, quantity):
    row = c.execute(
        'SELECT stock FROM products WHERE id=?',
        (pid,)
    ).fetchone()

    if not row:
        return False

    stock = row['stock']

    return stock < 0 or stock >= quantity


def cart_keyboard(rows):
    kb = []

    for row in rows:
        kb.append([
            InlineKeyboardButton(
                '➖',
                callback_data=f'cartminus:{row["product_id"]}'
            ),
            InlineKeyboardButton(
                f'{row["name"]} × {row["quantity"]}',
                callback_data='noop'
            ),
            InlineKeyboardButton(
                '➕',
                callback_data=f'cartplus:{row["product_id"]}'
            )
        ])

    if rows:
        kb.append([
            InlineKeyboardButton(
                '🗑️ Kosongkan',
                callback_data='cartclear'
            ),
            InlineKeyboardButton(
                '💳 Checkout',
                callback_data='checkout'
            )
        ])

    kb.append([
        InlineKeyboardButton(
            '⬅️ Menu',
            callback_data='home'
        )
    ])

    return InlineKeyboardMarkup(kb)


def cart_text(rows):
    if not rows:
        return '🧺 *Keranjang masih kosong.*'

    total = 0
    lines = []

    for row in rows:
        price = money_number(row['price'])
        subtotal = price * row['quantity']
        total += subtotal

        lines.append(
            f'• {row["name"]} × {row["quantity"]} '
            f'— {format_money(subtotal)}'
        )

    return (
        '🧺 *KERANJANG*\n\n'
        + '\n'.join(lines)
        + f'\n\n💰 *Total:* {format_money(total)}'
    )


async def show_cart(update, context):
    uid = update.effective_user.id
    rows = cart_items(uid)

    text = cart_text(rows)
    kb = cart_keyboard(rows)

    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text,
                parse_mode='Markdown',
                reply_markup=kb
            )
            return
        except Exception:
            pass

    await context.bot.send_message(
        uid,
        text,
        parse_mode='Markdown',
        reply_markup=kb
    )


def create_single_order(uid, pid):
    c = db()

    product = c.execute(
        '''
        SELECT *
        FROM products
        WHERE id=?
        ''',
        (pid,)
    ).fetchone()

    if not product:
        c.close()
        return None, 'Produk tidak ditemukan.'

    if product['stock'] == 0:
        c.close()
        return None, 'Stok produk habis.'

    if product['stock'] > 0:
        c.execute(
            '''
            UPDATE products
            SET stock=stock-1
            WHERE id=?
            ''',
            (pid,)
        )

    cur = c.execute(
        '''
        INSERT INTO orders(
            user_id,
            product_id,
            quantity,
            total_price,
            status
        )
        VALUES(?,?,?,?,?)
        ''',
        (
            uid,
            pid,
            1,
            product['price'],
            'pending_payment'
        )
    )

    oid = cur.lastrowid

    c.commit()
    c.close()

    return oid, None


def create_cart_order(uid):
    c = db()

    rows = c.execute(
        '''
        SELECT
            c.product_id,
            c.quantity,
            p.name,
            p.price,
            p.stock
        FROM cart c
        JOIN products p
          ON p.id=c.product_id
        WHERE c.user_id=?
        ''',
        (uid,)
    ).fetchall()

    if not rows:
        c.close()
        return None, 'Keranjang kosong.'

    for row in rows:
        if not product_available(
            c,
            row['product_id'],
            row['quantity']
        ):
            c.close()
            return None, (
                f'Stok {row["name"]} tidak cukup.'
            )

    first = rows[0]

    total = sum(
        money_number(row['price']) * row['quantity']
        for row in rows
    )

    if len(rows) == 1:
        product_id = first['product_id']
        quantity = first['quantity']
    else:
        product_id = first['product_id']
        quantity = sum(
            row['quantity']
            for row in rows
        )

    cur = c.execute(
        '''
        INSERT INTO orders(
            user_id,
            product_id,
            quantity,
            total_price,
            status
        )
        VALUES(?,?,?,?,?)
        ''',
        (
            uid,
            product_id,
            quantity,
            format_money(total),
            'pending_payment'
        )
    )

    oid = cur.lastrowid

    for row in rows:
        if row['stock'] > 0:
            c.execute(
                '''
                UPDATE products
                SET stock=stock-?
                WHERE id=?
                ''',
                (
                    row['quantity'],
                    row['product_id']
                )
            )

    c.execute(
        'DELETE FROM cart WHERE user_id=?',
        (uid,)
    )

    c.commit()
    c.close()

    return oid, None


async def order_info(
    uid,
    context,
    oid
):
    c = db()

    row = c.execute(
        '''
        SELECT
            o.id,
            o.user_id,
            o.product_id,
            o.quantity,
            o.total_price,
            o.status,
            o.payment_method,
            o.created_at,
            p.name,
            p.price
        FROM orders o
        JOIN products p
          ON p.id=o.product_id
        WHERE o.id=?
        ''',
        (oid,)
    ).fetchone()

    c.close()

    if not row:
        return

    username = (
        context.user_data.get('username')
        or ''
    )

    text = (
        f'🧾 *ORDER {store_name()}*\n\n'
        f'🆔 No. Transaksi: `ORD-{row["id"]:05d}`\n'
        f'📦 Produk: {row["name"]}\n'
        f'🔢 Qty: {row["quantity"]}\n'
        f'💰 Total: {row["total_price"] or row["price"]}\n'
        f'📌 Status: '
        f'*{STATUS_TEXT.get(row["status"], row["status"])}*\n'
        f'🕐 Tanggal: {row["created_at"]}'
    )

    await context.bot.send_message(
        uid,
        text,
        parse_mode='Markdown',
        reply_markup=order_user_buttons(oid)
    )


async def catalog(update, context):
    c = db()

    rows = c.execute(
        '''
        SELECT *
        FROM products
        ORDER BY id DESC
        '''
    ).fetchall()

    c.close()

    if not rows:
        text = '🛒 *KATALOG*\n\nBelum ada produk.'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('⬅️ Menu', callback_data='home')]
        ])
    else:
        text = f'🛒 *KATALOG {store_name()}*\n\n'
        buttons = []

        for row in rows:
            stock = (
                '∞'
                if row['stock'] < 0
                else str(row['stock'])
            )

            text += (
                f'📦 *{row["name"]}*\n'
                f'💰 {row["price"]}\n'
                f'📦 Stok: {stock}\n'
            )

            if row['description']:
                text += f'_{row["description"]}_\n'

            text += '\n'

            buttons.append([
                InlineKeyboardButton(
                    f'🛒 {row["name"]}',
                    callback_data=f'product:{row["id"]}'
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                '⬅️ Menu',
                callback_data='home'
            )
        ])

        kb = InlineKeyboardMarkup(buttons)

    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text,
                parse_mode='Markdown',
                reply_markup=kb
            )
            return
        except Exception:
            pass

    await context.bot.send_message(
        update.effective_user.id,
        text,
        parse_mode='Markdown',
        reply_markup=kb
    )


async def product_detail(update, context, pid):
    c = db()

    row = c.execute(
        'SELECT * FROM products WHERE id=?',
        (pid,)
    ).fetchone()

    c.close()

    if not row:
        await update.callback_query.answer(
            'Produk tidak ditemukan.',
            show_alert=True
        )
        return

    stock = (
        '∞'
        if row['stock'] < 0
        else str(row['stock'])
    )

    text = (
        f'📦 *{row["name"]}*\n\n'
        f'💰 Harga: *{row["price"]}*\n'
        f'📦 Stok: *{stock}*\n\n'
        f'{row["description"] or "Tidak ada deskripsi."}'
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '🛒 Tambah Keranjang',
                callback_data=f'addcart:{pid}'
            )
        ],
        [
            InlineKeyboardButton(
                '⚡ Beli Sekarang',
                callback_data=f'buy:{pid}'
            )
        ],
        [
            InlineKeyboardButton(
                '⬅️ Katalog',
                callback_data='catalog'
            )
        ]
    ])

    if row['photo']:
        try:
            await context.bot.send_photo(
                update.effective_user.id,
                photo=row['photo'],
                caption=text,
                parse_mode='Markdown',
                reply_markup=kb
            )
            return
        except Exception:
            pass

    await update.callback_query.message.edit_text(
        text,
        parse_mode='Markdown',
        reply_markup=kb
    )


async def add_cart(update, context, pid):
    uid = update.effective_user.id

    c = db()

    row = c.execute(
        'SELECT stock,name FROM products WHERE id=?',
        (pid,)
    ).fetchone()

    if not row:
        c.close()
        await update.callback_query.answer(
            'Produk tidak ditemukan.',
            show_alert=True
        )
        return

    existing = c.execute(
        '''
        SELECT quantity
        FROM cart
        WHERE user_id=? AND product_id=?
        ''',
        (uid, pid)
    ).fetchone()

    qty = (existing['quantity'] if existing else 0) + 1

    if row['stock'] >= 0 and qty > row['stock']:
        c.close()
        await update.callback_query.answer(
            'Stok tidak mencukupi.',
            show_alert=True
        )
        return

    c.execute(
        '''
        INSERT INTO cart(user_id,product_id,quantity)
        VALUES(?,?,?)
        ON CONFLICT(user_id,product_id)
        DO UPDATE SET quantity=excluded.quantity
        ''',
        (uid, pid, qty)
    )

    c.commit()
    c.close()

    await update.callback_query.answer(
        '✅ Ditambahkan ke keranjang.'
    )


async def buy_now(update, context, pid):
    uid = update.effective_user.id

    oid, error = create_single_order(
        uid,
        pid
    )

    if error:
        await update.callback_query.answer(
            error,
            show_alert=True
        )
        return

    await update.callback_query.answer(
        'Order dibuat.'
    )

    await show_payment_for_order(
        update,
        context,
        oid
    )


async def show_payment_for_order(
    update,
    context,
    oid
):
    uid = update.effective_user.id

    text = (
        f'💳 *PEMBAYARAN*\n\n'
        f'🧾 Order: `ORD-{oid:05d}`\n\n'
        'Silakan pilih metode pembayaran:'
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '💙 DANA',
                callback_data=f'choosemethod:DANA:{oid}'
            ),
            InlineKeyboardButton(
                '💚 GO-PAY',
                callback_data=f'choosemethod:GOPAY:{oid}'
            )
        ],
        [
            InlineKeyboardButton(
                '🟦 QRIS',
                callback_data=f'choosemethod:QRIS:{oid}'
            )
        ],
        [
            InlineKeyboardButton(
                '⬅️ Menu',
                callback_data='home'
            )
        ]
    ])

    try:
        await update.callback_query.message.edit_text(
            text,
            parse_mode='Markdown',
            reply_markup=kb
        )
    except Exception:
        await context.bot.send_message(
            uid,
            text,
            parse_mode='Markdown',
            reply_markup=kb
        )


async def select_payment(
    update,
    context,
    method,
    oid
):
    uid = update.effective_user.id

    method_key = method.upper()

    c = db()

    order = c.execute(
        'SELECT * FROM orders WHERE id=? AND user_id=?',
        (oid, uid)
    ).fetchone()

    c.close()

    if not order:
        await update.callback_query.answer(
            'Order tidak ditemukan.',
            show_alert=True
        )
        return

    payment_info = payment_value(
        'GOPAY'
        if method_key == 'GOPAY'
        else method_key
    )

    if method_key == 'QRIS':
        qris = payment_value('QRIS')

        if not qris:
            await update.callback_query.answer(
                'QRIS belum diatur admin.',
                show_alert=True
            )
            return

        try:
            await context.bot.send_photo(
                uid,
                photo=qris,
                caption=(
                    f'🟦 *PEMBAYARAN QRIS*\n\n'
                    f'🧾 Order: `ORD-{oid:05d}`\n'
                    f'💰 Total: {order["total_price"]}\n\n'
                    'Setelah pembayaran, kirim *bukti pembayaran '
                    'berupa foto* di chat ini.'
                ),
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            '📤 Kirim Bukti',
                            callback_data=f'proofhelp:{oid}'
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            '⬅️ Menu',
                            callback_data='home'
                        )
                    ]
                ])
            )
        except Exception:
            await context.bot.send_message(
                uid,
                (
                    f'🟦 *QRIS*\n\n'
                    f'Order: `ORD-{oid:05d}`\n'
                    f'Total: {order["total_price"]}\n\n'
                    'QRIS gagal ditampilkan. Hubungi admin.'
                ),
                parse_mode='Markdown'
            )

    else:
        if not payment_info:
            await update.callback_query.answer(
                'Metode pembayaran ini belum diatur admin.',
                show_alert=True
            )
            return

        await context.bot.send_message(
            uid,
            (
                f'💳 *PEMBAYARAN {method_key}*\n\n'
                f'🧾 Order: `ORD-{oid:05d}`\n'
                f'💰 Total: {order["total_price"]}\n\n'
                f'📱 Nomor/Akun:\n`{payment_info}`\n\n'
                'Setelah pembayaran, kirim *bukti pembayaran '
                'berupa foto* di chat ini.'
            ),
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        '📤 Kirim Bukti',
                        callback_data=f'proofhelp:{oid}'
                    )
                ]
            ])
        )

    c = db()

    c.execute(
        '''
        UPDATE orders
        SET payment_method=?
        WHERE id=?
        ''',
        (method_key, oid)
    )

    c.commit()
    c.close()

    context.user_data['proof_order_id'] = oid


async def proof_help(update, context, oid):
    uid = update.effective_user.id

    context.user_data['proof_order_id'] = oid

    await update.callback_query.answer()

    await context.bot.send_message(
        uid,
        (
            f'📤 *UPLOAD BUKTI PEMBAYARAN*\n\n'
            f'Order: `ORD-{oid:05d}`\n\n'
            'Silakan kirim foto/screenshot bukti pembayaran '
            'sebagai *foto*, bukan teks.\n\n'
            'Setelah diterima, bukti akan otomatis dikirim '
            'ke admin dan grup notifikasi.'
        ),
        parse_mode='Markdown'
    )


async def receive_proof(update, context):
    uid = update.effective_user.id

    if not update.message or not update.message.photo:
        return

    oid = context.user_data.get('proof_order_id')

    if not oid:
        await update.message.reply_text(
            '⚠️ Pilih order terlebih dahulu, lalu pilih '
            'Upload Bukti Pembayaran.'
        )
        return

    c = db()

    order = c.execute(
        '''
        SELECT
            o.*,
            p.name
        FROM orders o
        LEFT JOIN products p
          ON p.id=o.product_id
        WHERE o.id=? AND o.user_id=?
        ''',
        (oid, uid)
    ).fetchone()

    c.close()

    if not order:
        await update.message.reply_text(
            '❌ Order tidak ditemukan.'
        )
        return

    username = (
        f'@{update.effective_user.username}'
        if update.effective_user.username
        else '(tanpa username)'
    )

    now = datetime.now().strftime(
        '%d-%m-%Y %H:%M:%S'
    )

    caption = (
        f'💰 *BUKTI PEMBAYARAN MASUK*\n\n'
        f'🧾 No. ID: `ORD-{oid:05d}`\n'
        f'👤 Telegram ID: `{uid}`\n'
        f'🔗 Username: {username}\n'
        f'📅 Tanggal: `{now}`\n'
        f'📦 Produk: {order["name"] or "-"}\n'
        f'🔢 Qty: {order["quantity"]}\n'
        f'💰 Total: {order["total_price"] or "-"}\n'
        f'💳 Metode: {order["payment_method"] or "-"}\n'
        f'📌 Status: *Bukti diterima*'
    )

    c = db()

    c.execute(
        '''
        UPDATE orders
        SET status='proof_received'
        WHERE id=?
        ''',
        (oid,)
    )

    c.commit()
    c.close()

    photo_id = update.message.photo[-1].file_id

    await notify_admins(
        context,
        caption,
        reply_markup=order_admin_buttons(oid),
        photo=photo_id
    )

    await update.message.reply_text(
        (
            '✅ *BUKTI TERKIRIM*\n\n'
            f'Order `ORD-{oid:05d}` sudah diterima.\n'
            'Admin akan memverifikasi pembayaran kamu.'
        ),
        parse_mode='Markdown',
        reply_markup=main_menu()
    )

    context.user_data.pop(
        'proof_order_id',
        None
    )


async def show_orders(update, context):
    uid = update.effective_user.id

    c = db()

    rows = c.execute(
        '''
        SELECT
            o.id,
            o.total_price,
            o.status,
            o.payment_method,
            o.created_at,
            p.name
        FROM orders o
        LEFT JOIN products p
          ON p.id=o.product_id
        WHERE o.user_id=?
        ORDER BY o.id DESC
        LIMIT 20
        ''',
        (uid,)
    ).fetchall()

    c.close()

    if not rows:
        text = '📦 *PESANAN SAYA*\n\nBelum ada pesanan.'
    else:
        lines = [
            '📦 *PESANAN SAYA*\n'
        ]

        for row in rows:
            lines.append(
                f'🧾 `ORD-{row["id"]:05d}`\n'
                f'📦 {row["name"] or "-"}\n'
                f'💰 {row["total_price"] or "-"}\n'
                f'💳 {row["payment_method"] or "-"}\n'
                f'📌 {STATUS_TEXT.get(row["status"], row["status"])}\n'
                f'🕐 {row["created_at"]}\n'
            )

        text = '\n'.join(lines)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '⬅️ Menu',
                callback_data='home'
            )
        ]
    ])

    try:
        await update.callback_query.message.edit_text(
            text,
            parse_mode='Markdown',
            reply_markup=kb
        )
    except Exception:
        await context.bot.send_message(
            uid,
            text,
            parse_mode='Markdown',
            reply_markup=kb
        )


async def admin_panel(update, context):
    uid = update.effective_user.id

    if uid not in ADMIN_IDS:
        await update.callback_query.answer(
            'Akses ditolak.',
            show_alert=True
        )
        return

    await update.callback_query.message.edit_text(
        (
            f'⚙️ *ADMIN PANEL*\n\n'
            f'🏪 Store: *{store_name()}*\n\n'
            'Pilih menu admin:'
        ),
        parse_mode='Markdown',
        reply_markup=admin_menu()
    )


async def admin_products(update, context):
    uid = update.effective_user.id

    if uid not in ADMIN_IDS:
        return

    c = db()

    rows = c.execute(
        'SELECT * FROM products ORDER BY id DESC'
    ).fetchall()

    c.close()

    if not rows:
        text = '📦 Belum ada produk.'
    else:
        text = '📦 *DAFTAR PRODUK*\n\n'

        for row in rows:
            text += (
                f'#{row["id"]} — *{row["name"]}*\n'
                f'Harga: {row["price"]}\n'
                f'Stok: {row["stock"]}\n\n'
            )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                '➕ Tambah Produk',
                callback_data='addproduct'
            )
        ],
        [
            InlineKeyboardButton(
                '⬅️ Admin Panel',
                callback_data='adminhome'
            )
        ]
    ])

    await update.callback_query.message.edit_text(
        text,
        parse_mode='Markdown',
        reply_markup=kb
    )


async def admin_orders(update, context):
    uid = update.effective_user.id

    if uid not in ADMIN_IDS:
        return

    c = db()

    rows = c.execute(
        '''
        SELECT
            o.id,
            o.user_id,
            o.quantity,
            o.total_price,
            o.status,
            o.payment_method,
            o.created_at,
            p.name
        FROM orders o
        LEFT JOIN products p
          ON p.id=o.product_id
        ORDER BY o.id DESC
        LIMIT 30
        '''
    ).fetchall()

    c.close()

    if not rows:
        text = '📦 Belum ada order.'
    else:
        text = '📦 *ORDER TERBARU*\n\n'

        for row in rows:
            text += (
                f'🧾 `ORD-{row["id"]:05d}`\n'
                f'👤 `{row["user_id"]}`\n'
                f'📦 {row["name"] or "-"}\n'
                f'💰 {row["total_price"] or "-"}\n'
                f'💳 {row["payment_method"] or "-"}\n'
                f'📌 {STATUS_TEXT.get(row["status"], row["status"])}\n'
                f'🕐 {row["created_at"]}\n\n'
            )

    await update.callback_query.message.edit_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    '⬅️ Admin Panel',
                    callback_data='adminhome'
                )
            ]
        ])
    )


async def admin_payment(update, context):
    uid = update.effective_user.id

    if uid not in ADMIN_IDS:
        return

    dana = payment_value('DANA')
    gopay = payment_value('GOPAY')
    qris = payment_value('QRIS')

    text = (
        '💳 *METODE PEMBAYARAN*\n\n'
        f'💙 DANA: `{dana or "Belum diatur"}`\n'
        f'💚 GO-PAY: `{gopay or "Belum diatur"}`\n'
        f'🟦 QRIS: '
        f'{"✅ Sudah diupload" if qris else "❌ Belum diupload"}\n\n'
        'Pilih metode yang ingin diubah.'
    )

    await update.callback_query.message.edit_text(
        text,
        parse_mode='Markdown',
        reply_markup=admin_payment_menu()
    )


async def admin_store(update, context):
    uid = update.effective_user.id

    if uid not in ADMIN_IDS:
        return

    context.user_data['awaiting_store_name'] = True

    await update.callback_query.message.edit_text(
        (
            '🏪 *EDIT NAMA STORE*\n\n'
            'Kirim nama store baru sekarang.\n\n'
            f'Nama sekarang: *{store_name()}*'
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    '⬅️ Batal',
                    callback_data='adminhome'
                )
            ]
        ])
    )


async def set_payment_prompt(
    update,
    context,
    method
):
    uid = update.effective_user.id

    if uid not in ADMIN_IDS:
        return

    context.user_data['awaiting_payment'] = method

    label = (
        'GO-PAY'
        if method == 'GOPAY'
        else method
    )

    await update.callback_query.message.edit_text(
        (
            f'💳 *ATUR {label}*\n\n'
            f'Kirim nomor / akun {label} sekarang.\n'
            'Contoh: `08123456789`'
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    '⬅️ Batal',
                    callback_data='adminpayment'
                )
            ]
        ])
    )


async def upload_qris_prompt(update, context):
    uid = update.effective_user.id

    if uid not in ADMIN_IDS:
        return

    context.user_data['awaiting_qris'] = True

    await update.callback_query.message.edit_text(
        (
            '🟦 *UPLOAD QRIS*\n\n'
            'Kirim gambar QRIS sebagai foto sekarang.\n'
            'QRIS tersebut akan digunakan user saat memilih '
            'metode pembayaran QRIS.'
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    '⬅️ Batal',
                    callback_data='adminpayment'
                )
            ]
        ])
    )


async def receive_admin_text(update, context):
    uid = update.effective_user.id

    if uid not in ADMIN_IDS:
        return False

    text = (
        update.message.text
        if update.message
        else ''
    ).strip()

    if context.user_data.get('awaiting_store_name'):
        if not text:
            return True

        set_setting(
            'store_name',
            text[:100]
        )

        context.user_data.pop(
            'awaiting_store_name',
            None
        )

        await update.message.reply_text(
            f'✅ Nama store diubah menjadi *{text[:100]}*.',
            parse_mode='Markdown',
            reply_markup=admin_menu()
        )

        return True

    method = context.user_data.get(
        'awaiting_payment'
    )

    if method:
        set_setting(
            f'payment_{method}',
            text[:200]
        )

        context.user_data.pop(
            'awaiting_payment',
            None
        )

        await update.message.reply_text(
            (
                f'✅ Pembayaran {method} berhasil diatur.\n'
                f'Akun: `{text[:200]}`'
            ),
            parse_mode='Markdown',
            reply_markup=admin_payment_menu()
        )

        return True

    if context.user_data.get('awaiting_add_product'):
        parts = [p.strip() for p in text.split('\n') if p.strip()]
        if len(parts) >= 2:
            name = parts[0]
            price = parts[1]
            desc = parts[2] if len(parts) > 2 else ''
            stock = int(parts[3]) if len(parts) > 3 and parts[3].lstrip('-').isdigit() else -1
            delivery_text = parts[4] if len(parts) > 4 else ''

            c = db()
            c.execute(
                '''
                INSERT INTO products(name, price, description, stock, delivery_text)
                VALUES(?,?,?,?,?)
                ''',
                (name, price, desc, stock, delivery_text)
            )
            c.commit()
            c.close()

            context.user_data.pop('awaiting_add_product', None)
            await update.message.reply_text(
                f'✅ Produk *{name}* berhasil ditambahkan!',
                parse_mode='Markdown',
                reply_markup=admin_menu()
            )
            return True
        else:
            await update.message.reply_text(
                '⚠️ Format salah. Sertakan minimal Nama dan Harga (terpisah baris baru).'
            )
            return True

    return False


# --- FITUR PELENGKAP ---

async def check_join(update, context):
    q = update.callback_query
    await q.answer()
    if await joined(update, context):
        await q.message.delete()
        await replace_home(update.effective_user.id, context)
    else:
        await q.answer('⚠️ Kamu belum join grup!', show_alert=True)


async def show_payment_menu(update, context):
    text = (
        '💳 *METODE PEMBAYARAN TERSEDIA*\n\n'
        'Pilih salah satu metode pembayaran di bawah ini:'
    )
    if update.callback_query:
        await update.callback_query.message.edit_text(
            text, parse_mode='Markdown', reply_markup=payment_menu()
        )


async def show_payment_method(update, context, method):
    info = payment_value(method)
    if method == 'QRIS':
        if info:
            try:
                await context.bot.send_photo(
                    update.effective_user.id,
                    photo=info,
                    caption='🟦 *PEMBAYARAN QRIS*\n\nSilakan scan QRIS di atas.',
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton('⬅️ Kembali', callback_data='payment')]
                    ])
                )
                return
            except Exception:
                pass
        await update.callback_query.message.edit_text(
            '❌ QRIS belum dikonfigurasi oleh admin.',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('⬅️ Kembali', callback_data='payment')]
            ])
        )
    else:
        val = info if info else 'Belum diatur oleh admin.'
        await update.callback_query.message.edit_text(
            f'💳 *METODE PEMBAYARAN {method}*\n\nDetail Akun:\n`{val}`',
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('⬅️ Kembali', callback_data='payment')]
            ])
        )


async def support(update, context):
    username = SUPPORT_USERNAME.lstrip('@')
    text = (
        '👨‍💻 *BANTUAN & SUPPORT*\n\n'
        'Jika ada kendala transaksi atau pertanyaan, hubungi admin:'
    )
    kb = []
    if username:
        kb.append([InlineKeyboardButton('💬 Hubungi Admin', url=f'https://t.me/{username}')])
    kb.append([InlineKeyboardButton('⬅️ Menu', callback_data='home')])
    
    await update.callback_query.message.edit_text(
        text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb)
    )


async def search_prompt(update, context):
    context.user_data['searching'] = True
    await update.callback_query.answer()
    await update.callback_query.message.edit_text(
        '🔎 *CARI PRODUK*\n\nKetik kata kunci nama produk yang ingin kamu cari:',
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('⬅️ Batal', callback_data='home')]
        ])
    )


async def do_search(update, context, keyword):
    context.user_data.pop('searching', None)
    c = db()
    rows = c.execute(
        'SELECT * FROM products WHERE name LIKE ? ORDER BY id DESC',
        (f'%{keyword}%',)
    ).fetchall()
    c.close()

    if not rows:
        await update.message.reply_text(
            f'🔎 Tidak ditemukan produk dengan kata kunci: *{keyword}*',
            parse_mode='Markdown',
            reply_markup=main_menu()
        )
        return

    text = f'🔎 *HASIL PENCARIAN:* "{keyword}"\n\n'
    buttons = []
    for row in rows:
        text += f'📦 *{row["name"]}* - {row["price"]}\n'
        buttons.append([InlineKeyboardButton(f'🛒 {row["name"]}', callback_data=f'product:{row["id"]}')])

    buttons.append([InlineKeyboardButton('⬅️ Menu', callback_data='home')])
    await update.message.reply_text(
        text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons)
    )


async def cart_change(update, context, pid, delta):
    uid = update.effective_user.id
    c = db()
    row = c.execute('SELECT quantity FROM cart WHERE user_id=? AND product_id=?', (uid, pid)).fetchone()
    
    if row:
        new_qty = row['quantity'] + delta
        if new_qty <= 0:
            c.execute('DELETE FROM cart WHERE user_id=? AND product_id=?', (uid, pid))
        else:
            if product_available(c, pid, new_qty):
                c.execute('UPDATE cart SET quantity=? WHERE user_id=? AND product_id=?', (new_qty, uid, pid))
            else:
                await update.callback_query.answer('Stok tidak mencukupi.', show_alert=True)
                c.close()
                return
        c.commit()
    c.close()
    await show_cart(update, context)


async def clear_cart(update, context):
    uid = update.effective_user.id
    c = db()
    c.execute('DELETE FROM cart WHERE user_id=?', (uid,))
    c.commit()
    c.close()
    await update.callback_query.answer('Keranjang dikosongkan.')
    await show_cart(update, context)


async def checkout(update, context):
    uid = update.effective_user.id
    oid, error = create_cart_order(uid)
    if error:
        await update.callback_query.answer(error, show_alert=True)
        return

    await update.callback_query.answer('Checkout berhasil.')
    await show_payment_for_order(update, context, oid)


async def set_order_status(update, context, status, oid):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return

    c = db()
    c.execute('UPDATE orders SET status=? WHERE id=?', (status, oid))
    c.commit()
    
    order = c.execute(
        'SELECT o.*, p.name, p.delivery_text, p.delivery_file_id FROM orders o LEFT JOIN products p ON p.id=o.product_id WHERE o.id=?',
        (oid,)
    ).fetchone()
    c.close()

    await update.callback_query.answer(f'Status diubah ke {status}')

    if order:
        user_id = order['user_id']
        st_label = STATUS_TEXT.get(status, status)
        
        # Auto delivery jika status paid/completed
        if status in ('paid', 'completed'):
            msg_text = (
                f'✅ *PESANAN DIKONFIRMASI*\n\n'
                f'Order `ORD-{oid:05d}` telah dikonfirmasi!\n'
                f'Status: *{st_label}*\n\n'
            )
            if order['delivery_text']:
                msg_text += f'📦 *Detail Pengiriman/Item:*\n`{order["delivery_text"]}`\n'

            await context.bot.send_message(user_id, msg_text, parse_mode='Markdown')
            
            if order['delivery_file_id']:
                try:
                    await context.bot.send_document(user_id, document=order['delivery_file_id'])
                except Exception:
                    pass
        else:
            await context.bot.send_message(
                user_id,
                f'ℹ️ Update Order `ORD-{oid:05d}`:\nStatus saat ini: *{st_label}*',
                parse_mode='Markdown'
            )

    await admin_orders(update, context)


async def add_product_prompt(update, context):
    context.user_data['awaiting_add_product'] = True
    await update.callback_query.message.edit_text(
        '➕ *TAMBAH PRODUK BARU*\n\n'
        'Kirim detail produk dengan format per baris:\n'
        '`Nama Produk`\n'
        '`Harga`\n'
        '`Deskripsi` (opsional)\n'
        '`Stok` (angka, opsional, default -1 = tak terbatas)\n'
        '`Teks Auto-Delivery` (opsional)',
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('⬅️ Batal', callback_data='adminlist')]
        ])
    )


async def backup_db(update, context):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return

    backup_filename = f'backup_store_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    shutil.copyfile(DB, backup_filename)
    
    try:
        with open(backup_filename, 'rb') as f:
            await context.bot.send_document(
                chat_id=uid,
                document=f,
                caption=f'💾 *BACKUP DATABASE*\nTanggal: `{datetime.now().strftime("%d-%m-%Y %H:%M:%S")}`',
                parse_mode='Markdown'
            )
    except Exception as e:
        await update.callback_query.answer('Gagal mengirim file backup.', show_alert=True)
    finally:
        if os.path.exists(backup_filename):
            os.remove(backup_filename)


async def admin_stats(update, context):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return

    c = db()
    total_users = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    total_products = c.execute('SELECT COUNT(*) FROM products').fetchone()[0]
    total_orders = c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    completed_orders = c.execute("SELECT COUNT(*) FROM orders WHERE status IN ('paid', 'completed')").fetchone()[0]
    c.close()

    text = (
        '📊 *STATISTIK BOT*\n\n'
        f'👥 Total Pengguna: *{total_users}*\n'
        f'📦 Total Produk: *{total_products}*\n'
        f'🧾 Total Order: *{total_orders}*\n'
        f'✅ Order Sukses: *{completed_orders}*'
    )

    await update.callback_query.message.edit_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('⬅️ Admin Panel', callback_data='adminhome')]
        ])
    )


async def receive_text(update, context):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Mode pencarian
    if context.user_data.get('searching'):
        await do_search(update, context, text)
        return

    # Mode admin
    if update.effective_user.id in ADMIN_IDS:
        handled = await receive_admin_text(update, context)
        if handled:
            return

    await update.message.reply_text(
        'Gunakan menu tombol di bawah atau /start.',
        reply_markup=main_menu()
    )


async def admin_command(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text('⛔ Akses ditolak.')
        return

    await update.message.reply_text(
        '⚙️ *ADMIN PANEL*',
        parse_mode='Markdown',
        reply_markup=admin_menu()
    )


async def photo_router(update, context):
    # Foto QRIS dari admin
    if (
        update.effective_user.id in ADMIN_IDS
        and context.user_data.get('awaiting_qris')
    ):
        photo_id = update.message.photo[-1].file_id

        set_setting(
            'QRIS',
            photo_id
        )

        context.user_data.pop(
            'awaiting_qris',
            None
        )

        await update.message.reply_text(
            '✅ QRIS berhasil disimpan.',
            reply_markup=admin_payment_menu()
        )

        return

    # Bukti pembayaran user
    await receive_proof(update, context)


async def callback_router(update, context):
    q = update.callback_query
    data = q.data or ''

    if data == 'home':
        await q.answer()
        await replace_home(
            update.effective_user.id,
            context
        )

    elif data == 'catalog':
        await q.answer()
        await catalog(update, context)

    elif data == 'cart':
        await q.answer()
        await show_cart(update, context)

    elif data == 'payment':
        await q.answer()
        await show_payment_menu(update, context)

    elif data == 'orders':
        await q.answer()
        await show_orders(update, context)

    elif data == 'support':
        await q.answer()
        await support(update, context)

    elif data == 'checkjoin':
        await check_join(update, context)

    elif data == 'search':
        await search_prompt(update, context)

    elif data.startswith('product:'):
        pid = int(data.split(':')[1])
        await q.answer()
        await product_detail(update, context, pid)

    elif data.startswith('addcart:'):
        pid = int(data.split(':')[1])
        await add_cart(update, context, pid)

    elif data.startswith('buy:'):
        pid = int(data.split(':')[1])
        await buy_now(update, context, pid)

    elif data.startswith('choosepay:'):
        oid = int(data.split(':')[1])
        await q.answer()
        await show_payment_for_order(
            update,
            context,
            oid
        )

    elif data.startswith('choosemethod:'):
        _, method, oid = data.split(':')
        await select_payment(
            update,
            context,
            method,
            int(oid)
        )

    elif data.startswith('proofhelp:'):
        oid = int(data.split(':')[1])
        await proof_help(
            update,
            context,
            oid
        )

    elif data.startswith('paymethod:'):
        method = data.split(':')[1]
        await q.answer()
        await show_payment_method(
            update,
            context,
            method
        )

    # CART
    elif data.startswith('cartplus:'):
        pid = int(data.split(':')[1])
        await cart_change(
            update,
            context,
            pid,
            1
        )

    elif data.startswith('cartminus:'):
        pid = int(data.split(':')[1])
        await cart_change(
            update,
            context,
            pid,
            -1
        )

    elif data == 'cartclear':
        await clear_cart(update, context)

    elif data == 'checkout':
        await checkout(update, context)

    # ADMIN
    elif data == 'adminhome':
        await q.answer()
        await admin_panel(update, context)

    elif data == 'adminlist':
        await q.answer()
        await admin_products(update, context)

    elif data == 'adminorders':
        await q.answer()
        await admin_orders(update, context)

    elif data == 'adminpayment':
        await q.answer()
        await admin_payment(update, context)

    elif data == 'adminstore':
        await q.answer()
        await admin_store(update, context)

    elif data == 'backup':
        await q.answer()
        await backup_db(update, context)

    elif data == 'adminstats':
        await q.answer()
        await admin_stats(update, context)

    elif data == 'addproduct':
        await q.answer()
        await add_product_prompt(
            update,
            context
        )

    elif data.startswith('setpay:'):
        method = data.split(':')[1]
        await q.answer()
        await set_payment_prompt(
            update,
            context,
            method
        )

    elif data == 'uploadqris':
        await q.answer()
        await upload_qris_prompt(
            update,
            context
        )

    elif data.startswith('setstatus:'):
        _, status, oid = data.split(':')
        await set_order_status(
            update,
            context,
            status,
            int(oid)
        )

    elif data == 'noop':
        await q.answer()


def main():
    if not TOKEN:
        raise RuntimeError(
            'BOT_TOKEN belum diset.'
        )

    # Buat database/tabel
    c = db()
    c.close()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler(
            'start',
            start
        )
    )

    app.add_handler(
        CommandHandler(
            'admin',
            admin_command
        )
    )

    # Semua tombol inline
    app.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # Foto
    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_router
        )
    )

    # Text
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_text
        )
    )

    print(
        f'🔥 {store_name()} BOT RUNNING...'
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == '__main__':
    main()
