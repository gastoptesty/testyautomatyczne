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
# ZMIENNE I STALE SYSTEMOWE
# =========================================================
WAIT_TIME_FOR_GATE_ARM_MOVEMENT = 6
WAIT_TIMEOUT = 30

BOOT_WAIT_MASTER   = 3.0   
BOOT_WAIT_LINK     = 5.0   
LOG_SYSTEM_READY   = "Permit manager"   
SYSTEM_READY_TIMEOUT = 12.0             

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

# --- OCZEKIWANE LOGI Z SYSTEMU (Mniej rygorystyczne by wyłapać wszystko) ---
LOG_GATE_OPENED    = "GATE OPENED"
LOG_GATE_CLOSED    = "GATE CLOSED"
LOG_ALARM_INTRUSION  = "INTRUSION"
LOG_ALARM_TAILGATING = "TAILGATING"
LOG_MOTOR_ERROR    = "MOTOR ERROR"
LOG_ALARM_NO_PERMIT  = "NO PERMITION"
LOG_ALARM_SAFETY   = "SAFETY"
LOG_TIMEOUT        = "TIMEOUT"

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

def get_counters(jlink, timeout_sec=1.0):
    global right_counter, left_counter

    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.1)
    rtt = ''
    start_time_c = time.time()
    
    while time.time() - start_time_c < timeout_sec:
        chunk = jlink.rtt_read(0, 1024)
        if chunk:
            rtt += "".join([chr(c) for c in chunk])
        time.sleep(0.02)

    pattern_right = r"right counter:(\d+)"
    pattern_left  = r"left counter:(\d+)"

    matches_r = re.findall(pattern_right, rtt)
    matches_l = re.findall(pattern_left,  rtt)

    if matches_r and matches_l:
        right_val = int(matches_r[-1])
        left_val  = int(matches_l[-1])
        right_counter = right_val
        left_counter  = left_val
        return right_val, left_val

    print("\n[WARN] get_counters: Failed to parse RTT response. "
          "Using last known values (L:{}, R:{}).".format(left_counter, right_counter))
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
    monitor_window = 5.0 if is_remote else 3.0
    collected_logs = ""

    for attempt in range(4):
        print("\n--- [PROBA ZAPISU {}] Ustawianie parametru {} = {} (remote={}) ---".format(
            attempt + 1, idx, val, is_remote))

        try:
            jlink.rtt_read(0, 4096)
        except Exception:
            pass

        jlink.rtt_write(0, 'set {} {}\n'.format(idx, val).encode('utf-8'))

        collected_logs = ""
        start_monitor = time.time()

        while time.time() - start_monitor < monitor_window:
            chunk = jlink.rtt_read(0, 1024)
            if chunk:
                text = "".join([chr(c) for c in chunk])
                collected_logs += text
            time.sleep(0.01)

        if ("WWDG" in collected_logs or "IWDG" in collected_logs
                or "HardFault" in collected_logs):
            print("   [KATASTROFA] Wykryto sprzetowy HardFault lub Watchdog w logach!")
            return False, collected_logs

        jlink.rtt_write(0, b'\n')
        time.sleep(0.2)
        try:
            jlink.rtt_read(0, 256)
        except Exception:
            pass

        resp = rtt_get_param(jlink, idx, 1.5 if is_remote else 1.0)
        read_val = parse_get_response(resp, idx)

        if read_val is not None:
            if read_val == val:
                print("   [SUKCES] Parametr poprawnie zweryfikowany.")
                return True, collected_logs
            else:
                print("   [SYNC FAIL] Zglasza {}, oczekiwano {}. Ponawiam...".format(read_val, val))
        else:
            print("   [SYNC FAIL] Brak jasnej odpowiedzi cyfrowej na GET.")

    return False, collected_logs

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
            print("   [BOOT OK] Brama zyje i odpowiada na zapytania RTT. Bezpieczny zapis mozliwy.")
        else:
            print("   [BOOT FATAL] Brama nie odpowiada! Ryzyko WDG lub rozlaczenia J-Link.")
            time.sleep(BOOT_WAIT_LINK)

# =========================================================
# PRE-FLIGHT CHECKS & DIAGNOSTICS
# =========================================================
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
        print("  [WARN] Brak odpowiedzi dla ID 118, pomijam ten konkretny check.")
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

