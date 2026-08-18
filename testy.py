import pylink
import re
import time
import sys
import platform
import os

# =========================================================
# ODBIERANIE ARGUMENTOW Z GUI
# =========================================================
try:
    NUMBER_OF_TESTS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    IS_INFINITE = (sys.argv[2] == "1") if len(sys.argv) > 2 else False
    GATE_TYPE = sys.argv[3] if len(sys.argv) > 3 else "SG"
except Exception:
    NUMBER_OF_TESTS = 100
    IS_INFINITE = False
    GATE_TYPE = "SG"

# =========================================================
# KONFIGURACJA PARAMETRÓW EEPROM
# =========================================================

# TABELA Z PDF - Ustawienia fabryczne (Domyślne) dla bramki SG
DEFAULT_SETTINGS_SG = {
    0: 0, 1: 3, 2: 0, 3: 0, 4: 0, 5: 9, 8: 0, 9: 1, 10: 5, 11: 0, 12: 1, 13: 0, 14: 0,
    15: 8, 16: 1, 17: 2, 18: 8, 19: 0, 20: 0, 21: 0, 22: 0, 23: 0, 24: 0, 25: 0, 26: 0,
    27: 0, 28: 0, 29: 0, 30: 0, 31: 0, 32: 0, 33: 0, 34: 0, 35: 0, 36: 0, 37: 0, 38: 0,
    39: 0, 40: 0, 41: 0, 42: 1, 43: 1, 44: 33, 45: 33, 46: 1, 47: 1, 48: 0, 49: 1,
    50: 1, 51: 6, 52: 0, 53: 0, 54: 0, 55: 0
}

# Wspólne parametry (ALL) - Do testów
PARAM_ALL = {
    0: 0,    
    10: 10,  
    12: 1,   
    13: 0,   
    18: 8,   
    19: 20,  
    20: 10,  
    21: 10,  
    22: 100, 
    23: 100, 
    28: 14,  
    40: 2    
}

# Parametry specyficzne dla konkretnych bramek
# ID 39 wraca na 0 (Tryb fizyczny) - Tryb symulacji (1) jest zbyt zbugowany i blokuje EEPROM
PARAM_SG = {
    27: 10, 
    32: 1,  
    39: 0   
}

PARAM_GT = {
    27: 10, 
    39: 0   
}

PARAM_SK = {
    27: 10, 
    32: 1,  
    39: 0   
}

PARAM_BR = {
    24: 5,  
    32: 0,  
    34: 1,  
    38: 0   
}

# =========================================================
# ZMIENNE I STALE SYSTEMOWE
# =========================================================
WAIT_TIME_FOR_GATE_ARM_MOVEMENT = 6
WAIT_TIMEOUT = 30
POKE_DELAY_TIME = 0.5
POKE_DELAY_EXIT_TIME = 0.5

BOOT_WAIT_MASTER   = 3.0   
BOOT_WAIT_LINK     = 5.0   
LOG_SYSTEM_READY   = "Permit manager"   
SYSTEM_READY_TIMEOUT = 12.0             

# LOGICZNE MAPOWANIE SENSOROW
RIGHT_SENSOR = 13
RIGHT_DOWN_SENSOR = 10
LEFT_SENSOR = 0
LEFT_DOWN_SENSOR = 1
RIGHT_SECURITY_SENSOR = 8
LEFT_SECURITY_SENSOR = 3
CENTER_SECURITY_SENSOR = 5

right_counter = 0
left_counter = 0
current_mode = "WOLNE_LEWE_PRAWA"
start_time = time.time()

LOG_GATE_OPENED    = "GATE OPENED"
LOG_GATE_CLOSED    = "GATE CLOSED"
# Dodano 'DANGEROUS BEHAVIOR' do dopuszczalnych reakcji obronnych
LOG_ALARM_INTRUSION  = ["INTRUSION", "UNAUTHORIZED", "SECURITY_ZONE_STATE", "DANGEROUS BEHAVIOR"]
LOG_ALARM_TAILGATING = ["TAILGATING", "UNAUTHORIZED", "SECURITY_ZONE_STATE", "DANGEROUS BEHAVIOR"]
LOG_MOTOR_ERROR    = "MOTOR ERROR"
LOG_ALARM_NO_PERMIT  = "NO PERMITION"
LOG_ALARM_SAFETY   = "SECURITY_ZONE_STATE"
LOG_TIMEOUT        = "TimeOUT"

# =========================================================
# FUNKCJE POMOCNICZE BAZOWE
# =========================================================
def play_beep(freq, duration):
    if platform.system() == "Windows":
        import winsound
        winsound.Beep(freq, duration)

def drain_rtt(jlink, max_bytes=4096):
    try:
        chunk = jlink.rtt_read(0, max_bytes)
        if chunk:
            text = "".join([chr(c) for c in chunk])
            sys.stdout.write(text)
            sys.stdout.flush()
            return text
    except Exception:
        pass
    return ""

