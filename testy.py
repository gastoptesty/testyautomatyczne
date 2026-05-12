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
except:
    NUMBER_OF_TESTS = 100
    IS_INFINITE = False

# =========================================================
# ZMIENNE I STALE SYSTEMOWE
# =========================================================
SIZE_TEST_VECTOR = 4
WAIT_TIME_FOR_GATE_ARM_MOVEMENT = 6
WAIT_TIMEOUT = 30
POKE_DELAY_TIME = 0.5
POKE_DELAY_EXIT_TIME = 0.5
HOLD_DELAY_TIME = 1

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
LOG_GATE_OPENED = "Permit manager: GATE OPENED"
LOG_GATE_CLOSED = "Permit manager: GATE CLOSED"
LOG_ALARM_INTRUSION = "ALARM INTRUSION"       
LOG_ALARM_TAILGATING = "ALARM TAILGATING"     
LOG_MOTOR_ERROR = "MOTOR ERROR"               
LOG_ALARM_NO_PERMIT = "ALARM NO PERMIT"       
LOG_ALARM_SAFETY = "SAFETY ALARM"             

# =========================================================
# FUNKCJE POMOCNICZE BAZOWE
# =========================================================
def play_beep(freq, duration):
    if platform.system() == "Windows":
        import winsound
        winsound.Beep(freq, duration)

def wait_for_logs(log, timeout_sec):
    rtt_buffer = ''
    start_time_log = time.time()
    while time.time() - start_time_log < timeout_sec:
        # KLUCZOWA ZMIANA: Czytamy duże bloki danych, a nie po 1 znaku
        data = jlink.rtt_read(0, 2048) 
        if data:
            rtt_buffer += "".join(map(chr, data))
        if log in rtt_buffer:
            return True
        time.sleep(0.01) # Dajemy procesorowi odetchnąć
        
    print("-----------============ LOGS ============-------------")
    print(rtt_buffer)
    print("-----------========== DIAGNOSE ============-------------")
    print("Timeout reached. Log:'{}' not found. - TEST FAILED".format(log))
    play_beep(440, 500)  
    sys.exit(1)

def check_for_log_bool(log, timeout_sec):
    rtt_buffer = ''
    start_time_log = time.time()
    while time.time() - start_time_log < timeout_sec:
        data = jlink.rtt_read(0, 2048)
        if data:
            rtt_buffer += "".join(map(chr, data))
        if log in rtt_buffer:
            return True
        time.sleep(0.01)
    return False

def sensor_poke(num):
    jlink.rtt_write(0, 'sensor {} 1\r\n'.format(num).encode('utf-8'))
    time.sleep(POKE_DELAY_TIME)
    jlink.rtt_write(0, 'sensor {} 0\r\n'.format(num).encode('utf-8'))
    time.sleep(POKE_DELAY_EXIT_TIME)

def reset():
    jlink.rtt_write(0, b'reset\r\n')
    time.sleep(0.5)

def mode_set(mode):
    global current_mode
    strings_table = [
        "WOLNE_LEWE_PRAWA", "WOLNE_LEWE_KONTROLA_PRAWE", "WOLNE_PRAWE_KONTROLA_LEWE",
        "KONTROLA_LEWE_PRAWA", "BLOKADA_LEWE_PRAWA", "BEZ_BLOKADY_LEWE_PRAWA"
    ]
    if mode in strings_table:
        jlink.rtt_write(0, 'mode {}\r\n'.format(strings_table.index(mode)).encode('utf-8'))
        time.sleep(0.5)
        current_mode = mode
    else:
        print("Mode:{} not found. - TEST FAILED".format(mode))
        play_beep(440, 500)
        sys.exit(1)

def add_permission(direction):
    if direction == "L":
        jlink.rtt_write(0, b'add_l\r\n')
    elif direction == "R":
        jlink.rtt_write(0, b'add_r\r\n')
    time.sleep(0.2)

