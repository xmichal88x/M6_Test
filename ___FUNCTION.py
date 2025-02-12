#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# FUNCTION to throw message in py status line and optionally end program 
# Args: message(string), action(boolean)
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def throwMessage(message, action):

    ttime = time.strftime("%H:%M:%S", timezone)
    print("\n"  + ttime + " - " + message)

    if message == True: 
        
        msg.info("\n"  + ttime + " - " + message)

    if action == "exit":
        sys.exit(0)

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# FUNCTION to GET status of IO pin
# Args: pin_in(int)
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def get_digital_input(pin_tuple):
    """Odczytuje stan wejścia cyfrowego z odpowiedniego modułu."""
    module_id, pin, module_type = pin_tuple

    # Wybór odpowiedniego modułu
    if module_type == "IP":
        csmio = d.getModule(ModuleType.IP, module_id)
    elif module_type == "IO":
        csmio = d.getModule(ModuleType.IO, module_id)
    else:
        print(f"Błąd: Nieznany typ modułu {module_type}")
        return None

    if pin is None:
        print("Błąd: Pin nie został podany.")
        return None

    value = csmio.getDigitalIO(IOPortDir.InputPort, pin) == DIOPinVal.PinSet
    # print(f"Odczytano wejście: module_id={module_id}, pin={pin}, wartość={value}")
    return value

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# FUNCTION to SET status of IO pin
# Args: pin_out(int), state(boolean)
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def set_digital_output(pin_tuple, state):
    """Ustawia stan wyjścia cyfrowego w odpowiednim module."""
    module_id, pin, module_type = pin_tuple  # Rozpakowanie wartości
    state2 = DIOPinVal.PinSet if state else DIOPinVal.PinReset

    # Wybór odpowiedniego modułu
    if module_type == "IP":
        csmio = d.getModule(ModuleType.IP, module_id)
    elif module_type == "IO":
        csmio = d.getModule(ModuleType.IO, module_id)
    else:
        print(f"Błąd: Nieznany typ modułu {module_type}")
        return None

    if pin is None:
        print("Błąd: Pin nie został podany.")
        return None
    
    try:
        csmio.setDigitalIO(pin, state2)
    except NameError as e:
        print(f"Błąd: Digital Output został błędnie zdefiniowany. Szczegóły: {e}")

#-----------------------------------------------------------
# Operacje na json
#-----------------------------------------------------------

import json

JSON_FILE = "narzedzia.json"

# Mapowanie wartości liczbowych na nazwy trybu pracy
TRYB_PRACY_MAP = {0: "Dół", 1: "Góra"}
TRYB_PRACY_REVERSE = {"Dół": 0, "Góra": 1}

def wczytaj_ustawienia():
    """Wczytuje ustawienia z JSON i konwertuje wartości na nazwy."""
    try:
        with open(JSON_FILE, "r") as f:
            data = json.load(f)
        # Zamiana wartości 0/1 na nazwy trybu pracy
        for tool, params in data.items():
            params["tryb_pracy"] = TRYB_PRACY_MAP.get(params["tryb_pracy"], "Nieznany")
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def odczytaj_kieszen(narzedzie):
    """Odczytuje numer kieszeni dla podanego narzędzia z pliku JSON."""
    data = wczytaj_ustawienia()  # Wczytuje dane z pliku JSON

    # Sprawdza, czy narzędzie istnieje w danych
    if str(narzedzie) in data:
        kieszen = data[str(narzedzie)]["kieszen"]  # Pobiera numer kieszeni
        return kieszen
    else:
        messagebox.showerror("Błąd", f"Narzędzie {narzedzie} nie znaleziono w pliku JSON.")
        return None