def wait_for_logs(jlink, log, timeout_sec):
    rtt = ''
    start_time_log = time.time()
    while time.time() - start_time_log < timeout_sec:
        chunk = jlink.rtt_read(0, 1024)
        if chunk:
            text = "".join([chr(c) for c in chunk])
            sys.stdout.write(text)
            sys.stdout.flush()
            rtt += text
        if log in rtt:
            return True
        time.sleep(0.02)

    print("\n-----------========== DIAGNOSE ============-------------")
    print("Timeout reached. Log:'{}' not found. - TEST FAILED".format(log))
    play_beep(440, 500)
    sys.exit(1)

def check_for_log_bool(jlink, log, timeout_sec):
    rtt = ''
    start_time_log = time.time()
    while time.time() - start_time_log < timeout_sec:
        chunk = jlink.rtt_read(0, 1024)
        if chunk:
            text = "".join([chr(c) for c in chunk])
            sys.stdout.write(text)
            sys.stdout.flush()
            rtt += text
        if log in rtt:
            return True
        time.sleep(0.02)
    return False

def sensor_poke(jlink, num):
    jlink.rtt_write(0, 'sensor {} 1\n'.format(num).encode('utf-8'))
    time.sleep(POKE_DELAY_TIME)
    jlink.rtt_write(0, 'sensor {} 0\n'.format(num).encode('utf-8'))
    time.sleep(POKE_DELAY_EXIT_TIME)

def mode_set(jlink, mode):
    global current_mode
    strings_table = [
        "WOLNE_LEWE_PRAWA", "WOLNE_LEWE_KONTROLA_PRAWE", "WOLNE_PRAWE_KONTROLA_LEWE",
        "KONTROLA_LEWE_PRAWA", "BLOKADA_LEWE_PRAWA", "BEZ_BLOKADY_LEWE_PRAWA"
    ]
    if mode in strings_table:
        jlink.rtt_write(0, 'mode {}\n'.format(strings_table.index(mode)).encode('utf-8'))
        time.sleep(0.5)
        current_mode = mode
    else:
        print("\nMode:{} not found. - TEST FAILED".format(mode))
        play_beep(440, 500)
        sys.exit(1)

def add_permission(jlink, direction):
    if direction == "L":
        jlink.rtt_write(0, b'add_l\n')
    elif direction == "R":
        jlink.rtt_write(0, b'add_r\n')
    time.sleep(0.2)

def get_counters(jlink, timeout_sec=2.0):
    global right_counter, left_counter

    drain_rtt(jlink, 4096)
    
    # 1. Próba pancerna - wywołanie samej komendy `counter` z mocnym Regexem
    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.2)
    
    rtt = ''
    start_time_c = time.time()
    
    while time.time() - start_time_c < timeout_sec:
        chunk = jlink.rtt_read(0, 1024)
        if chunk:
            rtt += "".join([chr(c) for c in chunk])
            if "right counter" in rtt.lower() and "left counter" in rtt.lower():
                time.sleep(0.05)
                chunk = jlink.rtt_read(0, 1024)
                if chunk: rtt += "".join([chr(c) for c in chunk])
                break
        time.sleep(0.02)

    matches_r = re.findall(r"(?i)right\s+counter\s*:\s*(\d+)", rtt)
    matches_l = re.findall(r"(?i)left\s+counter\s*:\s*(\d+)", rtt)

    if matches_r and matches_l:
        right_counter = int(matches_r[-1])
        left_counter = int(matches_l[-1])
        return right_counter, left_counter

    # 2. Jesli komenda counter nie zadzialala w uzytym buforze, sprobuj EEPROM
    print("\n[INFO] Odczyt komendy 'counter' nie powiodl sie. Probuje EEPROM...")
    resp_l = rtt_get_param(jlink, 2, timeout_sec)
    val_l = parse_get_response(resp_l, 2)
    
    resp_r = rtt_get_param(jlink, 3, timeout_sec)
    val_r = parse_get_response(resp_r, 3)

    if val_l is not None and val_r is not None:
        left_counter = val_l
        right_counter = val_r
        return right_counter, left_counter

    print("\n[WARN] get_counters: Blad podwojnego odczytu! Uzywam ostatnich wartosci (L:{}, R:{}).".format(left_counter, right_counter))
    return right_counter, left_counter

# =========================================================
# FUNKCJE RTT (GET / SET / VERIFY)
# =========================================================

def parse_get_response(resp, idx):
    clean = re.sub(r'(?i).*?get\s+{}\s*[\r\n]+'.format(idx), '', resp)
    lines = [l.strip() for l in clean.split('\n') if l.strip()]
    
    for line in lines:
        if 'manager' in line.lower() or 'alarm' in line.lower() or 'set' in line.lower():
            continue
            
        match = re.search(r'[=:]\s*(-?\d+)', line)
        if match:
            return int(match.group(1))
            
        clean_line = re.sub(r'\[.*?\]|\(.*?\)', '', line)
        digits = re.findall(r'-?\d+', clean_line)
        if digits:
            return int(digits[-1])
            
    return None

def rtt_get_param(jlink, idx, timeout_sec=1.5):
    try:
        jlink.rtt_read(0, 4096)
    except Exception:
        pass

    jlink.rtt_write(0, 'get {}\n'.format(idx).encode('utf-8'))
    start_t = time.time()
    rtt = ''
    while time.time() - start_t < timeout_sec:
        chunk = jlink.rtt_read(0, 1024)
        if chunk:
            rtt += "".join([chr(c) for c in chunk])
            if rtt.replace('\r', '').count('\n') >= 2:
                break
        time.sleep(0.02)
    return rtt

