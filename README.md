# Telegram Store Bot V1

Fitur awal:
- Wajib join grup sebelum akses
- Auto-check membership
- Katalog produk
- Foto produk
- Order + ID transaksi otomatis
- Riwayat order
- Info pembayaran placeholder
- Contact admin placeholder
- Admin tambah produk
- Admin lihat produk

## Environment Variables

`BOT_TOKEN` = token dari @BotFather  
`REQUIRED_CHAT` = username grup/channel, contoh `@namagrup`  
`ADMIN_IDS` = Telegram user ID admin, contoh `123456789,987654321`

## Penting
Bot harus berada di grup/channel wajib dan punya izin yang diperlukan untuk mengecek member.

Untuk produksi, sebaiknya database diganti ke PostgreSQL/Supabase agar data tidak hilang ketika hosting melakukan redeploy.
