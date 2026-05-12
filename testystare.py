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
    NUMBER_OF_TESTS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    IS_INFINITE = (sys.argv[2] == "1") if len(sys.argv) > 2 else False
except:
    NUMBER_OF_TESTS = 200
    IS_INFINITE = False

# =========================================================
# ZMIENNE I STAŁE
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
CENTER_SECURITY_SENSOR = 5  # or 5

right_counter = 0
left_counter = 0
start_time = time.time()

# =========================================================
# FUNKCJE POMOCNICZE
# =========================================================
def play_beep(freq, duration):
    if platform.system() == "Windows":
        import winsound
        winsound.Beep(freq, duration)
    else:
        # Puste polecenie na Raspberry Pi - ignorujemy dźwięk
        pass

def wait_for_logs(log, timeout_sec):
    rtt = ''
    start_time_log = time.time()
    while time.time() - start_time_log < timeout_sec:
        char = jlink.rtt_read(0, 1)
        if len(char) == 1:
            rtt += chr(char[0])
        if rtt[-len(log):] == log:
            print("Found: ", log)
            return
    print("-----------============ LOGS ============-------------")
    print(rtt)
    print("-----------========== DIAGNOSE ============-------------")
    print(f"Timeout reached. Log:{log} not found. - TEST FAILED")
    play_beep(440, 500)  
    sys.exit(1) # ZMIANA: Zwraca błąd (1) dla GUI

def sensor_poke(num):
    jlink.rtt_write(0, f'sensor {num} 1\n'.encode('utf-8'))
    time.sleep(POKE_DELAY_TIME)
    jlink.rtt_write(0, f'sensor {num} 0\n'.encode('utf-8'))
    time.sleep(POKE_DELAY_EXIT_TIME)

def sensor_hold(num):
    jlink.rtt_write(0, f'sensor {num} 1\n'.encode('utf-8'))
    time.sleep(HOLD_DELAY_TIME)
    jlink.rtt_write(0, f'sensor {num} 0\n'.encode('utf-8'))
    time.sleep(HOLD_DELAY_TIME)

def reset():
    jlink.rtt_write(0, b'reset\n')
    time.sleep(0.2)

def mode_set(mode):
    strings_table = [
        "WOLNE_LEWE_PRAWA",
        "WOLNE_LEWE_KONTROLA_PRAWE",
        "WOLNE_PRAWE_KONTROLA_LEWE",
        "KONTROLA_LEWE_PRAWA",
        "BLOKADA_LEWE_PRAWA",
        "BEZ_BLOKADY_LEWE_PRAWA"
    ]
    if mode in strings_table:
        jlink.rtt_write(0, f'mode {strings_table.index(mode)}\n'.encode('utf-8'))
        time.sleep(0.5)
    else:
        print(f"Mode:{mode} not found. - TEST FAILED")
        play_beep(440, 500)
        sys.exit(1) # ZMIANA: Zwraca błąd (1) dla GUI

def check_counter(val_right, val_left):
    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.1)
    wait_for_logs(f'right counter:{val_right}', 0.5)
    wait_for_logs(f'left counter:{val_left}', 0.5)

def get_counters(timeout_sec):
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

        print(f"Counters - Right: {right_val}, Left: {left_val}")
        return right_val, left_val
    else:
        print(rtt)
        print(f"Timeout: Counters NOT found.")
        sys.exit(1) # ZMIANA: Zwraca błąd (1) dla GUI

def add_left_permission():
    jlink.rtt_write(0, b'add_l\n')
    time.sleep(0.1)

def add_right_permission():
    jlink.rtt_write(0, b'add_r\n')
    time.sleep(0.1)

def sim_passing_left_right():
    global left_counter
    sensor_poke(LEFT_SENSOR)  
    wait_for_logs("Permit manager: GATE OPENED", WAIT_TIME_FOR_GATE_ARM_MOVEMENT)  
    sensor_poke(LEFT_SECURITY_SENSOR)  
    sensor_poke(CENTER_SECURITY_SENSOR)
    sensor_poke(RIGHT_SECURITY_SENSOR)  
    sensor_poke(RIGHT_SENSOR)  
    wait_for_logs("Permit manager: GATE CLOSED", WAIT_TIME_FOR_GATE_ARM_MOVEMENT)  
    left_counter += 1  
    check_counter(right_counter, left_counter)  

def sim_passing_right_left():
    global right_counter
    sensor_poke(RIGHT_SENSOR)  
    wait_for_logs("Permit manager: GATE OPENED", WAIT_TIME_FOR_GATE_ARM_MOVEMENT)  
    sensor_poke(RIGHT_SECURITY_SENSOR)  
    sensor_poke(CENTER_SECURITY_SENSOR)
    sensor_poke(LEFT_SECURITY_SENSOR)  
    sensor_poke(LEFT_SENSOR)  
    wait_for_logs("Permit manager: GATE CLOSED", WAIT_TIME_FOR_GATE_ARM_MOVEMENT)  
    right_counter += 1  
    check_counter(right_counter, left_counter)  

# =========================================================
# GŁÓWNY SKRYPT
# =========================================================

jlink = pylink.JLink()

emulators = jlink.connected_emulators()

if not emulators:
    print("Nie znaleziono żadnych urządzeń J-Link.")
    sys.exit(1)

# Zautomatyzowany wybór urządzenia, żeby skrypt nie czekał na input w GUI
selected_sn = emulators[0].SerialNumber
jlink.open(serial_no=selected_sn)

jlink.connect("STM32F030RC", verbose=True)
jlink.rtt_start()
jlink.restart()
wait_for_logs("MODE:", 1)
time.sleep(2)

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> MODE SET >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
mode_set("WOLNE_LEWE_PRAWA")                                    # gate mode set - test FREE BOTH
right_counter, left_counter = get_counters(1)                 # proper read of current counters value

print(f"\n=======================================================")
print(f" Rozpoczynam testy. Nieskończoność: {IS_INFINITE}, Liczba: {NUMBER_OF_TESTS}")
print(f"=======================================================\n")

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> TEST 01 >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
count = 0
while True:
    count += 1
    time.sleep(1)
    print(f"\n>>> ITERACJA NR: {count}")
    
    print("FREE BOTH - ENTER LEFT -> EXIT RIGHT")
    sim_passing_left_right()
    time.sleep(1)
    
    print("FREE BOTH - ENTER RIGHT -> EXIT LEFT")
    sim_passing_right_left()

    # Przerwanie pętli, jeśli nie ma nieskończoności i osiągnięto limit
    if not IS_INFINITE and count >= NUMBER_OF_TESTS:
        break

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> TEST FINISHED <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
minutes, seconds = divmod(time.time()-start_time, 60)
print(f"\nTest finished successfully - time: {int(minutes)} minutes {seconds:.2f} seconds")

jlink.close()
sys.exit(0)  # Sukces, runner.py zobaczy PASS
