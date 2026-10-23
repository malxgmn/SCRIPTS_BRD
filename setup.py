import subprocess
import threading
import sys
import os
import time
import json
import signal
import random
import urllib.request
import urllib.error
import ssl
import sqlite3

def migrate_all_sessions_to_wal(sessions_dir):
    """Aktifkan WAL mode untuk seluruh file .session yang ada di folder sessions/"""
    if not os.path.exists(sessions_dir):
        return
    count = 0
    for root, _, files in os.walk(sessions_dir):
        for f in files:
            if f.endswith(".session"):
                fpath = os.path.join(root, f)
                try:
                    with sqlite3.connect(fpath, timeout=5) as conn:
                        conn.execute("PRAGMA journal_mode=WAL;")
                        conn.execute("PRAGMA synchronous=NORMAL;")
                        conn.execute("PRAGMA busy_timeout=30000;")
                    count += 1
                except Exception:
                    pass
    if count > 0:
        print(f"[✔] SQLite WAL mode activated for {count} session databases.")

# Global list to track all spawned subprocesses for clean shutdown
ALL_PROCESSES = []

# Load environment from .env file if exists
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

def run_command(command, cwd=None, name=""):
    print(f"[+] Starting {name}...")
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=cwd,
            shell=False,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        ALL_PROCESSES.append(process)
        threading.Thread(target=log_reader_func, args=(process, name), daemon=True).start()
        return process
    except Exception as e:
        print(f"[!] Error running {name}: {e}")
        return None

def log_reader_func(process, name):
    try:
        for line in process.stdout:
            print(f"[{name}] {line.strip()}")
    except Exception:
        pass

