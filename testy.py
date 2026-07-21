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
POKE_DELAY_TIME = 0.5
POKE_DELAY_EXIT_TIME = 0.5

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

# --- OCZEKIWANE LOGI Z SYSTEMU ---
LOG_GATE_OPENED    = "Permit manager: GATE OPENED"
LOG_GATE_CLOSED    = "Permit manager: GATE CLOSED"
LOG_ALARM_INTRUSION  = "ALARM INTRUSION"
LOG_ALARM_TAILGATING = "ALARM TAILGATING"
LOG_MOTOR_ERROR    = "MOTOR ERROR"
LOG_ALARM_NO_PERMIT  = "ALARM NO PERMIT"
LOG_ALARM_SAFETY   = "SAFETY ALARM"

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

def get_counters(jlink, timeout_sec=1.0):
    global right_counter, left_counter

    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.1)
    rtt = ''
    start_time_c = time.time()
    pattern_right = r"right counter:(\d+)"
    pattern_left  = r"left counter:(\d+)"

    while time.time() - start_time_c < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])

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
def rtt_get_param(jlink, idx, timeout_sec=1.0):
    jlink.rtt_write(0, 'get {}\n'.format(idx).encode('utf-8'))
    start_t = time.time()
    rtt = ''
    while time.time() - start_t < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])
    return rtt

def rtt_set_and_verify(jlink, idx, val, is_remote=False):
    monitor_window = 5.0 if is_remote else 3.0
    collected_logs = ""

    for attempt in range(4):
        print("\n--- [PROBA ZAPISU {}] Ustawianie parametru {} = {} (remote={}) ---".format(
            attempt + 1, idx, val, is_remote))

        try:
            jlink.rtt_read(0, 4096)
        except Exception as e:
            print("   [WARN] Pre-write drain error (ignored): {}".format(e))

        jlink.rtt_write(0, 'set {} {}\n'.format(idx, val).encode('utf-8'))

        collected_logs = ""
        start_monitor = time.time()

        print("   [MONITOR] Nasłuch RTT przez {}s...".format(monitor_window))
        while time.time() - start_monitor < monitor_window:
            chunk = jlink.rtt_read(0, 1024)
            if chunk:
                text = "".join([chr(c) for c in chunk])
                sys.stdout.write(text)
                sys.stdout.flush()
                collected_logs += text
            time.sleep(0.01)

        print("\n   [MONITOR] Zakończono okno nasłuchu.")

        if ("Watchdog" in collected_logs or "WDG" in collected_logs
                or "reset" in collected_logs.lower()):
            print("   [KATASTROFA] Wykryto sprzętowy RESET/WATCHDOG w logach podczas zapisu!")
            return False, collected_logs

        jlink.rtt_write(0, b'\n')
        time.sleep(0.2)
        try:
            jlink.rtt_read(0, 256)
        except Exception:
            pass

        resp = rtt_get_param(jlink, idx, 1.5 if is_remote else 1.0)
        print("   [DEBUG-RTT] Odpowiedz na GET: {}".format(repr(resp)))

        clean_resp = resp.replace('get {}\n'.format(idx), '')
        digits = re.findall(r'\d+', clean_resp)

        if digits:
            read_val = int(digits[-1])
            if read_val == val:
                print("   [SUKCES] Parametr poprawnie zweryfikowany.")
                return True, collected_logs
            else:
                print("   [SYNC FAIL] Zgłasza {}, oczekiwano {}. Ponawiam...".format(
                    read_val, val))
        else:
            print("   [SYNC FAIL] Brak jasnej odpowiedzi cyfrowej na GET.")

    return False, collected_logs