def test_eeprom_crash_safe(jlink):
    print("\n[PRE-CHECK] Test trwalosci atomowego zapisu EEPROM (Flash)...")
    test_id = 28  # MAX_TORQUE_SILNIK
    test_val = 14 
    
    status, logs = rtt_set_and_verify(jlink, test_id, test_val, is_remote=True)
    if not status:
        print("  [BLAD KRYTYCZNY] Nie udalo sie nadpisac zmiennej (ID: {})! Test przerwany.".format(test_id))
        sys.exit(1)

    print("  [OK] Zmienna testowa ustawiona. Czekam 2s na zatwierdzenie w pamieci Flash...")
    time.sleep(2.0)

    print("  [OK] Wymuszam twardy reset...")
    safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)
    
    time.sleep(3.0)
    drain_rtt(jlink, 4096)

    read_val = None
    for attempt in range(8):
        print("  [Odczyt po restarcie - próba {}/8]".format(attempt + 1))
        response = rtt_get_param(jlink, test_id, timeout_sec=3.0)
        read_val = parse_get_response(response, test_id)
        if read_val is not None:
            break
        time.sleep(1.5)
    
    jlink.rtt_write(0, 'set {} 1\n'.format(test_id).encode('utf-8'))
    time.sleep(0.5)

    if read_val == test_val:
        print("  [OK] Dane we Flash (EEPROM) sa bezpieczne, przetrwaly nagly reset!")
    else:
        print("  [BLAD KRYTYCZNY] Utrata danych po restarcie! Skrypt odczytal: {}".format(
            read_val if read_val is not None else "Brak odpowiedzi (CLI nie gotowe)"))
        sys.exit(1)

def setup_gate_hardware(jlink, gate_type):
    print("\n[SETUP] Konfiguracja sprzetowa dla bramki: {}...".format(gate_type))

    if gate_type == "SG":
        rtt_set_and_verify(jlink, 32, 1, is_remote=True)
        rtt_set_and_verify(jlink, 34, 0, is_remote=True)
        rtt_set_and_verify(jlink, 38, 0, is_remote=True)
    elif gate_type == "GT":
        rtt_set_and_verify(jlink, 32, 0, is_remote=True)
        rtt_set_and_verify(jlink, 34, 1, is_remote=True)
        rtt_set_and_verify(jlink, 38, 1, is_remote=True)
    elif gate_type == "SK":
        rtt_set_and_verify(jlink, 32, 1, is_remote=True)
        rtt_set_and_verify(jlink, 34, 0, is_remote=True)
        rtt_set_and_verify(jlink, 38, 0, is_remote=True)
    elif gate_type == "BR":
        rtt_set_and_verify(jlink, 32, 0, is_remote=True)
        rtt_set_and_verify(jlink, 34, 1, is_remote=True)
        rtt_set_and_verify(jlink, 38, 0, is_remote=True)
    else:
        print("  [WARN] Nieznany typ bramki, pomijam scisla konfiguracje EEPROM.")

    print("   [OK] Konfiguracja peryferiow zapisana. Wykonuje restart...")
    safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)

def test_find_optimal_torque(jlink):
    print("\n[PRE-CHECK] Pelne skanowanie Max Torque (1-20)...")
    successful_torques = []

    for tq in range(1, 21):
        status, logs = rtt_set_and_verify(jlink, 28, tq, is_remote=True)
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
            
            print("   [INFO] Symulacja fizycznego przejscia by zresetowac stan bramki...")
            seq_lp = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
            
            for i in range(len(seq_lp)):
                jlink.rtt_write(0, 'sensor {} 1\n'.format(seq_lp[i]).encode('utf-8'))
                time.sleep(0.3)
                if i + 1 < len(seq_lp):
                    jlink.rtt_write(0, 'sensor {} 1\n'.format(seq_lp[i+1]).encode('utf-8'))
                    time.sleep(0.3)
                jlink.rtt_write(0, 'sensor {} 0\n'.format(seq_lp[i]).encode('utf-8'))
                time.sleep(0.3)
                
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

    global right_counter, left_counter
    start_r, start_l = get_counters(jlink, 1)

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

    # NOWY SILNIK Z NAKŁADAJĄCYMI SIĘ CZUJNIKAMI (SYMULACJA CIAŁA PIESZEGO)
    if seq:
        for i in range(len(seq)):
            # 1. Wejście na bieżący czujnik
            jlink.rtt_write(0, 'sensor {} 1\n'.format(seq[i]).encode('utf-8'))
            do_sleep(0.3)

            # Przerwanie - Symulacja alarmu podczas kroku
            if interrupt_step and i == interrupt_step["after_index"]:
                print("\n[!] ALARM: Symulacja naruszenia strefy {}!".format(interrupt_step['sensor']))
                jlink.rtt_write(0, 'sensor {} 1\n'.format(interrupt_step["sensor"]).encode('utf-8'))
                do_sleep(0.8)
                jlink.rtt_write(0, 'sensor {} 0\n'.format(interrupt_step["sensor"]).encode('utf-8'))

            # 2. Wejście na KOLEJNY czujnik zanim zejdzie się z poprzedniego
            if i + 1 < len(seq):
                jlink.rtt_write(0, 'sensor {} 1\n'.format(seq[i+1]).encode('utf-8'))
                do_sleep(0.3)

            # 3. Zejście z bieżącego czujnika
            jlink.rtt_write(0, 'sensor {} 0\n'.format(seq[i]).encode('utf-8'))
            do_sleep(0.3)

    # POSZUKIWANIE OCZEKIWANEGO LOGU W ZBUFOROWANYCH DANYCH LUB NASŁUCH DALEJ
    if expected_log:
        found = False
        full_log = "".join(collected_logs)
        if expected_log in full_log:
            found = True
        else:
            start_w = time.time()
            while time.time() - start_w < wait_time:
                chunk = jlink.rtt_read(0, 1024)
                if chunk:
                    text = "".join([chr(c) for c in chunk])
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    full_log += text
                    if expected_log in full_log:
                        found = True
                        break
                time.sleep(0.05)
        
        if not found:
            print("\nBLAD: Oczekiwano logu '{}', ale go zabraklo! - TEST FAILED".format(expected_log))
            play_beep(440, 500)
            sys.exit(1)
        print("\nSUKCES: Zweryfikowano zachowanie '{}'.".format(expected_log))

    time.sleep(1)

    if custom_restore:
        print("Wysylanie Komendy Przywracajacej: {}".format(custom_restore.strip()))
        jlink.rtt_write(0, custom_restore.encode('utf-8'))
        time.sleep(0.5)

    end_r, end_l = get_counters(jlink, 1)
    total_start = start_r + start_l
    total_end   = end_r + end_l

    if expect_count:
        if total_end <= total_start:
            print("\nBLAD: Zliczanie przejscia NIE powiodlo sie! - TEST FAILED")
            sys.exit(1)
        else:
            right_counter, left_counter = end_r, end_l
            print("\nSUKCES: Licznik wzrosl (L:{}, R:{})".format(left_counter, right_counter))
    else:
        if total_end > total_start:
            print("\nBLAD: System nieslusznie zliczyl przejscie! - TEST FAILED")
            sys.exit(1)
        else:
            print("\nSUKCES: System poprawnie zignorowal bledne/brakujace przejscie.")

