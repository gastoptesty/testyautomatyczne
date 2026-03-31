import time
import random
import sys

def run_hil_test():
    print(">>> INICJALIZACJA TESTU BRAMKI GASTOP <<<")
    time.sleep(1)
    
    # Symulacja kroków testowych
    checks = [
        "Sprawdzanie zasilania sterownika...",
        "Komunikacja z czytnikiem RFID...",
        "Test rygla elektromagnetycznego...",
        "Kalibracja czujników przejścia..."
    ]
    
    for check in checks:
        print(f"[LOG] {check}")
        time.sleep(0.8) # Symulacja czasu trwania testu
        
    # Losowanie wyniku (90% szans na sukces)
    if random.random() > 0.1:
        print("WYNIK: TEST ZAKOŃCZONY POMYŚLNIE (OK)")
        sys.exit(0) # Sukces
    else:
        # Przykładowe błędy
        errors = ["BŁĄD: Przekroczono czas odpowiedzi rygla", "BŁĄD: Zwarcie na czujniku wejścia"]
        print(f"WYNIK: {random.choice(errors)}")
        sys.exit(1) # Błąd

if __name__ == "__main__":
    run_hil_test()