def safe_rtt_restart(jlink, delay=None, wait_for_link=True):
    if delay is None:
        delay = BOOT_WAIT_MASTER

    jlink.rtt_write(0, b'reset\n')
    print("   [RESET] Czekam {}s na wstepny start Mastera...".format(delay))
    time.sleep(delay)

    try:
        jlink.rtt_stop()
        time.sleep(0.2)
        jlink.rtt_start()
    except Exception as e:
        print("[WARN] RTT restart napotkał błąd (kontynuuję): {}".format(e))

    if not wait_for_link:
        time.sleep(1)
        return

    print("   [BOOT] Czekam na potwierdzenie linku Master↔Slave "
          "(szukam: '{}', timeout {}s)...".format(LOG_SYSTEM_READY, SYSTEM_READY_TIMEOUT))

    rtt_buf = ""
    start_link = time.time()
    link_found = False

    while time.time() - start_link < SYSTEM_READY_TIMEOUT:
        chunk = jlink.rtt_read(0, 1024)
        if chunk:
            text = "".join([chr(c) for c in chunk])
            sys.stdout.write(text)
            sys.stdout.flush()
            rtt_buf += text
        if LOG_SYSTEM_READY in rtt_buf:
            link_found = True
            break
        time.sleep(0.05)

    if link_found:
        elapsed = time.time() - start_link
        print("   [BOOT] Link Master↔Slave potwierdzony po {:.1f}s. "
              "Bezpieczny zapis EE remote możliwy.".format(elapsed))
        time.sleep(0.5)
    else:
        print("   [BOOT WARN] Nie wykryto markera gotowości w ciągu {}s. "
              "Kontynuuję z dodatkowym opóźnieniem {}s (ryzyko WDG!).".format(
                  SYSTEM_READY_TIMEOUT, BOOT_WAIT_LINK))
        time.sleep(BOOT_WAIT_LINK)

# =========================================================
# PRE-FLIGHT CHECKS
# =========================================================
def test_calibration_read_only(jlink):
    print("\n[PRE-CHECK] Sprawdzanie bezpieczenstwa kalibracji...")
    response = rtt_get_param(jlink, 7)
    digits = re.findall(r'\d+', response.replace('get 7', ''))
    if not digits:
        print("Nie udalo sie odczytac kalibracji! Zatrzymuje test.")
        sys.exit(1)

    calib_val = int(digits[-1])
    if calib_val < 0 or calib_val > 4:
        print("BLAD: Kalibracja poza zakresem: {}. Zatrzymuje test!".format(calib_val))
        sys.exit(1)
    print("Kalibracja w normie. Odczytana wartosc: {}".format(calib_val))

def setup_gate_sg(jlink):
    """
    Wymusza konfigurację sprzętową specyficzną dla bramki SG:
    - Hamulec aktywny
    - Rygle i zbijak nieaktywne
    """
    print("\n[SETUP] Konfiguracja sprzetowa dla bramki SG (Tylko Hamulec + Silniki)...")

    # Włączamy Hamulec (idx 32 = 1) [EE remote]
    status, logs = rtt_set_and_verify(jlink, 32, 1, is_remote=True)
    if not status:
        print("\n[OSTRZEZENIE] Nie udalo sie wlaczyc hamulca (idx 32)! Ignoruje i kontynuuje test.")

    # Wyłączamy Rygle (idx 34 = 0) [EE remote]
    status, logs = rtt_set_and_verify(jlink, 34, 0, is_remote=True)
    if not status:
        print("\n[OSTRZEZENIE] Nie udalo sie wylaczyc rygli (idx 34)! Ignoruje i kontynuuje test.")

    # Wyłączamy rotację zbijaka (idx 38 = 0) [EE remote]
    status, logs = rtt_set_and_verify(jlink, 38, 0, is_remote=True)
    if not status:
        print("\n[OSTRZEZENIE] Nie udalo sie wylaczyc zbijaka (idx 38)! Ignoruje i kontynuuje test.")

    print("   [OK] Etap konfiguracji sprzetowej SG zakonczony. Reset + czekam na link Master↔Slave...")
    safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)