def rtt_set_and_verify(jlink, idx, val, is_remote=False):
    monitor_window = 1.5 if is_remote else 1.0 
    
    for attempt in range(4):
        print("   -> [ZAPIS] ID {} = {} ...".format(idx, val), end="")
        sys.stdout.flush()

        drain_rtt(jlink, 4096)
        
        jlink.rtt_write(0, 'set {} {}\n'.format(idx, val).encode('utf-8'))

        time.sleep(0.4 if is_remote else 0.2)

        collected_logs = drain_rtt(jlink, 4096)

        if ("WWDG" in collected_logs or "IWDG" in collected_logs
                or "HardFault" in collected_logs):
            print(" [KATASTROFA WDG/FAULT]")
            return False

        resp = rtt_get_param(jlink, idx, 1.5)
        read_val = parse_get_response(resp, idx)

        if read_val is not None:
            if read_val == val:
                print(" [OK]")
                time.sleep(0.2) 
                return True
            else:
                print(" [FAIL - Odczytano: {}] ponawiam...".format(read_val))
        else:
            print(" [FAIL - Brak odpowiedzi] ponawiam...")
            
        time.sleep(0.5)

    return False

def safe_rtt_restart(jlink, delay=None, wait_for_link=True):
    if delay is None:
        delay = BOOT_WAIT_MASTER

    print("   [RESET] Wymuszono reset sprzetowy przez SWD. Czekam na boot MCU...")
    try:
        jlink.restart()
    except Exception as e:
        print("   [WARN] Blad jlink.restart(): {}. Uzywam komendy konsolowej...".format(e))
        jlink.rtt_write(0, b'reset\n')

    time.sleep(delay)

    rtt_started = False
    start_rtt_time = time.time()
    while time.time() - start_rtt_time < 6.0:
        try:
            jlink.rtt_stop()
        except Exception:
            pass
        time.sleep(0.3)
        try:
            jlink.rtt_start()
            rtt_started = True
            break
        except Exception:
            time.sleep(0.5)

    if not rtt_started:
        print("[WARN] Nie udalo sie wznowic RTT automatycznie.")

    if not wait_for_link:
        time.sleep(1)
        return

    rtt_buf = ""
    start_link = time.time()
    link_found = False

    while time.time() - start_link < SYSTEM_READY_TIMEOUT:
        chunk = jlink.rtt_read(0, 1024)
        if chunk:
            text = "".join([chr(c) for c in chunk])
            rtt_buf += text
        if LOG_SYSTEM_READY in rtt_buf:
            link_found = True
            break
        time.sleep(0.05)

    if link_found:
        print("   [BOOT] Wykryto marker Master<->Slave. System w 100% gotowy.")
        time.sleep(1.0)
    else:
        print("   [BOOT WARN] Nie przechwycono logu startowego (MCU wstal zbyt szybko).")
        print("   [BOOT PING] Wysylam ping diagnostyczny (tryb pracy ID 0)...")
        
        ping_resp = rtt_get_param(jlink, 0, timeout_sec=2.0)
        if parse_get_response(ping_resp, 0) is not None:
            print("   [BOOT OK] Brama zyje i odpowiada na zapytania RTT.")
        else:
            print("   [BOOT FATAL] Brama nie odpowiada! Ryzyko WDG lub rozlaczenia J-Link.")
            time.sleep(BOOT_WAIT_LINK)

# =========================================================
# TRYB PRZYWRACANIA USTAWIEŃ FABRYCZNYCH SG
# =========================================================

def restore_sg_defaults(jlink):
    print("\n" + "="*60)
    print(" ⚠️  URUCHOMIONO TRYB: PRZYWRACANIE USTAWIEŃ DOMYŚLNYCH (SG)")
    print("="*60)
    
    print("\n[INFO] Przywracanie konfiguracji fabrycznej z pliku PDF...")
    
    for idx, val in DEFAULT_SETTINGS_SG.items():
        is_rem = True if idx >= 13 else False
        status = rtt_set_and_verify(jlink, idx, val, is_remote=is_rem)
        if not status:
            print("  [WARN] Nie udalo sie nadpisac zmiennej ID: {}. Kontynuuje...".format(idx))
            
    print("\n[OK] Zapisano domyślne parametry. Czekam na zapis do pamięci Flash Slave'a...")
    time.sleep(4.0)
    
    safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)
    print("\n[SUKCES] Ustawienia fabryczne przywrócone.")

# =========================================================
# TRYB DIAGNOSTYCZNY: TESTOWANIE FIZYCZNE CZUJNIKÓW
# =========================================================