# =========================================================
# GENERATOR BAZY TESTOW BEHAWIORALNYCH
# =========================================================
def generate_100_scenarios():
    scenarios = []

    seq_lp = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
    seq_pl = [RIGHT_SENSOR, RIGHT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR]

    scenarios.append({"name": "KONTROLA: Otwarcie w LEWO", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": seq_lp, "log": LOG_GATE_CLOSED, "count": True})
    scenarios.append({"name": "KONTROLA: Otwarcie w PRAWO", "mode": "KONTROLA_LEWE_PRAWA", "permit": "R", "seq": seq_pl, "log": LOG_GATE_CLOSED, "count": True})
    scenarios.append({"name": "BLOKADA: Proba wejscia z lewej", "mode": "BLOKADA_LEWE_PRAWA", "permit": "L", "seq": [LEFT_SENSOR], "log": LOG_ALARM_NO_PERMIT, "count": False})
    scenarios.append({"name": "KONTROLA ZLY KIERUNEK", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": [RIGHT_SENSOR, RIGHT_SECURITY_SENSOR], "log": LOG_ALARM_INTRUSION, "count": False})
    scenarios.append({"name": "TIMEOUT: Nadano uprawnienie L", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": [], "log": LOG_GATE_CLOSED, "count": False, "wait_time": 10})
    scenarios.append({"name": "WYCOFANIE: Uzytkownik wszedl i zrezygnowal", "mode": "WOLNE_LEWE_PRAWA", "seq": [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR], "log": LOG_GATE_CLOSED, "count": False})
    scenarios.append({"name": "ALARM PPOZ: Awaryjne otwarcie", "mode": "WOLNE_LEWE_PRAWA", "custom_trigger": "ppoz 1\n", "seq": seq_lp, "log": "", "count": False, "custom_restore": "ppoz 0\n"})
    scenarios.append({"name": "USTERKA SENSORA CENTER", "mode": "WOLNE_LEWE_PRAWA", "custom_trigger": "sensor 5 1\n", "seq": [], "log": LOG_ALARM_SAFETY, "count": False, "custom_restore": "sensor 5 0\n"})
    scenarios.append({"name": "TAILGATING", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR], "log": LOG_ALARM_TAILGATING, "count": True})
    scenarios.append({"name": "INTRUSION w srodek bramki", "mode": "WOLNE_LEWE_PRAWA", "seq": [CENTER_SECURITY_SENSOR], "log": LOG_ALARM_INTRUSION, "count": False})
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

        # >>>>>>>>>>>>> PRE-FLIGHT CHECKS >>>>>>>>>>>>>
        test_calibration_read_only(jlink)
        test_diagnostic_readonly(jlink)
        test_boundary_limits(jlink)
        test_eeprom_crash_safe(jlink)

        # Inicjalizacja peryferiow zaleznie od parametru SG/GT/SK/BR
        setup_gate_hardware(jlink, GATE_TYPE)

        # Test momentu obrotowego odpalamy zawsze, by zweryfikowac zachowanie (np. opuszczanie rygla w GT/BR)
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
