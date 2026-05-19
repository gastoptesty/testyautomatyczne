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
    rtt = ''
    start_time_log = time.time()
    while time.time() - start_time_log < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])
        if rtt[-len(log):] == log:
            return True
    print("-----------============ LOGS ============-------------")
    print(rtt)
    print("-----------========== DIAGNOSE ============-------------")
    print("Timeout reached. Log:'{}' not found. - TEST FAILED".format(log))
    play_beep(440, 500)  
    sys.exit(1)

def check_for_log_bool(log, timeout_sec):
    rtt = ''
    start_time_log = time.time()
    while time.time() - start_time_log < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])
        if rtt[-len(log):] == log:
            return True
    return False

def sensor_poke(num):
    jlink.rtt_write(0, 'sensor {} 1\n'.format(num).encode('utf-8'))
    time.sleep(POKE_DELAY_TIME)
    jlink.rtt_write(0, 'sensor {} 0\n'.format(num).encode('utf-8'))
    time.sleep(POKE_DELAY_EXIT_TIME)

def mode_set(mode):
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
        print("Mode:{} not found. - TEST FAILED".format(mode))
        play_beep(440, 500)
        sys.exit(1)

def add_permission(direction):
    if direction == "L":
        jlink.rtt_write(0, b'add_l\n')
    elif direction == "R":
        jlink.rtt_write(0, b'add_r\n')
    time.sleep(0.2)

def get_counters(timeout_sec=1.0):
    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.1)
    rtt = ''
    start_time_c = time.time()
    pattern_right = r"right counter:(\d+)"
    pattern_left = r"left counter:(\d+)"

    while time.time() - start_time_c < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0]) 

    matches_r = re.findall(pattern_right, rtt)
    matches_l = re.findall(pattern_left, rtt)

    if matches_r and matches_l:
        right_val = int(matches_r[-1])
        left_val = int(matches_l[-1])
        return right_val, left_val
    return right_counter, left_counter

# =========================================================
# FUNKCJE RTT (GET / SET / VERIFY)
# =========================================================
def rtt_get_param(idx, timeout_sec=1.0):
    jlink.rtt_write(0, 'get {}\n'.format(idx).encode('utf-8'))
    start_t = time.time()
    rtt = ''
    while time.time() - start_t < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])
    return rtt

def rtt_set_and_verify(idx, val):
    for attempt in range(4):
        # 1. Wysylamy komende zapisu
        jlink.rtt_write(0, 'set {} {}\n'.format(idx, val).encode('utf-8'))
        
        # Czekamy 1 sekunde, aby procesor spokojnie zapisal dane do pamieci Flash 
        # (co w STM32 zamraza uklad)
        time.sleep(1.0)
        
        # --- RESUSCYTACJA RTT ---
        # Zatrzymujemy i wznawiamy nasluch w J-Linku, aby podniesc przerwane 
        # polaczenie po "zamrozeniu" szyny pamieci przez zapis do Flasha.
        try:
            jlink.rtt_stop()
            time.sleep(0.1)
            jlink.rtt_start()
        except:
            pass
        # ------------------------
        
        # 2. Teraz spokojnie sprawdzamy zapis w Masterze
        resp = rtt_get_param(idx, 1.5)
        
        print("   [DEBUG-RTT] Surowa odpowiedz: {}".format(repr(resp)))
        
        clean_resp = resp.replace('get {}\n'.format(idx), '')
        digits = re.findall(r'\d+', clean_resp)
        
        if digits:
            read_val = int(digits[-1])
            if read_val == val:
                return True
            else:
                print("   [SYNC FAIL] Ustawiono {}, ale bramka zglasza {}. Ponawiam...".format(val, read_val))
        else:
            print("   [SYNC FAIL] Brak jasnej odpowiedzi. Ponawiam...")
            
        time.sleep(0.5)
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
        
        # 1. ZAPIS PARAMETRU W MASTERZE
        if not rtt_set_and_verify(28, tq):
            print("BLAD KRYTYCZNY: Nie udalo sie zapisac momentu w pamieci Mastera!")
            sys.exit(1)
            
        print("   [OK] Zapisano w Masterze. Wymuszam TWARDY RESET, aby zaktualizowac Slave'a...")
        
        # 2. TWARDY RESET W CELU SYNCHRONIZACJI SLAVE'A
        jlink.rtt_write(0, b'reset\n')
        time.sleep(3) # Czekamy az urzadzenie wstanie i wepchnie parametr do silnika
        try:
            jlink.rtt_stop()
            time.sleep(0.2)
            jlink.rtt_start()
        except:
            pass
            
        # 3. PO RESECIE MOZEMY BEZPIECZNIE TESTOWAC SILNIK
        mode_set("KONTROLA_LEWE_PRAWA")
        time.sleep(1)
        
        print("   Wymuszam probe otwarcia...")
        add_permission("L")
        
        rtt_buffer = ''
        start_t = time.time()
        result = "TIMEOUT"
        
        while time.time() - start_t < 4.0:
            char = jlink.rtt_read(0, 1)
            if len(char) == 1:
                rtt_buffer += chr(char[0])
                
                if LOG_MOTOR_ERROR in rtt_buffer:
                    result = "ERROR"
                    break
                elif LOG_GATE_OPENED in rtt_buffer:
                    result = "OPENED"
                    break
        
        if result == "ERROR" or result == "TIMEOUT":
            reason = "MOTOR ERROR" if result == "ERROR" else "TIMEOUT"
            print("   [X] Moment {} OBLAL TEST ({}).".format(tq, reason))
            # Nic nie musimy sprzatac, bo na poczatku nastepnej petli i tak bedzie nowy reset!
            
        elif result == "OPENED":
            print("   [V] Moment {} ZALICZYL TEST! Brama otwarta.".format(tq))
            successful_torques.append(tq)
            
            # Zamkniecie bramki po udanym otwarciu
            sensor_poke(LEFT_SENSOR)
            sensor_poke(LEFT_SECURITY_SENSOR)
            sensor_poke(CENTER_SECURITY_SENSOR)
            sensor_poke(RIGHT_SECURITY_SENSOR)
            sensor_poke(RIGHT_SENSOR)
            
            wait_for_logs(LOG_GATE_CLOSED, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
            time.sleep(1)

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
        
    # OSTATNI RESET NA ZAKONCZENIE PRE-CHECKA (zeby wejsc w testy ze stala wartoscia na silniku)
    jlink.rtt_write(0, b'reset\n')
    time.sleep(3)
    try:
        jlink.rtt_stop()
        time.sleep(0.2)
        jlink.rtt_start()
    except:
        pass
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
        jlink.rtt_write(0, 'sensor {} 1\n'.format(sensor).encode('utf-8'))
        time.sleep(POKE_DELAY_TIME)
        
        if interrupt_step and index == interrupt_step["after_index"]:
            print("[!] WYWOLANIE ALARMU: Naruszenie czujnika {} w trakcie ruchu!".format(interrupt_step['sensor']))
            jlink.rtt_write(0, 'sensor {} 1\n'.format(interrupt_step["sensor"]).encode('utf-8'))
            time.sleep(0.5)
            check_for_log_bool(LOG_ALARM_SAFETY, 2)
            jlink.rtt_write(0, 'sensor {} 0\n'.format(interrupt_step["sensor"]).encode('utf-8'))

        jlink.rtt_write(0, 'sensor {} 0\n'.format(sensor).encode('utf-8'))
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

# Twardy reset urzadzenia na wejsciu (dla pewnosci)
jlink.restart()
print("Czekam 3 sekundy na start procesora po pierwszym resecie...")
time.sleep(3)

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
