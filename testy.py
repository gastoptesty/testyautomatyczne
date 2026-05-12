import pylink      # pip install pylink-square
import re
import time
import sys
import platform
import os

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

# --- OCZEKIWANE LOGI Z SYSTEMU (DO MODYFIKACJI POD TWOJE RTT) ---
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
    print(f"Timeout reached. Log:'{log}' not found. - TEST FAILED")
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
    jlink.rtt_write(0, f'sensor {num} 1\n'.encode('utf-8'))
    time.sleep(POKE_DELAY_TIME)
    jlink.rtt_write(0, f'sensor {num} 0\n'.encode('utf-8'))
    time.sleep(POKE_DELAY_EXIT_TIME)

def reset():
    jlink.rtt_write(0, b'reset\n')
    time.sleep(0.5)

def mode_set(mode):
    global current_mode
    strings_table = [
        "WOLNE_LEWE_PRAWA", "WOLNE_LEWE_KONTROLA_PRAWE", "WOLNE_PRAWE_KONTROLA_LEWE",
        "KONTROLA_LEWE_PRAWA", "BLOKADA_LEWE_PRAWA", "BEZ_BLOKADY_LEWE_PRAWA"
    ]
    if mode in strings_table:
        jlink.rtt_write(0, f'mode {strings_table.index(mode)}\n'.encode('utf-8'))
        time.sleep(0.5)
        current_mode = mode
    else:
        print(f"Mode:{mode} not found. - TEST FAILED")
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
# FUNKCJE RTT (GET / SET)
# =========================================================
def rtt_set_param(idx, val):
    jlink.rtt_write(0, f'set {idx} {val}\n'.encode('utf-8'))
    time.sleep(0.3)

def rtt_get_param(idx, timeout_sec=1.0):
    jlink.rtt_write(0, f'get {idx}\n'.encode('utf-8'))
    start_t = time.time()
    rtt = ''
    while time.time() - start_t < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])
    return rtt

# =========================================================
# PRE-FLIGHT CHECKS (Testy i kalibracje)
# =========================================================
def test_calibration_read_only():
    print("\n[PRE-CHECK] Sprawdzanie bezpieczeństwa kalibracji...")
    response = rtt_get_param(7)
    digits = re.findall(r'\d+', response.replace('get 7', '')) 
    if not digits:
        print("Nie udało się odczytać kalibracji! Zatrzymuję test ze względów bezpieczeństwa.")
        sys.exit(1)
        
    calib_val = int(digits[-1])
    
    # POPRAWKA: Akceptujemy od 0 do 4
    if calib_val < 0 or calib_val > 4:
        print(f"BŁĄD: Kalibracja poza bezpiecznym zakresem: {calib_val}. Zatrzymuję test!")
        sys.exit(1)
    print(f"Kalibracja w normie. Odczytana wartość zerowa: {calib_val}")