def odczytaj_tryb_pracy(narzedzie):
    """Odczytuje tryb pracy dla podanego narzędzia z pliku JSON."""
    data = wczytaj_ustawienia()  # Wczytuje dane z pliku JSON

    # Sprawdza, czy narzędzie istnieje w danych
    if str(narzedzie) in data:
        tryb_pracy = data[str(narzedzie)]["tryb_pracy"]  # Pobiera tryb pracy
        return tryb_pracy
    else:
        messagebox.showerror("Błąd", f"Narzędzie {narzedzie} nie znaleziono w pliku JSON.")
        return None
#-----------------------------------------------------------
# Lista programów
#-----------------------------------------------------------

def check_axes_referenced():
    axis_to_check = [Axis.X, Axis.Y, Axis.Z]
    not_referenced_axes = []  # Lista na niezreferowane osie

    for axis in axis_to_check:
        if not d.isAxisReferenced(axis):
            not_referenced_axes.append(axis)  # Dodajemy niezreferowaną oś

    # Jeśli są niezreferowane osie, zgłoś błąd
    if not_referenced_axes:
        msg_axes_referenced = f"🔴 Osi(e) {', '.join([str(axis) for axis in not_referenced_axes])} nie są zbazowane! Uruchom proces bazowania."
        throwMessage(msg_axes_referenced, "exit")

def curtain_up():
    """
    Podnosi szczotkę.
    - Sprawdza czujnik pozycji górnej szczotki.
    """
    print("Rozpoczynam podnoszenie szczotki...")
    set_digital_output(OUT_CURTAIN_UP, True)
    time.sleep(0.25)
    set_digital_output(OUT_CURTAIN_UP, False)

    start_time = time.time()
    while not get_digital_input(IN_CURTAIN_UP):
        if time.time() - start_time > 5:
            print("Błąd: Szczotka nie osiągnęła pozycji górnej.")
            return False
        time.sleep(0.1)
    print("Szczotka podniesiona.")
    return True

def curtain_down():
    """
    Opuszcza szczotkę.
    - Sprawdza czujnik pozycji dolnej szczotki.
    """
    print("Rozpoczynam opuszczanie szczotki...")
    set_digital_output(OUT_CURTAIN_DOWN, True)
    time.sleep(0.25)
    set_digital_output(OUT_CURTAIN_DOWN, False)

    start_time = time.time()
    while not get_digital_input(IN_CURTAIN_DOWN):
        if time.time() - start_time > 5:
            print("Błąd: Szczotka nie osiągnęła pozycji dolnej.")
            return False
        time.sleep(0.1)
    print("Szczotka opuszczona.")
    return True

def aggregate_up():
    """
    Podnosi agregat.
    - Sprawdza czujnik pozycji górnej agregatu.
    """
    print("Rozpoczynam podnoszenie agregatu...")
    set_digital_output(OUT_AGGREGATE_UP, True)
    time.sleep(0.25)
    set_digital_output(OUT_AGGREGATE_UP, False)

    start_time = time.time()
    while not get_digital_input(IN_AGGREGATE_UP):
        if time.time() - start_time > 5:
            print("Błąd: Agregat nie osiągnął pozycji górnej.")
            return False
        time.sleep(0.1)
    print("Agregat podniesiony.")
    return True


def aggregate_down():
    """
    Opuszcza agregat.
    - Sprawdza czujnik pozycji dolnej agregatu.
    """
    print("Rozpoczynam opuszczanie agregatu...")
    set_digital_output(OUT_AGGREGATE_DOWN, True)
    time.sleep(0.25)
    set_digital_output(OUT_AGGREGATE_DOWN, False)

    start_time = time.time()
    while not get_digital_input(IN_AGGREGATE_DOWN):
        if time.time() - start_time > 5:
            print("Błąd: Agregat nie osiągnął pozycji dolnej.")
            return False
        time.sleep(0.1)
    print("Agregat opuszczony.")
    return True

def activate_tool_change_position():
    """
    Aktywuje pozycję wymiany narzędzia.
    """
    print("Aktywuję pozycję wymiany narzędzia...")
    set_digital_output(OUT_TOOL_CHANGE_POS, True)
    time.sleep(0.25)
    print("Pozycja wymiany aktywowana.")