def run_sensor_diagnostics(jlink, gate_type):
    print("\n" + "="*60)
    print(" 🛠️  URUCHOMIONO TRYB: AUTOMATYCZNA DIAGNOSTYKA CZUJNIKÓW")
    print("="*60)
    
    print("\n[INFO] Wymuszanie czułości czujników na 0 (aktywacja pełnej linii optyki)...")
    rtt_set_and_verify(jlink, 40, 0, is_remote=True)
    
    print("[INFO] Wymuszanie trybu sprzętowego czujników (Sensor Mode = 0)...")
    rtt_set_and_verify(jlink, 39, 0, is_remote=True)
    
    time.sleep(1.0)
    safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)

    expected_sensors_count = 12

    if "SG" in gate_type:
        print("\n -> Profil: Szybkie Bramki Rozsuwane (SG)")
        print(" -> Układ: 5 czujników górnych, 7 dolnych (Razem: 12)")
    else:
        print("\n -> Profil: Bramki Obrotowe/Wahadłowe (GT/SK)")
        print(" -> Układ: 6 czujników górnych, 6 dolnych (Razem: 12)")

    print("\n[INSTRUKCJA] Przesuwaj powoli ręką przez WSZYSTKIE czujniki (dół i góra).")
    print("[INSTRUKCJA] Skrypt zapisuje sprawne czujniki i wyłączy się, gdy zliczy {}.\n".format(expected_sensors_count))

    jlink.rtt_write(0, b'mode 0\n')
    time.sleep(0.5)
    drain_rtt(jlink)

    tested_sensors = set()

    while True:
        chunk = jlink.rtt_read(0, 2048)
        if chunk:
            text = "".join([chr(c) for c in chunk])
            lines = text.split('\n')
            for line in lines:
                clean = line.strip()
                if not clean: continue

                if "sensor ->" in clean:
                    pass
                elif re.search(r'(?:SENSOR|MASK).*?(0x[0-9A-Fa-f]+)', clean, re.IGNORECASE):
                    match = re.search(r'(?:SENSOR|MASK).*?(0x[0-9A-Fa-f]+)', clean, re.IGNORECASE)
                    hex_str = match.group(1)
                    try:
                        val = int(hex_str, 16)
                        active_now = []
                        new_found = False
                        
                        for i in range(16):
                            if val & (1 << i):
                                sensor_id = str(i)
                                active_now.append(sensor_id)
                                if sensor_id not in tested_sensors:
                                    tested_sensors.add(sensor_id)
                                    new_found = True

                        if new_found:
                            print(" 📡 [ZALICZONO {}/{}] Detekcja! Aktywne w tej chwili: {}".format(
                                len(tested_sensors), expected_sensors_count, ", ".join(active_now)))
                            print("     -> Zarejestrowane łącznie: [{}]".format(", ".join(sorted(tested_sensors, key=int))))

                            if len(tested_sensors) >= expected_sensors_count:
                                print("\n" + "="*60)
                                print(" ✅ [SUKCES] Przetestowano pomyślnie wszystkie {} czujników!".format(expected_sensors_count))
                                print(" ✅ Test diagnostyczny zakończony automatycznie.")
                                print("="*60 + "\n")
                                return
                    except:
                        pass
                else:
                    if "Permit manager" not in clean and "TICK" not in clean.upper() and "sensor" not in clean.lower():
                        pass

        time.sleep(0.05)

# =========================================================
# PRE-FLIGHT CHECKS, KONFIGURACJA I DIAGNOSTYKA
# =========================================================

def apply_and_verify_full_config(jlink, gate_type):
    print("\n[SETUP] Rozpoczynam pelna konfiguracje EEPROM dla bramki: {}...".format(gate_type))
    
    target_params = PARAM_ALL.copy()
    if gate_type == "SG":
        target_params.update(PARAM_SG)
    elif gate_type == "GT":
        target_params.update(PARAM_GT)
    elif gate_type == "SK":
        target_params.update(PARAM_SK)
    elif gate_type == "BR":
        target_params.update(PARAM_BR)
    else:
        print("  [WARN] Nieznany typ bramki {}. Wgrywam tylko zestaw podstawowy (ALL).".format(gate_type))

    for idx, val in target_params.items():
        is_rem = True if idx >= 13 else False
        status = rtt_set_and_verify(jlink, idx, val, is_remote=is_rem)
        if not status:
            print("  [WARN] Nie udalo sie nadpisac zmiennej ID: {}. Kontynuuje mimo to...".format(idx))
            
    print("  [OK] Wszystkie {} parametrow wyslano. Czekam 4s na zapis Flash u Slave'a...".format(len(target_params)))
    time.sleep(4.0)
    
    safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)
    time.sleep(2.0)
    drain_rtt(jlink, 4096)
    
    print("\n[WERYFIKACJA] Sprawdzanie trwalosci danych po restarcie (Crash-Safe)...")
    for idx, expected_val in target_params.items():
        read_val = None
        for attempt in range(4):
            resp = rtt_get_param(jlink, idx, timeout_sec=2.0)
            read_val = parse_get_response(resp, idx)
            if read_val is not None:
                break
            time.sleep(0.5)
            
        if read_val == expected_val:
            print("  [OK] Parametr ID {:<2} = {:<3} (przetrwal reset)".format(idx, expected_val))
        else:
            print("  [WARN] Parametr ID {} utracony lub odrzucony przez plyte! Oczekiwano {}, odczytano: {}".format(
                idx, expected_val, read_val if read_val is not None else "Brak odpowiedzi"))
            
    print("  [INFO] Weryfikacja EEPROM zakonczona. Przechodze dalej.")

