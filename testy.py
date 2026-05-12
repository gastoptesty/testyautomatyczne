import pylink      # pip install pylink-square
import re
import time
import sys
import platform
import os
import json
import gspread     # pip install gspread
from oauth2client.service_account import ServiceAccountCredentials

# =========================================================
# KONFIGURACJA I STAŁE
# =========================================================
PROGRESS_FILE = "test_progress.json"
GOOGLE_CREDS_FILE = "credentials.json"
SHEET_NAME = "Logi_Testowe_Bramek" # Upewnij się, że nazwa jest identyczna w Google Drive

# Parametry czasowe
WAIT_TIME_FOR_GATE_ARM_MOVEMENT = 6
POKE_DELAY_TIME = 0.5
POKE_DELAY_EXIT_TIME = 0.5

# Definicje czujników
RIGHT_SENSOR = 13
RIGHT_DOWN_SENSOR = 10
LEFT_SENSOR = 0
LEFT_DOWN_SENSOR = 1
RIGHT_SECURITY_SENSOR = 8
LEFT_SECURITY_SENSOR = 3
CENTER_SECURITY_SENSOR = 5  

# Oczekiwane logi
LOG_GATE_OPENED = "Permit manager: GATE OPENED"
LOG_GATE_CLOSED = "Permit manager: GATE CLOSED"
LOG_ALARM_INTRUSION = "ALARM INTRUSION"
LOG_ALARM_TAILGATING = "ALARM TAILGATING"
LOG_MOTOR_ERROR = "MOTOR ERROR"
LOG_ALARM_NO_PERMIT = "ALARM NO PERMIT"
LOG_ALARM_SAFETY = "SAFETY ALARM"

# =========================================================
# OBSŁUGA ARGUMENTÓW Z GUI
# =========================================================
try:
    NUMBER_OF_TESTS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    IS_INFINITE = (sys.argv[2] == "1") if len(sys.argv) > 2 else False
except:
    NUMBER_OF_TESTS = 100
    IS_INFINITE = False

# =========================================================
# SYSTEM RAPORTOWANIA I POSTĘPU
# =========================================================

def save_progress(count):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"last_count": count}, f)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f).get("last_count", 0)
        except: return 0
    return 0

