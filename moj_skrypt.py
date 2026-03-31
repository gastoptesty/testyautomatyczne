import time
import sys
from pylink import JLink

# --- KONFIGURACJA J-LINK ---
JLINK_SERIAL_NUMBER = 770248782
CHIP_NAME = "STM32F030RC"

# Definicje sensorów z Twojego starego kodu
LEFT_SENSOR = 0
LEFT_SECURITY_SENSOR = 3
RIGHT_SECURITY_SENSOR = 8
RIGHT_SENSOR = 11

def wait_for_logs(jlink, target_log, timeout=5):
    start = time.time()
    rtt_data = ""
    while time.time() - start < timeout:
        terminal_out = jlink.rtt_read(0, 1024)
        if terminal_out:
            rtt_data += "".join(map(chr, terminal_out))
            if target_log in rtt_data:
                print(f"Znaleziono log: {target_log}")
                return True
    print(f"TIMEOUT: Nie znaleziono logu: {target_log}")
    return False

def run_test():
    jlink = JLink()
    try:
        print(f"Łączenie z J-Link (SN: {JLINK_SERIAL_NUMBER})...")
        jlink.open(serial_no=JLINK_SERIAL_NUMBER)
        jlink.connect(CHIP_NAME, verbose=False)
        jlink.rtt_start()
        
        print("Ustawianie trybu: WOLNE_LEWE_PRAWA")
        jlink.rtt_write(0, b'mode 0\n') # Zakładam index 0 z Twojej tabeli
        time.sleep(0.5)

        # SYMULACJA PRZEJŚCIA (ENTER LEFT -> EXIT RIGHT)
        print("Symulacja przejścia: Lewa -> Prawa")
        
        # Wejście w sensor lewy
        jlink.rtt_write(0, f'sensor {LEFT_SENSOR} 1\n'.encode())
        time.sleep(0.2)
        jlink.rtt_write(0, f'sensor {LEFT_SENSOR} 0\n'.encode())
        
        if not wait_for_logs(jlink, "Permit manager: GATE OPENED"):
            print("WYNIK: BŁĄD - Bramka się nie otworzyła")
            sys.exit(1)

        # Sensory bezpieczeństwa
        jlink.rtt_write(0, f'sensor {LEFT_SECURITY_SENSOR} 1\n'.encode())
        time.sleep(0.2)
        jlink.rtt_write(0, f'sensor {RIGHT_SECURITY_SENSOR} 1\n'.encode())
        time.sleep(0.2)
        
        # Wyjście sensorem prawym
        jlink.rtt_write(0, f'sensor {RIGHT_SENSOR} 1\n'.encode())
        time.sleep(0.2)
        jlink.rtt_write(0, f'sensor {RIGHT_SENSOR} 0\n'.encode())

        if not wait_for_logs(jlink, "Permit manager: GATE CLOSED"):
            print("WYNIK: BŁĄD - Bramka się nie zamknęła")
            sys.exit(1)

        print("WYNIK: TEST ZAKOŃCZONY POMYŚLNIE")
        sys.exit(0)

    except Exception as e:
        print(f"WYNIK: BŁĄD KRYTYCZNY J-LINK: {e}")
        sys.exit(1)
    finally:
        jlink.close()

if __name__ == "__main__":
    run_test()
