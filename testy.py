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
# ZMIENNE I STALE SYSTEMOWE (ZWERYFIKOWANE INDEKSY Z TABELI)
# =========================================================
BOOT_WAIT_MASTER   = 3.0   
LOG_SYSTEM_READY   = "Permit manager"   
SYSTEM_READY_TIMEOUT = 12.0             

# Zgodnie z tabelą getów:
GATE_TYPE_PARAM_ID = 13      # get 13: gate type
MAX_TORQUE_PARAM_ID = 40     # get 40: max torque

# Mapowanie oczekiwanych wartości typu bramki
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

    jlink.rtt_write(0, 'get {}\r\n'.format(idx).encode('utf-8'))
    start_t = time.time()
    rtt = ''
    while time.time() - start_t < timeout_sec:
        chunk = jlink.rtt_read(0, 1024)
        if chunk:
            rtt += "".join([chr(c) for c in chunk])
        time.sleep(0.02)
    return rtt

def rtt_set_and_verify(jlink, idx, val, timeout_sec=2.0):
    for attempt in range(4):
        print("\n--- [ZAPIS] Ustawianie parametru ID {} = {} (próba {}) ---".format(idx, val, attempt + 1))
        
        try:
            jlink.rtt_read(0, 4096)
        except Exception:
            pass

        # Wysłanie komendy set z powrotem karetki
        jlink.rtt_write(0, 'set {} {}\r\n'.format(idx, val).encode('utf-8'))
        time.sleep(0.3)

        # Opcjonalny zapis do pamięci trwałej, jeśli mikrokontroler tego wymaga
        jlink.rtt_write(0, 'save\r\n')
        time.sleep(0.2)

        # Odczyt i weryfikacja
        resp = rtt_get_param(jlink, idx, timeout_sec)
        
        # Czyszczenie odpowiedzi z ANSI i nazwy komendy
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_resp = ansi_escape.sub('', resp)
        clean_resp = clean_resp.replace('get {}\r\n'.format(idx), '').replace('get {}\n'.format(idx), '')
        
        digits = re.findall(r'\d+', clean_resp)
        if digits:
            # Szukamy dokładnej wartości lub bierzemy ostatnią liczbę
            if str(val) in digits or int(digits[-1]) == val:
                print("   [SUKCES] Parametr ID {} zweryfikowany pomyślnie (wartość: {}).".format(idx, val))
                return True

        print("   [SYNC FAIL] Odczytano niepoprawną wartość. Ponawiam...")
    
    return False

def safe_rtt_restart(jlink, delay=None, wait_for_link=True):
    if delay is None:
        delay = BOOT_WAIT_MASTER

    print("   [RESET] Wymuszono reset sprzętowy przez SWD. Czekam na boot MCU...")
    try:
        jlink.restart()
    except Exception as e:
        print("   [WARN] Błąd jlink.restart(): {}. Używam komendy konsolowej...".format(e))
        jlink.rtt_write(0, b'reset\r\n')

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
        print("[WARN] Nie udało się wznowić RTT automatycznie.")

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
# GŁÓWNY SKRYPT
# =========================================================
def main():
    print("\n=======================================================")
    print(" TYP BRAMKI WYBRANY W GUI: {}".format(GATE_TYPE))
    print("=======================================================\n")

    jlink = pylink.JLink()
    emulators = jlink.connected_emulators()

    if not emulators:
        print("Nie znaleziono żadnych urządzeń J-Link.")
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

        # 1. SPRAWDZENIE TYPU BRAMKI (ID 13)
        print("\n[CHECK] Odpytywanie urządzenia o typ bramki (parametr ID {})...".format(GATE_TYPE_PARAM_ID))
        
        response = ""
        digits = []
        for attempt in range(5):
            response = rtt_get_param(jlink, GATE_TYPE_PARAM_ID, timeout_sec=2.0)
            digits = re.findall(r'\d+', response.replace('get {}'.format(GATE_TYPE_PARAM_ID), ''))
            if digits:
                break
            time.sleep(1.0)

        if not digits:
            print("[BŁĄD] Nie udało się odczytać parametru bramki z urządzenia! Surowa odpowiedź: '{}'".format(response))
            play_beep(440, 500)
            sys.exit(1)

        device_val = int(digits[-1])
        expected_val = EXPECTED_GATE_CONFIG.get(GATE_TYPE, -1)

        print("   -> Odczytana wartość z urządzenia: {}".format(device_val))
        print("   -> Oczekiwana wartość dla {}: {}".format(GATE_TYPE, expected_val))

        if GATE_TYPE in EXPECTED_GATE_CONFIG and device_val == expected_val:
            print("\n[SUKCES] Typ bramki z GUI zgadza się z konfiguracją urządzenia!")
        else:
            print("\n[BŁĄD] Niezgodność typu bramki! Urządzenie zgłasza inną konfigurację niż wybrano w GUI.")
            play_beep(440, 500)
            sys.exit(1)

        # 2. PRZYKŁAD POPRAWNEGO UŻYCIA ZAPISU (np. test max torque na ID 40)
        print("\n[CONFIG] Test ustawienia parametru Max Torque (ID {}) na wartość domyślną...".format(MAX_TORQUE_PARAM_ID))
        if rtt_set_and_verify(jlink, MAX_TORQUE_PARAM_ID, 10):
            print("   -> Zapis Max Torque zakończony powodzeniem.")
        else:
            print("   -> [OSTRZEZENIE] Nie udało się zapisać Max Torque, kontynuuję...")

        print("\nInicjalizacja i weryfikacja parametrów zakończona pomyślnie.")

    finally:
        try:
            jlink.close()
            print("[CLEANUP] Połączenie J-Link zamknięte.")
        except Exception as e:
            print("[CLEANUP] Warning: błąd podczas zamykania J-Link: {}".format(e))

if __name__ == "__main__":
    main()