class BotManager:
    def __init__(self, python_exe, scripts_dir):
        self.python_exe = python_exe
        self.scripts_dir = scripts_dir
        self.processes = {}  # {tenant_id: process_object}
        self.spawning_tenants = set()  # Mutex set untuk mencegah duplikasi subprocess bot
        self.running = True
        self.last_config = {}  # {tenant_id: config_hash}
        self.retry_cooldown = {}  # {tenant_id: next_allowed_retry_timestamp}

    def get_config_hash(self, t):
        config_str = f"{t.get('api_id', '')}|{t.get('api_hash', '')}|{t.get('bot_token', '')}|{t.get('admin_ids', '')}"
        return hash(config_str)

    def get_tenants(self):
        # 1. Coba ambil via HTTP Endpoint dari Server 1 (Multi-Server)
        server1_url = os.environ.get("SERVER1_TENANTS_URL", "")
        secret = os.environ.get("INTERNAL_TENANT_SECRET", "")
        if server1_url:
            try:
                sep = '&' if '?' in server1_url else '?'
                full_url = f"{server1_url}{sep}secret={secret}" if secret else server1_url
                req = urllib.request.Request(full_url)
                req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                if secret:
                    req.add_header("X-Internal-Secret", secret)
                
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                with urllib.request.urlopen(req, timeout=25, context=ctx) as response:
                    if response.status == 200:
                        tenants = json.loads(response.read().decode('utf-8'))
                        # Simpan cache lokal untuk emergency fallback jika Server 1 offline
                        cache_file = os.path.join(self.scripts_dir, "json", "tenants_cache.json")
                        try:
                            with open(cache_file, "w", encoding="utf-8") as cf:
                                json.dump(tenants, cf, indent=4)
                        except Exception:
                            pass
                        return tenants
            except Exception as e:
                print(f"[!] Gagal fetch tenants dari Server 1 ({server1_url}): {e}")

        # 2. Fallback ke Cache Lokal jika Server 1 down
        cache_file = os.path.join(self.scripts_dir, "json", "tenants_cache.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as cf:
                    print("[*] Menggunakan data cache tenants lokal...")
                    return json.load(cf)
            except Exception:
                pass

        # 3. Fallback: static settings.py jika ada
        try:
            import settings
            return [{
                'id': 0,
                'api_id': getattr(settings, 'api_id', ''),
                'api_hash': getattr(settings, 'api_hash', ''),
                'bot_token': getattr(settings, 'bot_token', ''),
                'bot_username': getattr(settings, 'bot_username', ''),
                'admin_ids': ",".join(map(str, getattr(settings, 'admin', [])))
            }]
        except Exception:
            pass

        return []

    def spawn_bot(self, t):
        tid = str(t['id'])
        if tid in self.spawning_tenants:
            return
        self.spawning_tenants.add(tid)
        try:
            delay = random.uniform(0.5, 3.0)
            print(f"[*] Queuing Watcher for Tenant {tid} (@{t['bot_username']}) with {delay:.1f}s jitter...")
            time.sleep(delay)
            
            cmd = [
                self.python_exe, "-u", "main.py",
                "--api_id", str(t['api_id']),
                "--api_hash", str(t['api_hash']),
                "--bot_token", str(t['bot_token']),
                "--bot_username", str(t['bot_username']),
                "--admin_ids", str(t['admin_ids']),
                "--tenant_id", tid
            ]
            
            p = subprocess.Popen(
                cmd,
                cwd=self.scripts_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            )
            self.processes[tid] = p
            ALL_PROCESSES.append(p)
            self.last_config[tid] = self.get_config_hash(t)
            
            threading.Thread(
                target=self.log_reader, 
                args=(p, f"BOT_{tid}"), 
                daemon=True
            ).start()
            print(f"[✔] Watcher for Tenant {tid} (@{t['bot_username']}) SPAWNED!")
        except Exception as e:
            print(f"[!] Failed to spawn bot for Tenant {tid}: {e}")
        finally:
            self.spawning_tenants.discard(tid)

    def restart_bot(self, t, reason="config change"):
        tid = str(t['id'])
        old_process = self.processes.get(tid)
        
        if old_process:
            print(f"[*] Restarting Tenant {tid} (@{t['bot_username']}) due to {reason}...")
            try:
                old_process.terminate()
                try:
                    old_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    old_process.kill()
                if old_process in ALL_PROCESSES:
                    ALL_PROCESSES.remove(old_process)
            except Exception as e:
                print(f"[!] Error terminating process for Tenant {tid}: {e}")
        
        self.spawn_bot(t)

    def manage_bots(self):
        print("[+] Bot Manager Thread Started.")
        while self.running:
            tenants = self.get_tenants()
            current_tenant_ids = {str(t['id']) for t in tenants}
            
            # Matikan bot tenant yang sudah dihapus
            for tid in list(self.processes.keys()):
                if tid not in current_tenant_ids:
                    p = self.processes.get(tid)
                    if p and p.poll() is None:
                        print(f"[*] Stopping bot for removed Tenant {tid}...")
                        p.terminate()
                        try:
                            p.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            p.kill()
                        if p in ALL_PROCESSES:
                            ALL_PROCESSES.remove(p)
                    del self.processes[tid]
                    self.last_config.pop(tid, None)
            
            # Spawn atau restart bot yang konfigurasinya berubah
            for t in tenants:
                tid = str(t['id'])
                current_config_hash = self.get_config_hash(t)
                p = self.processes.get(tid)
                config_changed = (tid in self.last_config and self.last_config[tid] != current_config_hash)
                
                if config_changed:
                    if tid not in self.spawning_tenants:
                        # Konfigurasi diubah oleh admin di Admin Panel! Reset cooldown dan restart instan
                        self.retry_cooldown.pop(tid, None)
                        threading.Thread(target=self.restart_bot, args=(t, "config change in admin"), daemon=True).start()
                elif p is None:
                    if tid not in self.spawning_tenants:
                        threading.Thread(target=self.spawn_bot, args=(t,), daemon=True).start()
                elif p.poll() is not None:
                    # Proses bot mati/crash (misal token expired). Terapkan cooldown 3 menit
                    now = time.time()
                    next_retry = self.retry_cooldown.get(tid, 0)
                    if now >= next_retry and tid not in self.spawning_tenants:
                        self.retry_cooldown[tid] = now + 180
                        print(f"[*] Tenant {tid} bot is down. Retrying spawn (cooldown 3m)...")
                        threading.Thread(target=self.spawn_bot, args=(t,), daemon=True).start()
            
            time.sleep(15)

    def log_reader(self, process, name):
        try:
            for line in process.stdout:
                print(f"[{name}] {line.strip()}")
        except Exception:
            pass

def shutdown(signum=None, frame=None):
    print("\n[!] Menangkap Sinyal Kematian. Shutting down CORE Engine...")
    for p in ALL_PROCESSES:
        try:
            if p.poll() is None:
                p.terminate()
        except:
            pass
            
    end_time = time.time() + 3
    for p in ALL_PROCESSES:
        try:
            while p.poll() is None and time.time() < end_time:
                time.sleep(0.1)
            if p.poll() is None:
                p.kill()
        except:
            pass
            
    print("[✔] All CORE systems stopped cleanly.\n")
    os._exit(0)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='MALXGMN SERVER 2 CORE RUNNER (BRD)')
    parser.add_argument('--mode', type=str, choices=['1', '2'], help='1: Local, 2: Production')
    args_cli = parser.parse_args()

    print("========================================")
    print("   MALXGMN SERVER 2 CORE ENGINE (BRD)   ")
    print("========================================")
    
    if args_cli.mode:
        choice = args_cli.mode
    else:
        print(" 1. Local (Windows/PowerShell)")
        print(" 2. Production (Linux/VPS)")
        print("========================================")
        choice = input("[?] Pilih Mode (1/2): ").strip()
    
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = None
    
    if choice == '1':
        p = os.path.join(scripts_dir, "venv", "Scripts", "python.exe")
        if os.path.exists(p): venv_python = p
    elif choice == '2':
        p = os.path.join(scripts_dir, "venv", "bin", "python")
        if os.path.exists(p): venv_python = p
    
    python_exe = venv_python if venv_python else sys.executable

    # Migrasi seluruh SQLite Telethon Session ke WAL mode
    migrate_all_sessions_to_wal(os.path.join(scripts_dir, "sessions"))

    # Jalankan Python API
    python_api_cmd = [python_exe, "-u", os.path.join(scripts_dir, "api.py")]
    threading.Thread(target=run_command, args=(python_api_cmd, scripts_dir, "PYTHON_API"), daemon=True).start()
    time.sleep(3)

    # Jalankan Bot Manager
    bot_manager = BotManager(python_exe, scripts_dir)
    threading.Thread(target=bot_manager.manage_bots, daemon=True).start()

    print("\n[✔] SERVER 2 CORE IS ACTIVE (BRD)!")
    print(f"[*] Working Directory: {scripts_dir}")
    print("[*] Sessions & JSON Storage: LOCAL TO SERVER 2")
    print("[!] Press Ctrl+C to stop all services.\n")

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    try:
        while True:
            time.sleep(1)
    except Exception:
        shutdown()

if __name__ == "__main__":
    main()