def test_find_optimal_torque(jlink):
    print("\n[PRE-CHECK] Pelne skanowanie Max Torque (1-20, EE remote)...")
    successful_torques = []

    for tq in range(1, 21):
        print("\n--- Skanowanie Max Torque: {} ---".format(tq))
        status, logs = rtt_set_and_verify(jlink, 28, tq, is_remote=True)
        if not status:
            print("\n[OSTRZEZENIE] Nie udalo sie zapisac momentu {}!"
                  "\n|| SUROWE LOGI: {}".format(tq, repr(logs)))
            print("Pomięcie testu dla momentu {} i kontynuacja...".format(tq))
            continue # Przechodzimy do kolejnej iteracji pętli zamiast przerywać skrypt

        print("   [OK] Zapisano. Reset + czekam na link Master↔Slave...")
        safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)
        mode_set(jlink, "KONTROLA_LEWE_PRAWA")
        time.sleep(1)
        print("   Wymuszam probe otwarcia...")
        add_permission(jlink, "L")

        rtt_buffer = ''
        start_t = time.time()
        result = "TIMEOUT"

        while time.time() - start_t < 6.0:
            chunk = jlink.rtt_read(0, 1024)
            if chunk:
                text = "".join([chr(c) for c in chunk])
                sys.stdout.write(text)
                sys.stdout.flush()
                rtt_buffer += text

                if LOG_MOTOR_ERROR in rtt_buffer:
                    result = "ERROR"
                    break
                elif LOG_GATE_OPENED in rtt_buffer:
                    result = "OPENED"
                    break

        if result in ("ERROR", "TIMEOUT"):
            reason = "MOTOR ERROR" if result == "ERROR" else "TIMEOUT"
            print("\n   [X] Moment {} OBLAL TEST ({}).".format(tq, reason))
        elif result == "OPENED":
            print("\n   [V] Moment {} ZALICZYL! Brama otwarta.".format(tq))
            successful_torques.append(tq)

            sensor_poke(jlink, LEFT_SENSOR)
            sensor_poke(jlink, LEFT_SECURITY_SENSOR)
            sensor_poke(jlink, CENTER_SECURITY_SENSOR)
            sensor_poke(jlink, RIGHT_SECURITY_SENSOR)
            sensor_poke(jlink, RIGHT_SENSOR)

            wait_for_logs(jlink, LOG_GATE_CLOSED, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
            time.sleep(2)

    # Co jeśli żaden moment nie przeszedł testu LUB nie dało się zapisać żadnego z nich?
    if not successful_torques:
        print("\n[OSTRZEZENIE] Brama nie ruszyla na zadnym momencie LUB zapis byl niemozliwy!")
        print("Testy beda kontynuowane na domyslnym (obecnym w pamieci) ustawieniu momentu.")
        print("   [OK] Przywracam tryb WOLNE_LEWE_PRAWA przed finalnym resetem.")
        mode_set(jlink, "WOLNE_LEWE_PRAWA")
        safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)
        return # Wychodzimy z funkcji, nie aplikujemy optymalnego momentu

    optimal_torque = min(successful_torques)

    print("\n=======================================================")
    print(" RAPORT SKANOWANIA MOMENTU OBROTOWEGO:")
    print(" Dzialajace wartosci: {}".format(successful_torques))
    print(" Optymalny prog: {}".format(optimal_torque))
    print("=======================================================\n")

    print("-> Aplikowanie optymalnego momentu ({})...".format(optimal_torque))
    status, logs = rtt_set_and_verify(jlink, 28, optimal_torque, is_remote=True)
    if not status:
        print("\n[OSTRZEZENIE] Nie mozna zaaplikowac finalnego momentu!"
              "\n|| SUROWE LOGI: {}".format(repr(logs)))
        print("Testy beda kontynuowane na ostatnim zachowanym ustawieniu.")

    print("   [OK] Przywracam tryb WOLNE_LEWE_PRAWA przed finalnym resetem.")
    mode_set(jlink, "WOLNE_LEWE_PRAWA")
    safe_rtt_restart(jlink, delay=BOOT_WAIT_MASTER, wait_for_link=True)

