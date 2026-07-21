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
BOOT_WAIT_MASTER   = 3.0   
LOG_SYSTEM_READY   = "Permit manager"   
SYSTEM_READY_TIMEOUT = 12.0             

# Parametr ID odpowiedzialny za konfigurację / typ bramki (np. ID 32)
GATE_TYPE_PARAM_ID = 32

# Mapowanie oczekiwanych wartości dla poszczególnych typów bramek
# SG: 1, GT: 0, SK: 1, BR: 0 (zgodnie z logiką peryferiów)
EXPECTED_GATE_CONFIG = {
    "SG": 1,
    "GT": 0,
    "SK": 1,
    "BR": 0
}

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
        time.sleep(0.02)
    return rtt

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
        print("   [BOOT WARN] Nie przechwycono logu startowego.")

# =========================================================
# GŁÓWNY SKRYPT - TYLKO SPRAWDZENIE TYPU BRAMKI
# =========================================================
def main():
    print("\n=======================================================")
    print(" TYP BRAMKI WYBRANY W GUI: {}".format(GATE_TYPE))
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
        # Reset i oczekiwanie na gotowość systemu
        jlink.restart()
        time.sleep(BOOT_WAIT_MASTER)
        
        try:
            jlink.rtt_stop()
            time.sleep(0.2)
            jlink.rtt_start()
        except Exception:
            pass

        time.sleep(2.0)
        drain_rtt(jlink, 4096)

        # SPRAWDZENIE TYPU BRAMKI PRZEZ GET
        print("\n[CHECK] Odpytywanie urzadzenia o typ bramki (parametr ID {})...".format(GATE_TYPE_PARAM_ID))
        
        response = ""
        digits = []
        for attempt in range(5):
            response = rtt_get_param(jlink, GATE_TYPE_PARAM_ID, timeout_sec=2.0)
            digits = re.findall(r'\d+', response.replace('get {}'.format(GATE_TYPE_PARAM_ID), ''))
            if digits:
                break
            time.sleep(1.0)

        if not digits:
            print("[BLAD] Nie udalo sie odczytac parametru bramki z urzadzenia! Surowa odpowiedź: '{}'".format(response))
            play_beep(440, 500)
            sys.exit(1)

        device_val = int(digits[-1])
        expected_val = EXPECTED_GATE_CONFIG.get(GATE_TYPE, -1)

        print("   -> Odczytana wartosc z urzadzenia: {}".format(device_val))
        print("   -> Oczekiwana wartosc dla {}: {}".format(GATE_TYPE, expected_val))

        if GATE_TYPE in EXPECTED_GATE_CONFIG and device_val == expected_val:
            print("\n[SUKCES] Typ bramki z GUI zgadza sie z konfiguracja urzadzenia!")
        else:
            print("\n[BLAD] Niezgodnosc typu bramki! Urzadzenie zgłasza inną konfigurację niż wybrano w GUI.")
            play_beep(440, 500)
            sys.exit(1)

        print("\nTest weryfikacji typu bramki zakończony pomyślnie.")

    finally:
        try:
            jlink.close()
            print("[CLEANUP] J-Link connection closed.")
        except Exception as e:
            print("[CLEANUP] Warning: error while closing J-Link: {}".format(e))

if __name__ == "__main__":
    main()
