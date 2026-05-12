import pylink      # pip install pylink-square
import re
import time
import sys
import platform
import os
import json
import gspread     # pip install gspread
from oauth2client.service_account import ServiceAccountCredentials # pip install oauth2client

# =========================================================
# KONFIGURACJA ZEWNĘTRZNA
# =========================================================
PROGRESS_FILE = "test_progress.json"
GOOGLE_CREDS_FILE = "credentials.json"  # Plik z Google Cloud Console
SHEET_NAME = "Raport_Testow_Bramki"     # Dokładna nazwa Twojego arkusza

# =========================================================
# ODBIERANIE ARGUMENTÓW Z GUI (runner.py)
# =========================================================
try:
    NUMBER_OF_TESTS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    IS_INFINITE = (sys.argv[2] == "1") if len(sys.argv) > 2 else False
except:
    NUMBER_OF_TESTS = 100
    IS_INFINITE = False

# =========================================================
# ZMIENNE I STAŁE SYSTEMOWE
# =========================================================
WAIT_TIME_FOR_GATE_ARM_MOVEMENT = 6
POKE_DELAY_TIME = 0.5
POKE_DELAY_EXIT_TIME = 0.5

# Czujniki
RIGHT_SENSOR, RIGHT_DOWN_SENSOR = 13, 10
LEFT_SENSOR, LEFT_DOWN_SENSOR = 0, 1
RIGHT_SECURITY_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR = 8, 3, 5  

# Logi RTT
LOG_GATE_OPENED = "Permit manager: GATE OPENED"
LOG_GATE_CLOSED = "Permit manager: GATE CLOSED"
LOG_ALARM_INTRUSION = "ALARM INTRUSION"
LOG_ALARM_TAILGATING = "ALARM TAILGATING"
LOG_MOTOR_ERROR = "MOTOR ERROR"
LOG_ALARM_NO_PERMIT = "ALARM NO PERMIT"
LOG_ALARM_SAFETY = "SAFETY ALARM"

right_counter = 0
left_counter = 0
current_mode = "WOLNE_LEWE_PRAWA"
start_time = time.time()

# =========================================================
# FUNKCJE ZAPISU I RAPORTOWANIA
# =========================================================

def save_progress(count):
    """Zapisuje aktualny numer testu do pliku."""
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"last_count": count}, f)

def load_progress():
    """Wczytuje, na czym skończyliśmy."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f).get("last_count", 0)
        except: return 0
    return 0

def report_to_sheets(data_row):
    """Wysyła [Nr, Nazwa, Status, Log, Timestamp] do Google Sheets."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).get_worksheet(0)
        sheet.append_row(data_row + [time.strftime("%Y-%m-%d %H:%M:%S")])
    except Exception as e:
        print(f"[!] BŁĄD GOOGLE SHEETS: {e}")

# =========================================================
# KOMUNIKACJA RTT I FIX TORQUE
# =========================================================

def rtt_get_param(idx, timeout_sec=1.0):
    jlink.rtt_write(0, f'get {idx}\n'.encode('utf-8'))
    start_t = time.time()
    rtt = ''
    while time.time() - start_t < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])
    return rtt

def rtt_set_param(idx, val):
    """
    Wysyła komendę SET i sprawdza przez GET, czy wartość faktycznie się zmieniła.
    Rozwiązuje problem ignorowania komend przez brama.
    """
    max_retries = 3
    for attempt in range(max_retries):
        jlink.rtt_write(0, f'set {idx} {val}\n'.encode('utf-8'))
        time.sleep(0.6) # Czas na przetworzenie przez MCU
        
        # Weryfikacja
        response = rtt_get_param(idx)
        digits = re.findall(r'\d+', response.replace(f'get {idx}', ''))
        if digits and int(digits[-1]) == val:
            print(f"[RTT] Parametr {idx} ustawiony na {val} (Sukces)")
            return True
        print(f"[RTT] Próba {attempt+1}: Parametr {idx} nie zmienił się. Ponawiam...")
    
    print(f"[RTT] KRYTYCZNY BŁĄD: Nie udało się ustawić parametru {idx} na {val}")
    return False

def wait_for_logs(log, timeout_sec):
    rtt = ''
    start_time_log = time.time()
    while time.time() - start_time_log < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])
        if rtt[-len(log):] == log:
            return True
    return False

def check_for_log_bool(log, timeout_sec):
    return wait_for_logs(log, timeout_sec)

def sensor_poke(num):
    jlink.rtt_write(0, f'sensor {num} 1\n'.encode('utf-8'))
    time.sleep(POKE_DELAY_TIME)
    jlink.rtt_write(0, f'sensor {num} 0\n'.encode('utf-8'))
    time.sleep(POKE_DELAY_EXIT_TIME)

def reset():
    jlink.rtt_write(0, b'reset\n')
    time.sleep(1.0)