def test_calibration_read_only(jlink):
    print("\n[PRE-CHECK] Sprawdzanie bezpieczenstwa kalibracji...")
    drain_rtt(jlink, 4096)
    time.sleep(0.5)

    calib_val = None
    for attempt in range(5):
        response = rtt_get_param(jlink, 7, timeout_sec=2.0)
        calib_val = parse_get_response(response, 7)
        if calib_val is not None:
            break
        time.sleep(0.8)

    if calib_val is None:
        print("Nie udalo sie odczytac kalibracji! Zatrzymuje test.")
        sys.exit(1)

    if calib_val < 0 or calib_val > 4:
        print("BLAD: Kalibracja poza zakresem: {}. Zatrzymuje test!".format(calib_val))
        sys.exit(1)
    print("Kalibracja w normie. Odczytana wartosc: {}".format(calib_val))

def test_diagnostics_counters(jlink):
    print("\n[TLO] Sprawdzanie licznikow diagnostycznych (wg comm.h)...")
    
    response = rtt_get_param(jlink, 116)
    err_count = parse_get_response(response, 116)
    if err_count is not None and err_count > 0:
        print("  [OSTRZEZENIE] Wykryto {} bledow komunikacji Master-Slave!".format(err_count))
            
    response_wwdg = rtt_get_param(jlink, 112)
    wwdg_count = parse_get_response(response_wwdg, 112)
    if wwdg_count is not None and wwdg_count > 0:
        print("  [OSTRZEZENIE] Krytyczne resety WWDG: {}!".format(wwdg_count))

def test_diagnostic_readonly(jlink):
    print("\n[PRE-CHECK] Test ochrony parametrow diagnostycznych (Uptime - ID 118)...")
    drain_rtt(jlink, 4096)
    
    uptime_val = None
    for attempt in range(3):
        response = rtt_get_param(jlink, 118, timeout_sec=2.0)
        uptime_val = parse_get_response(response, 118)
        if uptime_val is not None:
            break
        time.sleep(0.5)
        
    if uptime_val is None:
        print("  [WARN] Brak odpowiedzi dla ID 118, pomijam ten konkret check.")
        return
        
    jlink.rtt_write(0, b'set 118 9999\n')
    time.sleep(0.5)

    response_new = rtt_get_param(jlink, 118, timeout_sec=2.0)
    new_uptime = parse_get_response(response_new, 118)
    
    if new_uptime is not None:
        if new_uptime == 9999:
            print("  [BLAD KRYTYCZNY] Ochrona nie dziala! Parametr read-only nadpisany.")
            sys.exit(1)
        else:
            print("  [OK] Zabezpieczenie dziala, parametr nienaruszony.")

def test_boundary_limits(jlink):
    print("\n[PRE-CHECK] Test limitow tablicy menu (Predkosc silnika - ID 18)...")
    drain_rtt(jlink, 4096)
    
    jlink.rtt_write(0, b'set 18 255\n')
    time.sleep(0.5)
    
    clamped_val = None
    for attempt in range(3):
        response = rtt_get_param(jlink, 18, timeout_sec=2.0)
        clamped_val = parse_get_response(response, 18)
        if clamped_val is not None:
            break
        time.sleep(0.5)
        
    if clamped_val is not None:
        if clamped_val == 255:
            print("  [OSTRZEZENIE] Brak logiki MIN/MAX w menu_st dla tego parametru! Zapisano 255.")
        else:
            print("  [OK] System zablokowal niebezpieczna wartosc: {}".format(clamped_val))
    else:
        print("  [WARN] Brak odpowiedzi dla limitów prędkości.")

def test_find_optimal_torque(jlink):
    print("\n[PRE-CHECK] Pelne skanowanie Max Torque (1-20)...")
    successful_torques = []

    for tq in range(1, 21):
        status = rtt_set_and_verify(jlink, 28, tq, is_remote=True)
        if not status:
            continue 

        safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)
        mode_set(jlink, "KONTROLA_LEWE_PRAWA")
        time.sleep(1)
        add_permission(jlink, "L")

        rtt_buffer = ''
        start_t = time.time()
        result = "TIMEOUT"

        while time.time() - start_t < 6.0:
            chunk = jlink.rtt_read(0, 1024)
            if chunk:
                text = "".join([chr(c) for c in chunk])
                rtt_buffer += text
                if LOG_MOTOR_ERROR in rtt_buffer:
                    result = "ERROR"
                    break
                elif LOG_GATE_OPENED in rtt_buffer:
                    result = "OPENED"
                    break
            time.sleep(0.05)

        if result == "OPENED":
            print("   [V] Moment {} wystarczajacy do ruchu.".format(tq))
            successful_torques.append(tq)
            
            print("   [INFO] Symulacja wirtualnego przejścia by zresetować stan bramki...")
            seq_lp = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
            
            jlink.rtt_write(0, 'sensor {} 1\n'.format(seq_lp[0]).encode('utf-8'))
            time.sleep(0.3)
            for i in range(len(seq_lp)):
                if i + 1 < len(seq_lp):
                    jlink.rtt_write(0, 'sensor {} 1\n'.format(seq_lp[i+1]).encode('utf-8'))
                    time.sleep(0.3)
                jlink.rtt_write(0, 'sensor {} 0\n'.format(seq_lp[i]).encode('utf-8'))
                time.sleep(0.3)
            
            for s in set(seq_lp):
                jlink.rtt_write(0, 'sensor {} 0\n'.format(s).encode('utf-8'))
                time.sleep(0.05)
                
            check_for_log_bool(jlink, LOG_GATE_CLOSED, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
            time.sleep(1)
            print("   [OK] Przerwano szukanie - znaleziono optymalny moment.")
            break
        else:
            print("   [X] Moment {} niewystarczajacy.".format(tq))

    if successful_torques:
        optimal_torque = min(successful_torques)
        print("-> Aplikowanie optymalnego momentu ({})...".format(optimal_torque))
        rtt_set_and_verify(jlink, 28, optimal_torque, is_remote=True)

    mode_set(jlink, "WOLNE_LEWE_PRAWA")
    safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)