def get_counters(timeout_sec=1.0):
    jlink.rtt_write(0, b'counter\r\n')
    time.sleep(0.1)
    rtt_buffer = ''
    start_time_c = time.time()
    pattern_right = r"right counter:(\d+)"
    pattern_left = r"left counter:(\d+)"

    while time.time() - start_time_c < timeout_sec:
        data = jlink.rtt_read(0, 1024)
        if data:
            rtt_buffer += "".join(map(chr, data))
        time.sleep(0.01)

    matches_r = re.findall(pattern_right, rtt_buffer)
    matches_l = re.findall(pattern_left, rtt_buffer)

    if matches_r and matches_l:
        right_val = int(matches_r[-1])
        left_val = int(matches_l[-1])
        return right_val, left_val
    return right_counter, left_counter

# =========================================================
# FUNKCJE RTT (GET / SET / VERIFY)
# =========================================================
def rtt_get_param(idx, timeout_sec=1.0):
    jlink.rtt_write(0, 'get {}\r\n'.format(idx).encode('utf-8'))
    start_t = time.time()
    rtt_buffer = ''
    while time.time() - start_t < timeout_sec:
        data = jlink.rtt_read(0, 1024)
        if data:
            rtt_buffer += "".join(map(chr, data))
        time.sleep(0.01)
    return rtt_buffer

def rtt_set_and_verify(idx, val):
    """ Ustawia parametr udajac fizyczna klawiature i weryfikuje zapis w bramce. """
    for attempt in range(5):
        # 1. Agresywne czyszczenie bufora odczytu ze smieci
        try:
            jlink.rtt_read(0, 4096)
        except:
            pass

        # 2. Wyslanie komendy SET ZNAK PO ZNAKU
        cmd_set = 'set {} {}\r\n'.format(idx, val)
        for char in cmd_set:
            jlink.rtt_write(0, char.encode('utf-8'))
            time.sleep(0.02)
            
        time.sleep(1.5) 
        
        # 3. Czysczenie bufora po wysłaniu komendy
        try:
            jlink.rtt_read(0, 4096)
        except:
            pass
            
        # 4. Zapytanie weryfikacyjne GET
        cmd_get = 'get {}\r\n'.format(idx)
        for char in cmd_get:
            jlink.rtt_write(0, char.encode('utf-8'))
            time.sleep(0.02)
            
        start_t = time.time()
        rtt_buffer = ''
        
        while time.time() - start_t < 1.0:
            data = jlink.rtt_read(0, 1024)
            if data:
                rtt_buffer += "".join(map(chr, data))
            time.sleep(0.01)
                
        # 5. Ekstrakcja liczby z odpowiedzi bramki
        clean_rtt = rtt_buffer.replace('get', '').replace(str(idx), '')
        digits = re.findall(r'\d+', clean_rtt)
        
        if digits:
            read_val = int(digits[-1])
            if read_val == val:
                return True
            else:
                print("   [SYNC FAIL] Chciano ustawic {}, ale bramka zwrocila {}. Ponawiam...".format(val, read_val))
                print("   [DEBUG RTT] Surowa odpowiedz bramki: {}".format(repr(rtt_buffer)))
        else:
            print("   [SYNC FAIL] Brak jasnej liczbowej odpowiedzi bramki. Ponawiam...")
            print("   [DEBUG RTT] Surowa odpowiedz bramki: {}".format(repr(rtt_buffer)))
            
    return False

# =========================================================
# PRE-FLIGHT CHECKS (Testy i kalibracje)
# =========================================================
def test_calibration_read_only():
    print("\n[PRE-CHECK] Sprawdzanie bezpieczenstwa kalibracji...")
    response = rtt_get_param(7)
    digits = re.findall(r'\d+', response.replace('get 7', '')) 
    if not digits:
        print("Nie udalo sie odczytac kalibracji! Zatrzymuje test ze wzgledow bezpieczenstwa.")
        sys.exit(1)
        
    calib_val = int(digits[-1])
    
    if calib_val < 0 or calib_val > 4:
        print("BLAD: Kalibracja poza bezpiecznym zakresem: {}. Zatrzymuje test!".format(calib_val))
        sys.exit(1)
    print("Kalibracja w normie. Odczytana wartosc zerowa: {}".format(calib_val))