def deactivate_tool_change_position():
    """
    Dezaktywuje pozycję wymiany narzędzia.
    """
    print("Dezaktywuję pozycję wymiany narzędzia...")
    set_digital_output(OUT_TOOL_CHANGE_POS, False)
    time.sleep(0.25)
    print("Pozycja wymiany dezaktywowana.")


def open_collet():
    """
    Otwiera uchwyt narzędzia.
    - Sprawdza czujnik potwierdzający otwarcie uchwytu.
    """
    print("Rozpoczynam otwieranie uchwytu narzędzia...")
    set_digital_output(OUT_COLLET_OPEN, True)
    time.sleep(0.25)
    set_digital_output(OUT_COLLET_OPEN, False)

    start_time = time.time()
    while not get_digital_input(IN_COLLET_OPEN):
        if time.time() - start_time > 5:
            print("Błąd: Uchwyt narzędzia nie otworzył się.")
            return False
        time.sleep(0.1)

    print("Uchwyt narzędzia otwarty.")
    return True

def close_collet():
    """
    Zamyka uchwyt narzędzia.
    - Sprawdza czujnik potwierdzający zamknięcie uchwytu.
    """
    print("Rozpoczynam zamykanie uchwytu narzędzia...")
    set_digital_output(OUT_COLLET_CLOSE, True)
    time.sleep(0.25)
    set_digital_output(OUT_COLLET_CLOSE, False)

    start_time = time.time()
    while get_digital_input(IN_COLLET_OPEN):
        if time.time() - start_time > 5:
            print("Błąd: Uchwyt narzędzia nie zamknął się.")
            return False
        time.sleep(0.1)

    print("Uchwyt narzędzia zamknięty.")
    return True

def open_magazine():
    """
    Otwiera magazyn narzędzi.
    - Otwiera osłonę pionową i poziomą.
    - Sprawdza czujniki otwarcia osłon.
    """
    # Otwórz osłonę pionową i poziomą
    print("Otwieram magazyn...")
    set_digital_output(OUT_MAGAZINE_OPEN, True)
    time.sleep(0.25)
    set_digital_output(OUT_MAGAZINE_OPEN, False)
    
    # Sprawdź osłonę pionową
    start_time = time.time()
    while not get_digital_input(IN_Oslona_Pion_Open):
        if time.time() - start_time > 5:
            print("Błąd: Osłona pionowa nie otworzyła się.")
            return False
        time.sleep(0.1)

    # Sprawdź osłonę poziomą
    start_time = time.time()
    while not get_digital_input(IN_Oslona_Poz_Open):
        if time.time() - start_time > 5:
            print("Błąd: Osłona pozioma nie otworzyła się.")
            return False
        time.sleep(0.1)

    print("Magazyn został otwarty.")
    return True

def close_magazine():
    """
    Zamyka magazyn narzędzi.
    - Zamykana jest osłona pionowa i pozioma.
    - Sprawdza czujniki zamknięcia osłon.
    """
    print("Zamykanie magazynu...")

    # Zamknij osłonę poziomą
    set_digital_output(OUT_MAGAZINE_CLOSE, True)
    time.sleep(0.25)
    set_digital_output(OUT_MAGAZINE_CLOSE, False)

    # Sprawdź osłonę poziomą
    start_time = time.time()
    while not get_digital_input(IN_Oslona_Poz_Close):
        if time.time() - start_time > 5:
            print("Błąd: Osłona pozioma nie zamknęła się.")
            return False
        time.sleep(0.1)

    # Sprawdź osłonę pionową
    start_time = time.time()
    while not get_digital_input(IN_Oslona_Pion_Close):
        if time.time() - start_time > 5:
            print("Błąd: Osłona pionowa nie zamknęła się.")
            return False
        time.sleep(0.1)

    print("Magazyn został zamknięty.")
    return True