def mode_set(mode):
    global current_mode
    table = ["WOLNE_LEWE_PRAWA", "WOLNE_LEWE_KONTROLA_PRAWE", "WOLNE_PRAWE_KONTROLA_LEWE",
             "KONTROLA_LEWE_PRAWA", "BLOKADA_LEWE_PRAWA", "BEZ_BLOKADY_LEWE_PRAWA"]
    if mode in table:
        jlink.rtt_write(0, f'mode {table.index(mode)}\n'.encode('utf-8'))
        time.sleep(0.5)
        current_mode = mode

def get_counters(timeout_sec=1.0):
    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.2)
    rtt = rtt_get_param(0, timeout_sec) # Hack: używamy get_param by zczytać bufor
    mr = re.findall(r"right counter:(\d+)", rtt)
    ml = re.findall(r"left counter:(\d+)", rtt)
    if mr and ml:
        return int(mr[-1]), int(ml[-1])
    return right_counter, left_counter

# =========================================================
# PRE-FLIGHT & DYNAMIC TORQUE
# =========================================================

def test_find_optimal_torque():
    print("\n[PRE-CHECK] Szukanie bezpiecznego momentu (Max Torque)...")
    optimal_torque = -1
    for tq in range(5, 21, 2): # Startujemy od 5, co 2 jednostki
        if rtt_set_param(28, tq):
            # Test ruchu
            jlink.rtt_write(0, f'sensor {LEFT_SENSOR} 1\n'.encode('utf-8'))
            time.sleep(0.3)
            jlink.rtt_write(0, f'sensor {LEFT_SENSOR} 0\n'.encode('utf-8'))
            
            if not check_for_log_bool(LOG_MOTOR_ERROR, 2):
                print(f"   [OK] Moment {tq} zaakceptowany.")
                optimal_torque = tq
                # Dokończ cykl, by zamknąć bramę
                for s in [CENTER_SECURITY_SENSOR, RIGHT_SENSOR]: sensor_poke(s)
                break
            else:
                print(f"   [!] Moment {tq} za słaby. Reset...")
                reset()
    return optimal_torque

# =========================================================
# SILNIK WYKONAWCZY
# =========================================================

def execute_custom_sequence(iter_num, config):
    name = config["name"]
    seq = config["seq"]
    expected_log = config["log"]
    expect_count = config["count"]
    req_mode = config.get("mode", "WOLNE_LEWE_PRAWA")

    print(f"\n>>> TEST {iter_num}: {name}")
    
    if current_mode != req_mode: mode_set(req_mode)

    start_r, start_l = get_counters()
    
    # Przejście przez czujniki
    for s in seq:
        jlink.rtt_write(0, f'sensor {s} 1\n'.encode('utf-8'))
        time.sleep(POKE_DELAY_TIME)
        jlink.rtt_write(0, f'sensor {s} 0\n'.encode('utf-8'))
        time.sleep(POKE_DELAY_EXIT_TIME)

    # Weryfikacja logu
    status = "FAIL"
    if expected_log:
        if check_for_log_bool(expected_log, WAIT_TIME_FOR_GATE_ARM_MOVEMENT):
            status = "PASS"
            print(f"   [OK] Log zweryfikowany.")
        else:
            print(f"   [X] Brak logu: {expected_log}")
    else:
        status = "PASS"

    # Weryfikacja licznika
    end_r, end_l = get_counters()
    count_increased = (end_r + end_l) > (start_r + start_l)
    
    if expect_count != count_increased:
        status = "FAIL"
        print("   [X] Błąd licznika!")

    # RAPORT DO GOOGLE SHEETS
    report_to_sheets([iter_num, name, status, expected_log])
    return status

# =========================================================
# SCENARIUSZE (SKRÓCONE)
# =========================================================

def get_scenarios():
    # Tu Twoja funkcja generate_100_scenarios()
    # Pamiętaj by zwracała listę słowników
    return [
        {"name": "Standard L->P", "mode": "WOLNE_LEWE_PRAWA", "seq": [0, 3, 5, 8, 13], "log": LOG_GATE_CLOSED, "count": True},
        {"name": "Intruz Środek", "mode": "WOLNE_LEWE_PRAWA", "seq": [5], "log": LOG_ALARM_INTRUSION, "count": False},
        # ... reszta scenariuszy ...
    ]

# =========================================================
# GŁÓWNA PĘTLA
# =========================================================

jlink = pylink.JLink()
jlink.open()
jlink.connect("STM32F030RC")
jlink.rtt_start()
reset()

# WCZYTYWANIE POSTĘPU
count = load_progress()
scenarios_pool = get_scenarios()

print(f"Wznawiam pracę od testu nr: {count + 1}")

try:
    while True:
        current_scenario = scenarios_pool[count % len(scenarios_pool)]
        
        res = execute_custom_sequence(count + 1, current_scenario)
        
        count += 1
        save_progress(count)
        
        if not IS_INFINITE and count >= NUMBER_OF_TESTS:
            print("Zakończono zaplanowaną pulę testów.")
            os.remove(PROGRESS_FILE) # Czyścimy postęp na koniec
            break
except KeyboardInterrupt:
    print("\nZatrzymano przez użytkownika. Postęp zapisany.")
finally:
    jlink.close()