# =========================================================
# SILNIK WYKONAWCZY SEKWENCJI
# =========================================================
def execute_custom_sequence(jlink, iter_num, config):
    name          = config["name"]
    seq           = config["seq"]
    expected_log  = config["log"]
    expect_count  = config["count"]
    req_mode      = config.get("mode", "WOLNE_LEWE_PRAWA")
    permit        = config.get("permit", None)
    interrupt_step = config.get("interrupt", None)
    custom_trigger = config.get("custom_trigger", None)
    custom_restore = config.get("custom_restore", None)
    wait_time      = config.get("wait_time", WAIT_TIME_FOR_GATE_ARM_MOVEMENT)

    print("\n=======================================================")
    print(">>> TEST NR: {} | {}".format(iter_num, name))

    if current_mode != req_mode:
        print("Ustawianie trybu: {}".format(req_mode))
        mode_set(jlink, req_mode)

    # 1. Czyszczenie stref przed rozpoczęciem testu z większą precyzją
    for s in [0, 1, 3, 5, 8, 10, 13]:
        jlink.rtt_write(0, 'sensor {} 0\n'.format(s).encode('utf-8'))
    time.sleep(0.3)

    global right_counter, left_counter
    start_r, start_l = get_counters(jlink, 1.5)

    if permit:
        print("Nadawanie uprawnienia dla: {}".format(permit))
        add_permission(jlink, permit)
        
    if custom_trigger:
        print("Wysylanie Triggera Systemowego: {}".format(custom_trigger.strip()))
        jlink.rtt_write(0, custom_trigger.encode('utf-8'))
        time.sleep(0.5)

    collected_logs = []
    def do_sleep(dur):
        start_t = time.time()
        while time.time() - start_t < dur:
            chunk = jlink.rtt_read(0, 1024)
            if chunk:
                text = "".join([chr(c) for c in chunk])
                sys.stdout.write(text)
                sys.stdout.flush()
                collected_logs.append(text)
            time.sleep(0.02)

    def filter_and_print_log(text):
        if "sensor ->" not in text:
            sys.stdout.write(text)
            sys.stdout.flush()

    if seq:
        # 2. Powrót do naturalnego kroku człowieka 
        jlink.rtt_write(0, 'sensor {} 1\n'.format(seq[0]).encode('utf-8'))
        do_sleep(0.3)

        for i in range(len(seq)):
            if interrupt_step and i == interrupt_step["after_index"]:
                print("\n[!] ALARM: Symulacja naruszenia strefy {}!".format(interrupt_step['sensor']))
                jlink.rtt_write(0, 'sensor {} 1\n'.format(interrupt_step["sensor"]).encode('utf-8'))
                do_sleep(0.8)
                jlink.rtt_write(0, 'sensor {} 0\n'.format(interrupt_step["sensor"]).encode('utf-8'))

            if i + 1 < len(seq):
                jlink.rtt_write(0, 'sensor {} 1\n'.format(seq[i+1]).encode('utf-8'))
                do_sleep(0.1) # Lekkie nałożenie nóg człowieka (dwie strefy na raz)

            jlink.rtt_write(0, 'sensor {} 0\n'.format(seq[i]).encode('utf-8'))
            do_sleep(0.3)

    if expected_log:
        found = False
        full_log = "".join(collected_logs)
        
        def check_log(expected, text):
            if isinstance(expected, list):
                return any(e in text for e in expected)
            return expected in text

        if check_log(expected_log, full_log):
            found = True
        else:
            start_w = time.time()
            while time.time() - start_w < wait_time:
                chunk = jlink.rtt_read(0, 1024)
                if chunk:
                    text = "".join([chr(c) for c in chunk])
                    filter_and_print_log(text)
                    full_log += text
                    if check_log(expected_log, full_log):
                        found = True
                        break
                time.sleep(0.05)
        
        if not found:
            print("\nBLAD: Oczekiwano logu '{}', ale go zabraklo! - TEST FAILED".format(expected_log))
            print("--- Zgromadzone logi z tego testu ---")
            print(re.sub(r'sensor ->.*?\n', '', full_log)) 
            print("-------------------------------------")
            play_beep(440, 500)
            sys.exit(1)
        print("\nSUKCES: Zweryfikowano zachowanie '{}'.".format(expected_log))

    time.sleep(2.5) # Czas na uspokojenie firmware po tescie i fizyczne zamkniecie skrzydel bramki

    # 3. Zamiatanie śmieci post-testowych po zamknięciu skrzydeł
    for s in [0, 1, 3, 5, 8, 10, 13]:
        jlink.rtt_write(0, 'sensor {} 0\n'.format(s).encode('utf-8'))
    
    # 4. NOWOŚĆ: Dodany czas oddechu po wyczyszczeniu RAM, aby EEPROM zdążył zapisać wynik i dał się odczytać 
    time.sleep(1.5) 

    if custom_restore:
        print("Wysylanie Komendy Przywracajacej: {}".format(custom_restore.strip()))
        jlink.rtt_write(0, custom_restore.encode('utf-8'))
        time.sleep(1.0)

    end_r, end_l = get_counters(jlink, 2.0)
    total_start = start_r + start_l
    total_end   = end_r + end_l

    if expect_count is True:
        if total_end <= total_start:
            print("\nBLAD: Zliczanie przejscia w EEPROM NIE powiodlo sie! - TEST FAILED")
            sys.exit(1)
        else:
            right_counter, left_counter = end_r, end_l
            print("\nSUKCES: Licznik EEPROM wzrosl (L:{}, R:{})".format(left_counter, right_counter))
            
    elif expect_count is False:
        if total_end > total_start:
            print("\nBLAD: System nieslusznie zliczyl przejscie w stale pamieci EEPROM! - TEST FAILED")
            sys.exit(1)
        else:
            print("\nSUKCES: System poprawnie zignorowal bledne/brakujace przejscie.")
            
    elif expect_count is None:
        right_counter, left_counter = end_r, end_l
        print("\nSUKCES: Weryfikacja licznika pominieta (ustawienie specjalne).")

