import pylink      # pip install pylink-square
import re
import time
import sys
import random
import platform    # DODANO: do wykrywania systemu operacyjnego
import os          # DODANO: do wywoływania komend w Linuksie

SIZE_TEST_VECTOR = 4
NUMBER_OF_TESTS = 200
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
# DODANO: Wieloplatformowa funkcja dźwiękowa
# =========================================================
def play_beep(freq, duration):
    if platform.system() == "Windows":
        import winsound
        winsound.Beep(freq, duration)
    else:
        # 2>/dev/null ukrywa błędy braku uprawnień/urządzenia
        os.system(f"beep -f {freq} -l {duration} 2>/dev/null")
# =========================================================


def wait_for_logs(log, timeout_sec):
    rtt = ''
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
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
    play_beep(440, 500)  # ZMIENIONO: Wieloplatformowy beep
    sys.exit()


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
        play_beep(440, 500)  # ZMIENIONO: Wieloplatformowy beep
        sys.exit()


def check_counter(val_right, val_left):
    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.1)
    wait_for_logs(f'right counter:{val_right}', 0.5)
    wait_for_logs(f'left counter:{val_left}', 0.5)


def get_counters(timeout_sec):
    jlink.rtt_write(0, b'counter\n')
    time.sleep(0.1)

    rtt = ''
    start_time = time.time()

    pattern_right = r"right counter:(\d+)"
    pattern_left = r"left counter:(\d+)"

    while time.time() - start_time < timeout_sec:
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
        sys.exit()


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



jlink = pylink.JLink()

emulators = jlink.connected_emulators()

if not emulators:
    print("Nie znaleziono żadnych urządzeń J-Link.")
    exit()

print("Dostępne urządzenia J-Link:")
print(f"{'Nr':<4} {'Nazwa (Nickname)':<20} {'Model':<15} {'SN':<12}")
print("-" * 55)

for i, emu in enumerate(emulators):
    nickname = emu.acNickname.decode('utf-8').strip('\x00')
    display_name = nickname if nickname else "--- brak nazwy ---"
    product = emu.acProduct.decode('utf-8').strip('\x00')
    serial = emu.SerialNumber
    print(f"[{i}] {display_name:<20} {product:<15} {serial:<12}")


# 2. Wybór urządzenia (ZAUTOMATYZOWANY)
if len(emulators) > 0:
    # Wybiera zawsze pierwszy z brzegu podłączony J-Link
    selected_sn = emulators[0].SerialNumber
    print(f"Automatycznie wybrano urządzenie 0 (SN: {selected_sn})")
else:
    print("Błąd: Brak dostępnych urządzeń do automatycznego wyboru.")
    sys.exit()


jlink.open(serial_no=selected_sn)
print(f"\nWybrano: {jlink.product_name} o nazwie '{nickname}' (SN: {jlink.serial_number})")
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
jlink.connect("STM32F030RC", verbose=True)
jlink.rtt_start()
jlink.restart()
wait_for_logs("MODE:", 1)
time.sleep(2)
#>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> MODE SET >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
mode_set("WOLNE_LEWE_PRAWA")                                    # gate mode set - test FREE BOTH
right_counter, left_counter = get_counters(1)                 # proper read of current counters value
#>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> TEST 01 >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
for i in range(NUMBER_OF_TESTS):
    time.sleep(1)
    print("FREE BOTH - ENTER LEFT -> EXIT RIGHT")
    sim_passing_left_right()
    time.sleep(1)
    print("FREE BOTH - ENTER RIGHT -> EXIT LEFT")
    sim_passing_right_left()

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> TEST FINISHED <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
minutes, seconds = divmod(time.time()-start_time, 60)
print(f"Test finished successfully - time: {int(minutes)} minutes {seconds:.2f} seconds")

jlink.close()
play_beep(1400, 100) # ZMIENIONO: Wieloplatformowy beep
play_beep(3400, 200) # ZMIENIONO: Wieloplatformowy beep
play_beep(2400, 100) # ZMIENIONO: Wieloplatformowy beep