def test_find_optimal_torque():
    print("\n[PRE-CHECK] Pelne skanowanie parametrow momentu obrotowego (Max Torque 1-20)...")
    
    successful_torques = []
    
    for tq in range(1, 21):
        print("\n--- Skanowanie wartosci Max Torque: {} ---".format(tq))
        
        if not rtt_set_and_verify(28, tq):
            print("BLAD KRYTYCZNY: Nie udalo sie fizycznie przestawic momentu obrotowego na {}!".format(tq))
            sys.exit(1)
            
        print("   [OK] Bramka potwierdzila zapis momentu ({}). Uruchamiam logike...".format(tq))
        
        mode_set("KONTROLA_LEWE_PRAWA")
        time.sleep(1)
        
        print("   Wymuszam ruch skrzydla (add_l)...")
        add_permission("L")
        
        rtt_buffer = ''
        start_t = time.time()
        result = "TIMEOUT"
        
        while time.time() - start_t < 4.0:
            data = jlink.rtt_read(0, 1024)
            if data:
                rtt_buffer += "".join(map(chr, data))
                
                if LOG_MOTOR_ERROR in rtt_buffer:
                    result = "ERROR"
                    break
                elif LOG_GATE_OPENED in rtt_buffer:
                    result = "OPENED"
                    break
            time.sleep(0.01)
        
        if result == "ERROR" or result == "TIMEOUT":
            reason = "MOTOR ERROR" if result == "ERROR" else "TIMEOUT"
            print("   [X] Moment {} OBLAL TEST ({}). Robie bezpieczny reset...".format(tq, reason))
            
            jlink.rtt_write(0, b'reset\r\n')
            time.sleep(3) 
            
            try:
                jlink.rtt_stop()
                time.sleep(0.2)
                jlink.rtt_start()
            except:
                pass
            
        elif result == "OPENED":
            print("   [V] Moment {} ZALICZYL TEST! Brama w pelni otwarta.".format(tq))
            successful_torques.append(tq)
            
            sensor_poke(LEFT_SENSOR)
            sensor_poke(LEFT_SECURITY_SENSOR)
            sensor_poke(CENTER_SECURITY_SENSOR)
            sensor_poke(RIGHT_SECURITY_SENSOR)
            sensor_poke(RIGHT_SENSOR)
            
            wait_for_logs(LOG_GATE_CLOSED, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
            
            jlink.rtt_write(0, b'reset\r\n')
            time.sleep(3)
            try:
                jlink.rtt_stop()
                time.sleep(0.2)
                jlink.rtt_start()
            except:
                pass

    if not successful_torques:
        print("\nBLAD KRYTYCZNY: Na zadnym momencie obrotowym (1-20) brama nie ruszyla poprawnie!")
        sys.exit(1)
        
    optimal_torque = min(successful_torques)
    
    print("\n=======================================================")
    print(" RAPORT SKANOWANIA MOMENTU OBROTOWEGO:")
    print(" Dzialajace wartosci (bez bledu silnika): {}".format(successful_torques))
    print(" Najmniejszy dzialajacy prog: {}".format(optimal_torque))
    print("=======================================================\n")
    
    print("-> Aplikowanie optymalnego momentu ({}) na reszte testow...".format(optimal_torque))
    if not rtt_set_and_verify(28, optimal_torque):
        print("BLAD KRYTYCZNY: Nie mozna zaaplikowac finalnego momentu!")
        sys.exit(1)
    time.sleep(1)
    
def test_diagnostics_counters():
    print("\n[TLO] Sprawdzanie licznikow diagnostycznych w tle...")
    response = rtt_get_param(60) 
    digits = re.findall(r'\d+', response.replace('get 60', ''))
    if digits:
        err_count = int(digits[-1])
        if err_count > 0:
            print("OSTRZEZENIE: Wykryto {} bledow komunikacji Master-Slave!".format(err_count))

# =========================================================
# SILNIK WYKONAWCZY SEKWENCJI
# =========================================================
def execute_custom_sequence(iter_num, config):
    name = config["name"]
    seq = config["seq"]
    expected_log = config["log"]
    expect_count = config["count"]
    req_mode = config.get("mode", "WOLNE_LEWE_PRAWA")
    permit = config.get("permit", None)
    interrupt_step = config.get("interrupt", None) 

    print("\n=======================================================")
    print(">>> TEST NR: {} | {}".format(iter_num, name))
    
    if current_mode != req_mode:
        print("Ustawianie trybu: {}".format(req_mode))
        mode_set(req_mode)

    global right_counter, left_counter
    start_r, start_l = get_counters(1)

    if permit:
        print("Nadawanie uprawnienia dla: {}".format(permit))
        add_permission(permit)

    for index, sensor in enumerate(seq):
        jlink.rtt_write(0, 'sensor {} 1\r\n'.format(sensor).encode('utf-8'))
        time.sleep(POKE_DELAY_TIME)
        
        if interrupt_step and index == interrupt_step["after_index"]:
            print("[!] WYWOLANIE ALARMU: Naruszenie czujnika {} w trakcie ruchu!".format(interrupt_step['sensor']))
            jlink.rtt_write(0, 'sensor {} 1\r\n'.format(interrupt_step["sensor"]).encode('utf-8'))
            time.sleep(0.5)
            check_for_log_bool(LOG_ALARM_SAFETY, 2)
            jlink.rtt_write(0, 'sensor {} 0\r\n'.format(interrupt_step["sensor"]).encode('utf-8'))

        jlink.rtt_write(0, 'sensor {} 0\r\n'.format(sensor).encode('utf-8'))
        time.sleep(POKE_DELAY_EXIT_TIME)

    if expected_log:
        found = check_for_log_bool(expected_log, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
        if not found:
            print("BLAD: Oczekiwano logu '{}', ale go zabraklo! - TEST FAILED".format(expected_log))
            play_beep(440, 500)
            sys.exit(1)
        print("SUKCES: Zweryfikowano zachowanie '{}'.".format(expected_log))
    
    time.sleep(1) 
    
    end_r, end_l = get_counters(1)
    total_start = start_r + start_l
    total_end = end_r + end_l

    if expect_count:
        if total_end <= total_start:
            print("BLAD: Zliczanie przejscia NIE powiodlo sie, a powinno! - TEST FAILED")
            sys.exit(1)
        else:
            right_counter, left_counter = end_r, end_l
            print("SUKCES: Licznik poprawnie wzrosl (Obecnie: L:{}, R:{})".format(left_counter, right_counter))
    else:
        if total_end > total_start:
            print("BLAD: System nieslusznie zliczyl przejscie (np. podczas alarmu)! - TEST FAILED")
            sys.exit(1)
        else:
            print("SUKCES: System poprawnie zignorowal nieudane przejscie.")

# =========================================================
# GENERATOR BAZY TESTOW BEHAWIORALNYCH
# =========================================================
def generate_100_scenarios():
    scenarios = []

    for i in range(10):
        seq_lp = [LEFT_SENSOR] * ((i % 2) + 1) + [LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
        scenarios.append({"name": "WOLNE L->P (wahanie {}x)".format(i%2 + 1), "mode": "WOLNE_LEWE_PRAWA", "seq": seq_lp, "log": LOG_GATE_CLOSED, "count": True})
        seq_pl = [RIGHT_SENSOR] * ((i % 2) + 1) + [RIGHT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR]
        scenarios.append({"name": "WOLNE P->L (wahanie {}x)".format(i%2 + 1), "mode": "WOLNE_LEWE_PRAWA", "seq": seq_pl, "log": LOG_GATE_CLOSED, "count": True})

    for i in range(10):
        seq_lp = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
        scenarios.append({"name": "KONTROLA L->P (Z uprawnieniem)", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": seq_lp, "log": LOG_GATE_CLOSED, "count": True})
        seq_reject = [LEFT_SENSOR]
        scenarios.append({"name": "KONTROLA L->P (Odbicie, brak upr)", "mode": "KONTROLA_LEWE_PRAWA", "permit": None, "seq": seq_reject, "log": LOG_ALARM_NO_PERMIT, "count": False})

    for i in range(15):
        if i % 2 == 0:
            seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
            scenarios.append({"name": "ASYMETRIA: Wolne przejscie L->P", "mode": "WOLNE_LEWE_KONTROLA_PRAWE", "seq": seq, "log": LOG_GATE_CLOSED, "count": True})
        else:
            seq = [RIGHT_SENSOR]
            scenarios.append({"name": "ASYMETRIA: Brak uprawnien P->L", "mode": "WOLNE_LEWE_KONTROLA_PRAWE", "seq": seq, "log": LOG_ALARM_NO_PERMIT, "count": False})

    for i in range(15):
        seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR]
        scenarios.append({"name": "Wycofanie po wejsciu", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "log": LOG_GATE_CLOSED, "count": False})

    for i in range(15):
        if i % 3 == 0:
            seq = [CENTER_SECURITY_SENSOR]
            scenarios.append({"name": "Wtargniecie w swiatlo bramki", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "log": LOG_ALARM_INTRUSION, "count": False})
        elif i % 3 == 1:
            seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
            scenarios.append({"name": "Proba jazdy na ogonie", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "log": LOG_ALARM_TAILGATING, "count": True})
        else:
            seq = [LEFT_DOWN_SENSOR, RIGHT_DOWN_SENSOR]
            scenarios.append({"name": "Czolganie pod szybami", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "log": "", "count": False})

    for i in range(15):
        seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR]
        interrupt = {"after_index": 0, "sensor": CENTER_SECURITY_SENSOR}
        scenarios.append({"name": "ANTI-CRUSH: Naruszenie w trakcie ruchu", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "interrupt": interrupt, "log": LOG_ALARM_SAFETY, "count": False})

    return scenarios

# =========================================================
# GLOWNY SKRYPT
# =========================================================

jlink = pylink.JLink()
emulators = jlink.connected_emulators()

if not emulators:
    print("Nie znaleziono zadnych urzadzen J-Link.")
    sys.exit(1)

selected_sn = emulators[0].SerialNumber
jlink.open(serial_no=selected_sn)
jlink.connect("STM32F030RC", verbose=True)
jlink.rtt_start()
jlink.restart()

wait_for_logs("MODE:", 1)
time.sleep(2)

# >>>>>>>>>>>>> PRE-FLIGHT CHECKS >>>>>>>>>>>>>
test_calibration_read_only()
test_find_optimal_torque()

# >>>>>>>>>>>>> SETUP PRZED GŁÓWNA PETLA >>>>>>>>>>>>>
mode_set("WOLNE_LEWE_PRAWA")
right_counter, left_counter = get_counters(1)

scenarios_pool = generate_100_scenarios()

print("\n=======================================================")
print(" BAZA TESTOWA ZALADOWANA. Wariantow: {}. Nieskonczonosc: {}".format(len(scenarios_pool), IS_INFINITE))
print("=======================================================\n")

# >>>>>>>>>>>>> GLOWNA PETLA WYKONAWCZA >>>>>>>>>>>>>
count = 0
while True:
    current_scenario = scenarios_pool[count % len(scenarios_pool)]
    
    execute_custom_sequence(count + 1, current_scenario)
    
    count += 1
    
    if count % 15 == 0:
        test_diagnostics_counters()

    if not IS_INFINITE and count >= NUMBER_OF_TESTS:
        break

# >>>>>>>>>>>>> ZAKONCZENIE >>>>>>>>>>>>>
minutes, seconds = divmod(time.time() - start_time, 60)
print("\nTest finished successfully - time: {} minutes {:.2f} seconds".format(int(minutes), seconds))

jlink.close()
sys.exit(0)