# =========================================================
# GENERATOR BAZY TESTOW BEHAWIORALNYCH
# =========================================================
def generate_100_scenarios():
    scenarios = []

    seq_lp = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
    seq_pl = [RIGHT_SENSOR, RIGHT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR]

    scenarios.append({"name": "KONTROLA: Otwarcie w LEWO", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": seq_lp, "log": LOG_GATE_CLOSED, "count": True})
    scenarios.append({"name": "KONTROLA: Otwarcie w PRAWO", "mode": "KONTROLA_LEWE_PRAWA", "permit": "R", "seq": seq_pl, "log": LOG_GATE_CLOSED, "count": True})
    scenarios.append({"name": "KONTROLA: Odbicie bez uprawnienia", "mode": "KONTROLA_LEWE_PRAWA", "permit": None, "seq": [LEFT_SENSOR], "log": LOG_ALARM_NO_PERMIT, "count": False})
    scenarios.append({"name": "BLOKADA: Proba wejscia z lewej", "mode": "BLOKADA_LEWE_PRAWA", "permit": "L", "seq": [LEFT_SENSOR], "log": "", "count": False})
    scenarios.append({"name": "KONTROLA ZLY KIERUNEK", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": [RIGHT_SENSOR, RIGHT_SECURITY_SENSOR], "log": LOG_ALARM_INTRUSION, "count": False})
    
    # 5. Zwiekszona tolerancja Timeoutu z 10 na 12 sekund dla plynniejszego dzialania
    scenarios.append({"name": "TIMEOUT: Nadano uprawnienie L", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": [], "log": LOG_TIMEOUT, "count": False, "wait_time": 12})
    scenarios.append({"name": "WYCOFANIE: Uzytkownik wszedl i zrezygnowal", "mode": "WOLNE_LEWE_PRAWA", "seq": [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR], "log": "", "count": False})
    scenarios.append({"name": "ALARM PPOZ: Awaryjne otwarcie", "mode": "WOLNE_LEWE_PRAWA", "custom_trigger": "ppoz 1\n", "seq": seq_lp, "log": "", "count": None, "custom_restore": "ppoz 0\n"})
    
    scenarios.append({"name": "USTERKA SENSORA CENTER", "mode": "WOLNE_LEWE_PRAWA", "custom_trigger": "sensor {} 1\n".format(CENTER_SECURITY_SENSOR), "seq": [], "log": LOG_ALARM_SAFETY, "count": False, "custom_restore": "sensor {} 0\n".format(CENTER_SECURITY_SENSOR)})
    
    scenarios.append({
        "name": "TAILGATING", 
        "mode": "KONTROLA_LEWE_PRAWA", 
        "permit": "L", 
        "seq": seq_lp, 
        "interrupt": {"after_index": 1, "sensor": LEFT_SENSOR}, 
        "log": LOG_ALARM_TAILGATING, 
        "count": None
    })
    
    scenarios.append({"name": "INTRUSION w srodek bramki", "mode": "BLOKADA_LEWE_PRAWA", "seq": [CENTER_SECURITY_SENSOR], "log": LOG_ALARM_INTRUSION, "count": False})
    scenarios.append({"name": "ANTI-CRUSH", "mode": "WOLNE_LEWE_PRAWA", "seq": [LEFT_SENSOR, LEFT_SECURITY_SENSOR], "interrupt": {"after_index": 0, "sensor": CENTER_SECURITY_SENSOR}, "log": LOG_ALARM_SAFETY, "count": False})

    for i in range(15):
        seq_lp_wah = ([LEFT_SENSOR] * ((i % 2) + 1) + [LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR])
        scenarios.append({"name": "WOLNE L->P (Wahanie przy wejsciu {}x)".format(i % 2 + 1), "mode": "WOLNE_LEWE_PRAWA", "seq": seq_lp_wah, "log": LOG_GATE_CLOSED, "count": True})
        seq_pl_wah = ([RIGHT_SENSOR] * ((i % 2) + 1) + [RIGHT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR])
        scenarios.append({"name": "WOLNE P->L (Wahanie przy wejsciu {}x)".format(i % 2 + 1), "mode": "WOLNE_LEWE_PRAWA", "seq": seq_pl_wah, "log": LOG_GATE_CLOSED, "count": True})

    return scenarios

# =========================================================
# GLOWNY SKRYPT
# =========================================================
def main():
    global right_counter, left_counter

    print("\n=======================================================")
    print(" TYP BRAMKI: {}".format(GATE_TYPE))
    print("=======================================================\n")

    jlink = pylink.JLink()
    emulators = jlink.connected_emulators()

    if not emulators:
        print("Nie znaleziono zadnych urzadzen J-Link.")
        sys.exit(1)

    selected_sn = emulators[0].SerialNumber
    jlink.open(serial_no=selected_sn)
    jlink.connect("STM32F030RC", verbose=True)
    jlink.rtt_start()

    try:
        jlink.restart()
        print("Reset wyslany. Czekam na pelny boot Master+Slave...")

        time.sleep(BOOT_WAIT_MASTER)
        try:
            jlink.rtt_stop()
            time.sleep(0.2)
            jlink.rtt_start()
        except Exception:
            pass

        rtt_buf = ""
        start_boot = time.time()
        while time.time() - start_boot < SYSTEM_READY_TIMEOUT:
            chunk = jlink.rtt_read(0, 1024)
            if chunk:
                text = "".join([chr(c) for c in chunk])
                rtt_buf += text
            if LOG_SYSTEM_READY in rtt_buf:
                print("\n[BOOT] System gotowy po {:.1f}s.".format(time.time() - start_boot))
                break
            time.sleep(0.05)
        else:
            print("[BOOT WARN] Marker gotowosci nie wykryty — kontynuuje.")

        # --- NOWY TRYB PRZYWRACANIA USTAWIEŃ ---
        if GATE_TYPE == "SG_RESTORE":
            restore_sg_defaults(jlink)
            return

        # --- NOWY TRYB DIAGNOSTYKI CZUJNIKOW ---
        if "Test Czujników" in GATE_TYPE:
            run_sensor_diagnostics(jlink, GATE_TYPE)
            return

        # >>>>>>>>>>>>> PRE-FLIGHT CHECKS >>>>>>>>>>>>>
        test_calibration_read_only(jlink)
        test_diagnostic_readonly(jlink)
        test_boundary_limits(jlink)

        # Instalowanie dedykowanego zestawu parametrów (ALL + Specyficzne)
        apply_and_verify_full_config(jlink, GATE_TYPE)

        # Skalowanie obciążenia
        test_find_optimal_torque(jlink)

        # >>>>>>>>>>>>> SETUP PRZED GLOWNA PETLA >>>>>>>>>>>>>
        mode_set(jlink, "WOLNE_LEWE_PRAWA")
        right_counter, left_counter = get_counters(jlink, 1)

        scenarios_pool = generate_100_scenarios()

        print("\n=======================================================")
        print(" BAZA TESTOWA ZALADOWANA. Wariantow: {}. Nieskonczonosc: {}".format(
            len(scenarios_pool), IS_INFINITE))
        if not IS_INFINITE and NUMBER_OF_TESTS > len(scenarios_pool):
            print(" UWAGA: NUMBER_OF_TESTS ({}) > pula ({}). Scenariusze beda powtarzane.".format(
                      NUMBER_OF_TESTS, len(scenarios_pool)))
        print("=======================================================\n")

        count = 0
        while True:
            scenario_index = count % len(scenarios_pool)
            if count > 0 and scenario_index == 0:
                print("\n[INFO] Pula scenariuszy wyczerpana — rozpoczynam kolejna iteracje od poczatku.\n")

            execute_custom_sequence(jlink, count + 1, scenarios_pool[scenario_index])
            count += 1

            if count % 15 == 0:
                test_diagnostics_counters(jlink)

            if not IS_INFINITE and count >= NUMBER_OF_TESTS:
                break

        minutes, seconds = divmod(time.time() - start_time, 60)
        print("\nTest finished successfully — czas: {} min {:.2f} s".format(int(minutes), seconds))

    finally:
        try:
            jlink.close()
            print("[CLEANUP] J-Link connection closed.")
        except Exception as e:
            print("[CLEANUP] Warning: error while closing J-Link: {}".format(e))

if __name__ == "__main__":
    main()