def test_find_optimal_torque():
    print("\n[PRE-CHECK] Pełne skanowanie parametrów momentu obrotowego (Max Torque 1-20)...")
    
    # Tryb KONTROLA przed rozpoczęciem skanowania
    mode_set("KONTROLA_LEWE_PRAWA")
    time.sleep(1)
    
    successful_torques = []
    
    for tq in range(1, 21):
        print(f"\n--- Skanowanie wartości Max Torque: {tq} ---")
        
        # 1. Ustawienie sprawdzanego momentu obrotowego
        rtt_set_param(28, tq)
        time.sleep(0.5) 
        
        # 2. Sygnał otwarcia
        print(f"   Wymuszam otwarcie bramki w lewo (add_l) dla momentu {tq}...")
        add_permission("L")
        
        rtt_buffer = ''
        start_t = time.time()
        result = "TIMEOUT"
        
        # 3. Nasłuch reakcji bramki
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
        
        # 4. Obsługa błędu lub braku siły
        if result == "ERROR" or result == "TIMEOUT":
            reason = "MOTOR ERROR" if result == "ERROR" else "TIMEOUT"
            print(f"   [X] Moment {tq} OBLAŁ TEST ({reason}). Robię bezpieczny reset...")
            
            # Reset sprzętowy bramki
            jlink.rtt_write(0, b'reset\n')
            time.sleep(3) 
            
            # Restart kanału RTT
            try:
                jlink.rtt_stop()
                time.sleep(0.2)
                jlink.rtt_start()
            except:
                pass
                
            # Wymuszenie trybu KONTROLA w ciemno po resecie
            jlink.rtt_write(0, b'mode 3\n')
            time.sleep(1) 
            
        # 5. Obsługa sukcesu
        elif result == "OPENED":
            print(f"   [V] Moment {tq} ZALICZYŁ TEST! Brama w pełni otwarta.")
            successful_torques.append(tq)
            
            # Przeprowadzamy wirtualnego pieszego, żeby fizycznie zamknąć skrzydła
            sensor_poke(LEFT_SENSOR)
            sensor_poke(LEFT_SECURITY_SENSOR)
            sensor_poke(CENTER_SECURITY_SENSOR)
            sensor_poke(RIGHT_SECURITY_SENSOR)
            sensor_poke(RIGHT_SENSOR)
            
            wait_for_logs(LOG_GATE_CLOSED, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
            time.sleep(1) # Chwila oddechu dla mechaniki przed testem kolejnego progu

    # ===============================================
    # PODSUMOWANIE I WYBÓR OPTYMALNEGO PARAMETRU
    # ===============================================
    if not successful_torques:
        print("\nBŁĄD KRYTYCZNY: Na żadnym momencie obrotowym (1-20) brama nie ruszyła poprawnie!")
        sys.exit(1)
        
    optimal_torque = min(successful_torques)
    
    print(f"\n=======================================================")
    print(f" RAPORT SKANOWANIA MOMENTU OBROTOWEGO:")
    print(f" Działające wartości (bez błędu silnika): {successful_torques}")
    print(f" Najmniejszy działający próg: {optimal_torque}")
    print(f"=======================================================\n")
    
    # 6. Ostateczne utrwalenie optymalnej wartości
    print(f"-> Aplikowanie optymalnego momentu ({optimal_torque}) na resztę testów...")
    rtt_set_param(28, optimal_torque)
    time.sleep(1)
            
        elif result == "OPENED":
            print(f"   [OK] Znaleziono optymalny, bezpieczny moment roboczy: {tq}")
            optimal_torque = tq
            
            # Skoro bramka otworzyła się po sygnale, symulujemy wejście pieszego, żeby ją poprawnie zamknąć
            sensor_poke(LEFT_SENSOR)
            sensor_poke(LEFT_SECURITY_SENSOR)
            sensor_poke(CENTER_SECURITY_SENSOR)
            sensor_poke(RIGHT_SECURITY_SENSOR)
            sensor_poke(RIGHT_SENSOR)
            
            wait_for_logs(LOG_GATE_CLOSED, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
            break

    if optimal_torque == -1:
        print("BŁĄD KRYTYCZNY: Nawet na maksymalnym momencie obrotowym brama nie może poprawnie ruszyć!")
        sys.exit(1)
def test_diagnostics_counters():
    print("\n[TŁO] Sprawdzanie liczników diagnostycznych w tle...")
    response = rtt_get_param(60) 
    digits = re.findall(r'\d+', response.replace('get 60', ''))
    if digits:
        err_count = int(digits[-1])
        if err_count > 0:
            print(f"OSTRZEŻENIE: Wykryto {err_count} błędów komunikacji Master-Slave!")

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

    print(f"\n=======================================================")
    print(f">>> TEST NR: {iter_num} | {name}")
    
    if current_mode != req_mode:
        print(f"Ustawianie trybu: {req_mode}")
        mode_set(req_mode)

    global right_counter, left_counter
    start_r, start_l = get_counters(1)

    if permit:
        print(f"Nadawanie uprawnienia dla: {permit}")
        add_permission(permit)

    for index, sensor in enumerate(seq):
        jlink.rtt_write(0, f'sensor {sensor} 1\n'.encode('utf-8'))
        time.sleep(POKE_DELAY_TIME)
        
        # Test bezpieczeństwa (np. antyzgnieceniowy podczas ruchu)
        if interrupt_step and index == interrupt_step["after_index"]:
            print(f"[!] WYWOŁANIE ALARMU: Naruszenie czujnika {interrupt_step['sensor']} w trakcie ruchu!")
            jlink.rtt_write(0, f'sensor {interrupt_step["sensor"]} 1\n'.encode('utf-8'))
            time.sleep(0.5)
            check_for_log_bool(LOG_ALARM_SAFETY, 2)
            jlink.rtt_write(0, f'sensor {interrupt_step["sensor"]} 0\n'.encode('utf-8'))

        jlink.rtt_write(0, f'sensor {sensor} 0\n'.encode('utf-8'))
        time.sleep(POKE_DELAY_EXIT_TIME)

    if expected_log:
        found = check_for_log_bool(expected_log, WAIT_TIME_FOR_GATE_ARM_MOVEMENT)
        if not found:
            print(f"BŁĄD: Oczekiwano logu '{expected_log}', ale go zabrakło! - TEST FAILED")
            play_beep(440, 500)
            sys.exit(1)
        print(f"SUKCES: Zweryfikowano zachowanie '{expected_log}'.")
    
    time.sleep(1) 
    
    end_r, end_l = get_counters(1)
    total_start = start_r + start_l
    total_end = end_r + end_l

    if expect_count:
        if total_end <= total_start:
            print("BŁĄD: Zliczanie przejścia NIE powiodło się, a powinno! - TEST FAILED")
            sys.exit(1)
        else:
            right_counter, left_counter = end_r, end_l
            print(f"SUKCES: Licznik poprawnie wzrósł (Obecnie: L:{left_counter}, R:{right_counter})")
    else:
        if total_end > total_start:
            print("BŁĄD: System niesłusznie zliczył przejście (np. podczas alarmu)! - TEST FAILED")
            sys.exit(1)
        else:
            print("SUKCES: System poprawnie zignorował nieudane przejście.")

# =========================================================
# GENERATOR BAZY TESTÓW BEHAWIORALNYCH
# =========================================================
def generate_100_scenarios():
    scenarios = []

    # [1-20] WOLNE LEWE PRAWA
    for i in range(10):
        seq_lp = [LEFT_SENSOR] * ((i % 2) + 1) + [LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
        scenarios.append({"name": f"WOLNE L->P (wahanie {i%2 + 1}x)", "mode": "WOLNE_LEWE_PRAWA", "seq": seq_lp, "log": LOG_GATE_CLOSED, "count": True})
        seq_pl = [RIGHT_SENSOR] * ((i % 2) + 1) + [RIGHT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR]
        scenarios.append({"name": f"WOLNE P->L (wahanie {i%2 + 1}x)", "mode": "WOLNE_LEWE_PRAWA", "seq": seq_pl, "log": LOG_GATE_CLOSED, "count": True})

    # [21-40] KONTROLA LEWE PRAWA
    for i in range(10):
        seq_lp = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
        scenarios.append({"name": "KONTROLA L->P (Z uprawnieniem)", "mode": "KONTROLA_LEWE_PRAWA", "permit": "L", "seq": seq_lp, "log": LOG_GATE_CLOSED, "count": True})
        seq_reject = [LEFT_SENSOR]
        scenarios.append({"name": "KONTROLA L->P (Odbicie, brak upr)", "mode": "KONTROLA_LEWE_PRAWA", "permit": None, "seq": seq_reject, "log": LOG_ALARM_NO_PERMIT, "count": False})

    # [41-55] WOLNE LEWE / KONTROLA PRAWE (Asymetria)
    for i in range(15):
        if i % 2 == 0:
            seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
            scenarios.append({"name": "ASYMETRIA: Wolne przejście L->P", "mode": "WOLNE_LEWE_KONTROLA_PRAWE", "seq": seq, "log": LOG_GATE_CLOSED, "count": True})
        else:
            seq = [RIGHT_SENSOR]
            scenarios.append({"name": "ASYMETRIA: Brak uprawnień P->L", "mode": "WOLNE_LEWE_KONTROLA_PRAWE", "seq": seq, "log": LOG_ALARM_NO_PERMIT, "count": False})

    # [56-70] ANOMALIE: Wycofania
    for i in range(15):
        seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR]
        scenarios.append({"name": "Wycofanie po wejściu", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "log": LOG_GATE_CLOSED, "count": False})

    # [71-85] ANOMALIE: Intruz, Tailgating, Czołganie
    for i in range(15):
        if i % 3 == 0:
            seq = [CENTER_SECURITY_SENSOR]
            scenarios.append({"name": "Wtargnięcie w światło bramki", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "log": LOG_ALARM_INTRUSION, "count": False})
        elif i % 3 == 1:
            seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR, LEFT_SENSOR, CENTER_SECURITY_SENSOR, RIGHT_SECURITY_SENSOR, RIGHT_SENSOR]
            scenarios.append({"name": "Próba jazdy na ogonie", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "log": LOG_ALARM_TAILGATING, "count": True})
        else:
            seq = [LEFT_DOWN_SENSOR, RIGHT_DOWN_SENSOR]
            scenarios.append({"name": "Czołganie pod szybami", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "log": "", "count": False})

    # [86-100] TESTY BEZPIECZEŃSTWA: Naruszenie w trakcie ruchu (Anti-crush)
    for i in range(15):
        seq = [LEFT_SENSOR, LEFT_SECURITY_SENSOR]
        interrupt = {"after_index": 0, "sensor": CENTER_SECURITY_SENSOR}
        scenarios.append({"name": "ANTI-CRUSH: Naruszenie w trakcie ruchu", "mode": "WOLNE_LEWE_PRAWA", "seq": seq, "interrupt": interrupt, "log": LOG_ALARM_SAFETY, "count": False})

    return scenarios

# =========================================================
# GŁÓWNY SKRYPT
# =========================================================

jlink = pylink.JLink()
emulators = jlink.connected_emulators()

if not emulators:
    print("Nie znaleziono żadnych urządzeń J-Link.")
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

# >>>>>>>>>>>>> SETUP PRZED GŁÓWNĄ PĘTLĄ >>>>>>>>>>>>>
mode_set("WOLNE_LEWE_PRAWA")
right_counter, left_counter = get_counters(1)

scenarios_pool = generate_100_scenarios()

print(f"\n=======================================================")
print(f" BAZA TESTOWA ZAŁADOWANA. Wariantów: {len(scenarios_pool)}. Nieskończoność: {IS_INFINITE}")
print(f"=======================================================\n")

# >>>>>>>>>>>>> GŁÓWNA PĘTLA WYKONAWCZA >>>>>>>>>>>>>
count = 0
while True:
    current_scenario = scenarios_pool[count % len(scenarios_pool)]
    
    execute_custom_sequence(count + 1, current_scenario)
    
    count += 1
    
    if count % 15 == 0:
        test_diagnostics_counters()

    if not IS_INFINITE and count >= NUMBER_OF_TESTS:
        break

# >>>>>>>>>>>>> ZAKOŃCZENIE >>>>>>>>>>>>>
minutes, seconds = divmod(time.time() - start_time, 60)
print(f"\nTest finished successfully - time: {int(minutes)} minutes {seconds:.2f} seconds")

jlink.close()
sys.exit(0)