def test_diagnostics_counters(jlink):
    print("\n[TLO] Sprawdzanie licznikow diagnostycznych...")
    response = rtt_get_param(jlink, 60)
    digits = re.findall(r'\d+', response.replace('get 60', ''))
    if digits:
        err_count = int(digits[-1])
        if err_count > 0:
            print("OSTRZEZENIE: Wykryto {} bledow komunikacji Master-Slave!".format(err_count))
            
    response2 = rtt_get_param(jlink, 67)
    digits2 = re.findall(r'\d+', response2.replace('get 67', ''))
    if digits2:
        s_err = int(digits2[-1])
        if s_err > 0:
            print("OSTRZEZENIE: Slave zgłasza {} bledow komunikacji!".format(s_err))

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

    for index, sensor in enumerate(seq):
        jlink.rtt_write(0, 'sensor {} 1\n'.format(sensor).encode('utf-8'))
        time.sleep(POKE_DELAY_TIME)

        if interrupt_step and index == interrupt_step["after_index"]:
            print("\n[!] ALARM: Naruszenie czujnika {} w trakcie ruchu!".format(
                interrupt_step['sensor']))
            jlink.rtt_write(0, 'sensor {} 1\n'.format(
                interrupt_step["sensor"]).encode('utf-8'))
            time.sleep(0.5)
            check_for_log_bool(jlink, LOG_ALARM_SAFETY, 2)
            jlink.rtt_write(0, 'sensor {} 0\n'.format(
                interrupt_step["sensor"]).encode('utf-8'))

        jlink.rtt_write(0, 'sensor {} 0\n'.format(sensor).encode('utf-8'))
        time.sleep(POKE_DELAY_EXIT_TIME)

    if expected_log:
        found = check_for_log_bool(jlink, expected_log, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
        if not found:
            print("\nBLAD: Oczekiwano logu '{}', ale go zabraklo! - TEST FAILED".format(
                expected_log))
            play_beep(440, 500)
            sys.exit(1)
        print("\nSUKCES: Zweryfikowano zachowanie '{}'.".format(expected_log))

    time.sleep(1)

    end_r, end_l = get_counters(jlink, 1)
    total_start = start_r + start_l
    total_end   = end_r + end_l

    if expect_count:
        if total_end <= total_start:
            print("\nBLAD: Zliczanie przejscia NIE powiodlo sie! - TEST FAILED")
            sys.exit(1)
        else:
            right_counter, left_counter = end_r, end_l
            print("\nSUKCES: Licznik wzrosl (L:{}, R:{})".format(
                left_counter, right_counter))
    else:
        if total_end > total_start:
            print("\nBLAD: System nieslusznie zliczyl przejscie! - TEST FAILED")
            sys.exit(1)
        else:
            print("\nSUKCES: System poprawnie zignorowal nieudane przejscie.")

# =========================================================
# GENERATOR BAZY TESTOW BEHAWIORALNYCH
# =========================================================
def generate_100_scenarios():
    scenarios = []

    for i in range(10):
        seq_lp = ([LEFT_SENSOR] * ((i % 2) + 1)
                  + [LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR,
                     RIGHT_SECURITY_SENSOR, RIGHT_SENSOR])
        scenarios.append({
            "name": "WOLNE L->P (wahanie {}x)".format(i % 2 + 1),
            "mode": "WOLNE_LEWE_PRAWA", "seq": seq_lp,
            "log": LOG_GATE_CLOSED, "count": True
        })
        seq_pl = ([RIGHT_SENSOR] * ((i % 2) + 1)
                  + [RIGHT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR,
                     LEFT_SECURITY_SENSOR, LEFT_SENSOR])
        scenarios.append({
            "name": "WOLNE P->L (wahanie {}x)".format(i % 2 + 1),
            "mode": "WOLNE_LEWE_PRAWA", "seq": seq_pl,
            "log": LOG_GATE_CLOSED, "count": True
        })

    for i in range(10):
        seq_lp = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR,
                  RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
        scenarios.append({
            "name": "KONTROLA L->P (Z uprawnieniem)",
            "mode": "KONTROLA_LEWE_PRAWA", "permit": "L",
            "seq": seq_lp, "log": LOG_GATE_CLOSED, "count": True
        })
        scenarios.append({
            "name": "KONTROLA L->P (Odbicie, brak upr)",
            "mode": "KONTROLA_LEWE_PRAWA", "permit": None,
            "seq": [LEFT_SENSOR], "log": LOG_ALARM_NO_PERMIT, "count": False
        })

    for i in range(15):
        if i % 2 == 0:
            seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR,
                   RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
            scenarios.append({
                "name": "ASYMETRIA: Wolne przejscie L->P",
                "mode": "WOLNE_LEWE_KONTROLA_PRAWE", "seq": seq,
                "log": LOG_GATE_CLOSED, "count": True
            })
        else:
            scenarios.append({
                "name": "ASYMETRIA: Brak uprawnien P->L",
                "mode": "WOLNE_LEWE_KONTROLA_PRAWE", "seq": [RIGHT_SENSOR],
                "log": LOG_ALARM_NO_PERMIT, "count": False
            })

    for i in range(15):
        scenarios.append({
            "name": "Wycofanie po wejsciu",
            "mode": "WOLNE_LEWE_PRAWA",
            "seq": [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR],
            "log": LOG_GATE_CLOSED, "count": False
        })

    for i in range(15):
        if i % 3 == 0:
            scenarios.append({
                "name": "Wtargniecie w swiatlo bramki",
                "mode": "WOLNE_LEWE_PRAWA", "seq": [CENTER_SECURITY_SENSOR],
                "log": LOG_ALARM_INTRUSION, "count": False
            })
        elif i % 3 == 1:
            scenarios.append({
                "name": "Proba jazdy na ogonie",
                "mode": "WOLNE_LEWE_PRAWA",
                "seq": [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR,
                        CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR],
                "log": LOG_ALARM_TAILGATING, "count": True
            })
        else:
            scenarios.append({
                "name": "Czolganie pod szybami",
                "mode": "WOLNE_LEWE_PRAWA",
                "seq": [LEFT_DOWN_SENSOR, RIGHT_DOWN_SENSOR],
                "log": "", "count": False
            })

    for i in range(15):
        scenarios.append({
            "name": "ANTI-CRUSH: Naruszenie w trakcie ruchu",
            "mode": "WOLNE_LEWE_PRAWA",
            "seq": [LEFT_SENSOR, LEFT_SECURITY_SENSOR],
            "interrupt": {"after_index": 0, "sensor": CENTER_SECURITY_SENSOR},
            "log": LOG_ALARM_SAFETY, "count": False
        })

    return scenarios

# =========================================================
# GLOWNY SKRYPT
# =========================================================
def main():
    global right_counter, left_counter

    print("\n=======================================================")
    print(" TYP BRAMKI: {}".format(GATE_TYPE))
    print("=======================================================\n")

    if GATE_TYPE != "SG":
        print("\n-----------========== DIAGNOSE ============-------------")
        print("Brak obslugi testow dla bramki {}. Funkcjonalnosc w przygotowaniu!".format(GATE_TYPE))
        print("Zatrzymuje wykonywanie skryptu.")
        sys.exit(1)

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
        print("Reset wysłany. Czekam na pełny boot Master+Slave...")

        time.sleep(BOOT_WAIT_MASTER)
        try:
            jlink.rtt_stop()
            time.sleep(0.2)
            jlink.rtt_start()
        except Exception as e:
            print("[WARN] RTT restart po pierwszym resecie: {}".format(e))

        print("Oczekiwanie na gotowość systemu (marker: '{}')...".format(LOG_SYSTEM_READY))
        rtt_buf = ""
        start_boot = time.time()
        while time.time() - start_boot < SYSTEM_READY_TIMEOUT:
            chunk = jlink.rtt_read(0, 1024)
            if chunk:
                text = "".join([chr(c) for c in chunk])
                sys.stdout.write(text)
                sys.stdout.flush()
                rtt_buf += text
            if LOG_SYSTEM_READY in rtt_buf:
                print("\n[BOOT] System gotowy po {:.1f}s.".format(
                    time.time() - start_boot))
                break
            time.sleep(0.05)
        else:
            print("[BOOT WARN] Marker gotowości nie wykryty — kontynuuję.")

        # >>>>>>>>>>>>> PRE-FLIGHT CHECKS >>>>>>>>>>>>>
        test_calibration_read_only(jlink)

        if GATE_TYPE == "SG":
            setup_gate_sg(jlink)

        test_find_optimal_torque(jlink)

        # >>>>>>>>>>>>> SETUP PRZED GLOWNA PETLA >>>>>>>>>>>>>
        mode_set(jlink, "WOLNE_LEWE_PRAWA")
        right_counter, left_counter = get_counters(jlink, 1)

        scenarios_pool = generate_100_scenarios()

        print("\n=======================================================")
        print(" BAZA TESTOWA ZALADOWANA. Wariantow: {}. Nieskonczonosc: {}".format(
            len(scenarios_pool), IS_INFINITE))
        if not IS_INFINITE and NUMBER_OF_TESTS > len(scenarios_pool):
            print(" UWAGA: NUMBER_OF_TESTS ({}) > pula ({}). "
                  "Scenariusze beda powtarzane.".format(
                      NUMBER_OF_TESTS, len(scenarios_pool)))
        print("=======================================================\n")

        count = 0
        while True:
            scenario_index = count % len(scenarios_pool)
            if count > 0 and scenario_index == 0:
                print("\n[INFO] Pula scenariuszy wyczerpana — "
                      "rozpoczynam kolejna iteracje od poczatku.\n")

            execute_custom_sequence(jlink, count + 1, scenarios_pool[scenario_index])
            count += 1

            if count % 15 == 0:
                test_diagnostics_counters(jlink)

            if not IS_INFINITE and count >= NUMBER_OF_TESTS:
                break

        minutes, seconds = divmod(time.time() - start_time, 60)
        print("\nTest finished successfully — czas: {} min {:.2f} s".format(
            int(minutes), seconds))

    finally:
        try:
            jlink.close()
            print("[CLEANUP] J-Link connection closed.")
        except Exception as e:
            print("[CLEANUP] Warning: error while closing J-Link: {}".format(e))

if __name__ == "__main__":
    main()