def report_to_sheets(data_row):
    """Wysyła dane do arkusza. Jeśli się nie uda, nie przerywa testu."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).get_worksheet(0)
        sheet.append_row(data_row + [time.strftime("%Y-%m-%d %H:%M:%S")])
    except Exception as e:
        print(f"   [!] BŁĄD RAPORTOWANIA SHEETS: {e}")

# =========================================================
# KOMUNIKACJA RTT (POPRAWIONA ODPORNOŚĆ)
# =========================================================

def safe_rtt_read(timeout_sec=1.5):
    """Cierpliwie czyta z bufora RTT, aż pojawi się treść."""
    start_t = time.time()
    collected_text = ""
    while time.time() - start_t < timeout_sec:
        data = jlink.rtt_read(0, 1024)
        if data:
            collected_text += "".join(map(chr, data))
            if "\n" in collected_text: 
                break
        time.sleep(0.1)
    return collected_text

def rtt_get_param(idx):
    jlink.rtt_write(0, f'get {idx}\n'.encode('utf-8'))
    return safe_rtt_read()

def rtt_set_param(idx, val):
    """Ustawia parametr i weryfikuje go komendą GET."""
    # Czyszczenie śmieci z bufora
    jlink.rtt_read(0, 4096)
    
    print(f"   [RTT] Próba: set {idx} {val}")
    jlink.rtt_write(0, f'set {idx} {val}\n'.encode('utf-8'))
    time.sleep(0.7)
    
    # Weryfikacja
    response = rtt_get_param(idx)
    print(f"   [RTT] Odpowiedź na weryfikację: '{response.strip()}'")
    
    # Wyciąganie liczb
    digits = re.findall(r'\d+', response)
    if digits and int(digits[-1]) == val:
        return True
    return False

# =========================================================
# LOGIKA TESTOWA
# =========================================================

def sensor_poke(num):
    jlink.rtt_write(0, f'sensor {num} 1\n'.encode('utf-8'))
    time.sleep(POKE_DELAY_TIME)
    jlink.rtt_write(0, f'sensor {num} 0\n'.encode('utf-8'))
    time.sleep(POKE_DELAY_EXIT_TIME)

def reset():
    jlink.rtt_write(0, b'reset\n')
    time.sleep(1.0)

def mode_set(mode_name):
    modes = ["WOLNE_LEWE_PRAWA", "WOLNE_LEWE_KONTROLA_PRAWE", "WOLNE_PRAWE_KONTROLA_LEWE",
             "KONTROLA_LEWE_PRAWA", "BLOKADA_LEWE_PRAWA", "BEZ_BLOKADY_LEWE_PRAWA"]
    if mode_name in modes:
        idx = modes.index(mode_name)
        jlink.rtt_write(0, f'mode {idx}\n'.encode('utf-8'))
        time.sleep(0.5)

def get_counters():
    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.3)
    rtt = safe_rtt_read()
    mr = re.findall(r"right counter:(\d+)", rtt)
    ml = re.findall(r"left counter:(\d+)", rtt)
    if mr and ml:
        return int(mr[-1]), int(ml[-1])
    return 0, 0

# =========================================================
# SEKWENCJA WYKONAWCZA
# =========================================================

def execute_custom_sequence(iter_num, config):
    name = config["name"]
    seq = config["seq"]
    expected_log = config["log"]
    expect_count = config["count"]
    req_mode = config.get("mode", "WOLNE_LEWE_PRAWA")
    
    print(f"\n>>> TEST {iter_num} | {name}")
    mode_set(req_mode)
    
    start_r, start_l = get_counters()
    
    # Ruch przez czujniki
    for s in seq:
        jlink.rtt_write(0, f'sensor {s} 1\n'.encode('utf-8'))
        time.sleep(POKE_DELAY_TIME)
        jlink.rtt_write(0, f'sensor {s} 0\n'.encode('utf-8'))
        time.sleep(POKE_DELAY_EXIT_TIME)
        
    # Sprawdzanie logów
    log_found = False
    if expected_log:
        log_found = any(expected_log in safe_rtt_read(2.0) for _ in range(3))
    
    # Sprawdzanie liczników
    end_r, end_l = get_counters()
    count_ok = ((end_r + end_l) > (start_r + start_l)) == expect_count
    
    status = "PASS" if count_ok else "FAIL"
    print(f"   [STATUS] {status}")
    
    report_to_sheets([iter_num, name, status, expected_log])
    return status

# =========================================================
# SCENARIUSZE I URUCHOMIENIE
# =========================================================

def generate_scenarios():
    # Przykładowe 3, tutaj można wkleić Twoją funkcję generującą 100
    return [
        {"name": "Standard L->P", "mode": "WOLNE_LEWE_PRAWA", "seq": [0, 3, 5, 8, 13], "log": LOG_GATE_CLOSED, "count": True},
        {"name": "Intruz Środek", "mode": "WOLNE_LEWE_PRAWA", "seq": [5], "log": LOG_ALARM_INTRUSION, "count": False},
        {"name": "Kontrola P->L", "mode": "KONTROLA_LEWE_PRAWA", "seq": [13], "log": LOG_ALARM_NO_PERMIT, "count": False}
    ]

# Inicjalizacja J-Link
jlink = pylink.JLink()
try:
    jlink.open()
    jlink.connect("STM32F030RC")
    jlink.rtt_start()
except Exception as e:
    print(f"Błąd połączenia J-Link: {e}")
    sys.exit(1)

reset()

# Pre-flight: Test Torque (nie przerywa skryptu przy failu)
print("\n[PRE-CHECK] Test ustawień Torque...")
if not rtt_set_param(28, 10):
    print("   [!] OSTRZEŻENIE: Brama nie potwierdziła zmiany Torque. Kontynuuję na domyślnym.")

# Główna pętla
scenarios = generate_scenarios()
count = load_progress()
start_time_global = time.time()

try:
    while True:
        current_idx = count % len(scenarios)
        execute_custom_sequence(count + 1, scenarios[current_idx])
        
        count += 1
        save_progress(count)
        
        if not IS_INFINITE and count >= NUMBER_OF_TESTS:
            if os.path.exists(PROGRESS_FILE): os.remove(PROGRESS_FILE)
            break
finally:
    jlink.close()
    print(f"\nTesty zakończone po {int((time.time()-start_time_global)/60)} min.")
