from ___CONF import * 
import time   
import sys
import json
import threading

JSON_FILE = "narzedzia.json"

# Mapowanie wartości liczbowych na nazwy trybu pracy
TRYB_PRACY_MAP = {0: "Dół", 1: "Góra"}
TRYB_PRACY_REVERSE = {"Dół": 0, "Góra": 1}

timezone = time.localtime() 

mode = "normal" # normal or debug (for more info output)

# warunek sprawdzania obecnosci narzędzia podczas pobierania
check_tool = False    # True lub False

# === DODANE: Synchronizacja wielowątkowości ===
io_lock = threading.RLock()  # Mutex do synchronizacji IO
error_event = threading.Event()  # Event do sygnalizowania błędów
error_messages = []  # Lista komunikatów błędów

#-----------------------------------------------------------
# Check status of pin 
#-----------------------------------------------------------

msg_air_warning         = "🔴 ERR - ATC - air pressure too low"
msg_clamp_error         = "🔴 ERR - ATC - Clamp could not be opened"
msg_clamp_error_close	= "🔴 ERR - ATC - Clamp could not be closed"
msg_spindle_error       = "🔴 ERR - ATC - Spindle still spinning" 
msg_old_equal_new       = "ℹ️ ATC - New tool equal to old tool. M6 aborted"
msg_tool_out_range      = "🔴 ERR - ATC - Selected tool out of range"
msg_tool_unload_error   = "🔴 ERR - ATC - Could not unload tool"
msg_tool_load_error     = "🔴 ERR - ATC - Could not load tool" 
msg_ref_error           = "🔴 ERR - ATC - Axis not referenced"
msg_tool_zero           = "🔴 ERR - ATC - Tool zero cannot be called"
msg_tool_count          = "🔴 ERR - ATC - Tool number out of range"
msg_tool_special        = "🔴 ERR - ATC - Special tool, not available for auto tool change"
msg_tool_dropoff        = "✅ ATC - Old tool dropped off"
msg_m6_end              = "✅ ATC - M6 successful"
msg_noprobe             = "ℹ️ ATC - Tool probing aborted, tool number in exception list"
msg_unknow_tool         = "⚠️ Nieznane narzędzie w uchwycie"
msg_magazine            = "⚠️ Brak miejsca w magazynie narzędzi"
msg_magazine_get        = "⚠️ Brak narzędzia w magazynie narzędzi"

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

#-----------------------------------------------------------
# Prep
#-----------------------------------------------------------

# Store some info for later use
tool_old_id     =  d.getSpindleToolNumber()
tool_new_id     =  d.getSelectedToolNumber()
tool_new_length =  d.getToolLength(tool_new_id)
machine_pos     =  d.getPosition(CoordMode.Machine)
spindle_state   =  d.getSpindleState()

# if debug is enabled, output some helpful information
if mode == "debug":        # normal or debug (for more info output)
    print(f"{tool_old_id}  -> {tool_new_id}")

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# POPRAWIONE: Bezpieczne funkcje IO z obsługą wielowątkowości
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def safe_io_operation(operation_func, max_retries=3, retry_delay=0.1):
    """Wrapper dla bezpiecznych operacji IO z ponowieniem próby"""
    for attempt in range(max_retries):
        try:
            with io_lock:
                return operation_func()
        except (KeyError, AttributeError, Exception) as e:
            if attempt == max_retries - 1:
                error_msg = f"Błąd IO po {max_retries} próbach: {e}"
                print(error_msg)
                error_messages.append(error_msg)
                error_event.set()
                return None
            time.sleep(retry_delay * (attempt + 1))
    return None

def get_digital_input(pin_tuple):
    """POPRAWIONE: Bezpieczne odczytywanie wejścia cyfrowego z obsługą wielowątkowości."""
    def _read_input():
        module_id, pin, module_type = pin_tuple

        if module_type == "IP":
            csmio = d.getModule(ModuleType.IP, module_id)
        elif module_type == "IO":
            csmio = d.getModule(ModuleType.IO, module_id)
        else:
            raise ValueError(f"Nieznany typ modułu {module_type}")

        if pin is None:
            raise ValueError("Pin nie został podany")

        if csmio is None:
            raise RuntimeError(f"Nie można uzyskać dostępu do modułu {module_type}:{module_id}")

        value = csmio.getDigitalIO(IOPortDir.InputPort, pin) == DIOPinVal.PinSet
        return value
    
    return safe_io_operation(_read_input)

def set_digital_output(pin_tuple, state):
    """POPRAWIONE: Bezpieczne ustawianie wyjścia cyfrowego z obsługą wielowątkowości."""
    def _set_output():
        module_id, pin, module_type = pin_tuple
        state2 = DIOPinVal.PinSet if state else DIOPinVal.PinReset

        if module_type == "IP":
            csmio = d.getModule(ModuleType.IP, module_id)
        elif module_type == "IO":
            csmio = d.getModule(ModuleType.IO, module_id)
        else:
            raise ValueError(f"Nieznany typ modułu {module_type}")

        if pin is None:
            raise ValueError("Pin nie został podany")

        if csmio is None:
            raise RuntimeError(f"Nie można uzyskać dostępu do modułu {module_type}:{module_id}")

        csmio.setDigitalIO(pin, state2)
        return True
    
    return safe_io_operation(_set_output)

def wait_for_input_with_timeout(input_pin, timeout=5, check_interval=0.05):
    """DODANE: Oczekiwanie na wejście z obsługą błędów i timeout"""
    start_time = time.time()
    
    while not error_event.is_set():
        if time.time() - start_time > timeout:
            error_msg = f"Timeout: Wejście {input_pin} nie zostało aktywowane w ciągu {timeout}s"
            print(error_msg)
            error_messages.append(error_msg)
            error_event.set()
            return False
            
        input_state = get_digital_input(input_pin)
        if input_state is None:
            return False
        elif input_state:
            return True
            
        time.sleep(check_interval)
    
    return False

#-----------------------------------------------------------
# Operacje na json
#-----------------------------------------------------------

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
    data = wczytaj_ustawienia()
  
    # Sprawdza, czy narzędzie istnieje w danych
    if str(narzedzie) in data:
        kieszen = data[str(narzedzie)]["kieszen"]
        return kieszen
    else:
        # POPRAWIONE: Usunięto messagebox.showerror (nie jest dostępne w tym kontekście)
        print(f"Błąd: Narzędzie {narzedzie} nie znaleziono w pliku JSON.")
        return None

def odczytaj_tryb_pracy(narzedzie):
    """Odczytuje tryb pracy dla podanego narzędzia z pliku JSON."""
    data = wczytaj_ustawienia()

    if str(narzedzie) in data:
        tryb_pracy = data[str(narzedzie)]["tryb_pracy"]
        return tryb_pracy
    else:
        # POPRAWIONE: Usunięto messagebox.showerror (nie jest dostępne w tym kontekście)
        print(f"Błąd: Narzędzie {narzedzie} nie znaleziono w pliku JSON.")
        return None

#-----------------------------------------------------------
# POPRAWIONE: Lista programów z obsługą wielowątkowości
#-----------------------------------------------------------

def check_axes_referenced():
    axis_to_check = [Axis.X, Axis.Y, Axis.Z]
    not_referenced_axes = []

    for axis in axis_to_check:
        if not d.isAxisReferenced(axis):
            not_referenced_axes.append(axis)

    if not_referenced_axes:
        msg_axes_referenced = f"🔴 Osi(e) {', '.join([str(axis) for axis in not_referenced_axes])} nie są zbazowane! Uruchom proces bazowania."
        throwMessage(msg_axes_referenced, "exit")

def curtain_up():
    """POPRAWIONE: Podnosi szczotkę z obsługą wielowątkowości."""
    try:
        if mode == "debug":
            print("Rozpoczynam podnoszenie szczotki...")
        
        if set_digital_output(OUT_CURTAIN_UP, True) is None:
            return False
        time.sleep(0.25)
        if set_digital_output(OUT_CURTAIN_UP, False) is None:
            return False

        if wait_for_input_with_timeout(IN_CURTAIN_UP, 5):
            if mode == "debug":
                print("Szczotka podniesiona.")
            return True
        else:
            print("Błąd: Szczotka nie osiągnęła pozycji górnej.")
            error_event.set()
            return False
            
    except Exception as e:
        error_msg = f"Błąd w curtain_up(): {e}"
        print(error_msg)
        error_messages.append(error_msg)
        error_event.set()
        return False

def curtain_down():
    """POPRAWIONE: Opuszcza szczotkę z obsługą wielowątkowości."""
    try:
        if mode == "debug":
            print("Rozpoczynam opuszczanie szczotki...")
        
        if set_digital_output(OUT_CURTAIN_DOWN, True) is None:
            return False
        time.sleep(0.25)
        if set_digital_output(OUT_CURTAIN_DOWN, False) is None:
            return False

        if wait_for_input_with_timeout(IN_CURTAIN_DOWN, 5):
            if mode == "debug":    
                print("Szczotka opuszczona.")
            return True
        else:
            print("Błąd: Szczotka nie osiągnęła pozycji dolnej.")
            error_event.set()
            return False
            
    except Exception as e:
        error_msg = f"Błąd w curtain_down(): {e}"
        print(error_msg)
        error_messages.append(error_msg)
        error_event.set()
        return False

def aggregate_up():
    """POPRAWIONE: Podnosi agregat z obsługą wielowątkowości."""
    try:
        if mode == "debug":
            print("Rozpoczynam podnoszenie agregatu...")
        
        if set_digital_output(OUT_AGGREGATE_UP, True) is None:
            return False
        time.sleep(0.25)
        if set_digital_output(OUT_AGGREGATE_UP, False) is None:
            return False

        if wait_for_input_with_timeout(IN_AGGREGATE_UP, 5):
            if mode == "debug":
                print("Agregat podniesiony.")
            return True
        else:
            print("Błąd: Agregat nie osiągnął pozycji górnej.")
            error_event.set()
            return False
            
    except Exception as e:
        error_msg = f"Błąd w aggregate_up(): {e}"
        print(error_msg)
        error_messages.append(error_msg)
        error_event.set()
        return False

def aggregate_down():
    """POPRAWIONE: Opuszcza agregat z obsługą wielowątkowości."""
    try:
        if mode == "debug":
            print("Rozpoczynam opuszczanie agregatu...")
        
        if set_digital_output(OUT_AGGREGATE_DOWN, True) is None:
            return False
        time.sleep(0.25)
        if set_digital_output(OUT_AGGREGATE_DOWN, False) is None:
            return False

        if wait_for_input_with_timeout(IN_AGGREGATE_DOWN, 5):
            if mode == "debug":
                print("Agregat opuszczony.")
            return True
        else:
            print("Błąd: Agregat nie osiągnął pozycji dolnej.")
            error_event.set()
            return False
            
    except Exception as e:
        error_msg = f"Błąd w aggregate_down(): {e}"
        print(error_msg)
        error_messages.append(error_msg)
        error_event.set()
        return False

def activate_tool_change_position():
    """Aktywuje pozycję wymiany narzędzia."""
    if mode == "debug":
        print("Aktywuję pozycję wymiany narzędzia...")
    set_digital_output(OUT_TOOL_CHANGE_POS, True)
    time.sleep(0.25)
    if mode == "debug":
        print("Pozycja wymiany aktywowana.")

def deactivate_tool_change_position():
    """Dezaktywuje pozycję wymiany narzędzia."""
    if mode == "debug":
        print("Dezaktywuję pozycję wymiany narzędzia...")
    set_digital_output(OUT_TOOL_CHANGE_POS, False)
    time.sleep(0.25)
    if mode == "debug":
        print("Pozycja wymiany dezaktywowana.")

def open_collet():
    """POPRAWIONE: Otwiera uchwyt narzędzia z obsługą wielowątkowości."""
    try:
        if mode == "debug":
            print("Rozpoczynam otwieranie uchwytu narzędzia...")
        
        if set_digital_output(OUT_COLLET_OPEN, True) is None:
            return False
        time.sleep(0.25)
        if set_digital_output(OUT_COLLET_OPEN, False) is None:
            return False

        if wait_for_input_with_timeout(IN_COLLET_OPEN, 5):
            if mode == "debug":
                print("Uchwyt narzędzia otwarty.")
            return True
        else:
            print("Błąd: Uchwyt narzędzia nie otworzył się.")
            throwMessage(msg_clamp_error, "exit")
            return False
            
    except Exception as e:
        error_msg = f"Błąd w open_collet(): {e}"
        print(error_msg)
        error_messages.append(error_msg)
        error_event.set()
        return False

def close_collet():
    """POPRAWIONE: Zamyka uchwyt narzędzia z obsługą wielowątkowości."""
    try:
        if mode == "debug":
            print("Rozpoczynam zamykanie uchwytu narzędzia...")
        
        if set_digital_output(OUT_COLLET_CLOSE, True) is None:
            return False
        time.sleep(0.25)
        if set_digital_output(OUT_COLLET_CLOSE, False) is None:
            return False

        # POPRAWIONE: Oczekiwanie aż IN_COLLET_OPEN będzie False (uchwyt zamknięty)
        start_time = time.time()
        while not error_event.is_set():
            if time.time() - start_time > 5:
                print("Błąd: Uchwyt narzędzia nie zamknął się.")
                throwMessage(msg_clamp_error_close, "exit")
                return False
                
            collet_state = get_digital_input(IN_COLLET_OPEN)
            if collet_state is None:
                return False
            elif not collet_state:  # Uchwyt zamknięty gdy IN_COLLET_OPEN = False
                if mode == "debug":
                    print("Uchwyt narzędzia zamknięty.")
                return True
            time.sleep(0.1)
        
        return False
            
    except Exception as e:
        error_msg = f"Błąd w close_collet(): {e}"
        print(error_msg)
        error_messages.append(error_msg)
        error_event.set()
        return False

def open_magazine():
    """POPRAWIONE: Otwiera magazyn narzędzi z obsługą wielowątkowości."""
    try:
        if mode == "debug":
            print("Otwieram magazyn...")
        
        if set_digital_output(OUT_MAGAZINE_OPEN, True) is None:
            return False
        time.sleep(0.25)
        if set_digital_output(OUT_MAGAZINE_OPEN, False) is None:
            return False
        
        # Sprawdź osłonę pionową
        if not wait_for_input_with_timeout(IN_Oslona_Pion_Open, 5):
            print("Błąd: Osłona pionowa nie otworzyła się.")
            error_event.set()
            return False

        # Sprawdź osłonę poziomą
        if not wait_for_input_with_timeout(IN_Oslona_Poz_Open, 5):
            print("Błąd: Osłona pozioma nie otworzyła się.")
            error_event.set()
            return False
            
        if mode == "debug":
            print("Magazyn został otwarty.")
        return True
        
    except Exception as e:
        error_msg = f"Błąd w open_magazine(): {e}"
        print(error_msg)
        error_messages.append(error_msg)
        error_event.set()
        return False

def close_magazine():
    """POPRAWIONE: Zamyka magazyn narzędzi z obsługą wielowątkowości."""
    try:
        if mode == "debug":
            print("Zamykanie magazynu...")

        if set_digital_output(OUT_MAGAZINE_CLOSE, True) is None:
            return False
        time.sleep(0.25)
        if set_digital_output(OUT_MAGAZINE_CLOSE, False) is None:
            return False

        # Sprawdź osłonę poziomą
        if not wait_for_input_with_timeout(IN_Oslona_Poz_Close, 5):
            print("Błąd: Osłona pozioma nie zamknęła się.")
            return False

        # Sprawdź osłonę pionową
        if not wait_for_input_with_timeout(IN_Oslona_Pion_Close, 5):
            print("Błąd: Osłona pionowa nie zamknęła się.")
            return False
            
        if mode == "debug":
            print("Magazyn został zamknięty.")
        return True
        
    except Exception as e:
        error_msg = f"Błąd w close_magazine(): {e}"
        print(error_msg)
        error_messages.append(error_msg)
        error_event.set()
        return False

def emergency_stop():
    """DODANE: Funkcja awaryjnego zatrzymania"""
    print("AWARYJNE ZATRZYMANIE - wykryto błędy:")
    for msg in error_messages:
        print(f"  - {msg}")
    d.stopTrajectory()

#-----------------------------------------------------------
#-----------------------------------------------------------
# M6 START
#-----------------------------------------------------------
#-----------------------------------------------------------

def main():
    
    #-----------------------------------------------------------
    # Perform pre-checks
    #-----------------------------------------------------------
    
    # Odczytaj z json
    tool_old_pocket_id = odczytaj_kieszen(tool_old_id)                      # Odczytaj kieszeń dla starego narzędzia
    if tool_old_pocket_id is not None:
        print(f"Numer kieszeni dla  T{tool_old_id}: {tool_old_pocket_id}")
        
    tool_new_pocket_id = odczytaj_kieszen(tool_new_id)                       # Odczytaj kieszeń dla nowego narzędzia
    if tool_new_pocket_id is not None:
        print(f"Numer kieszeni dla  T{tool_new_id}: {tool_new_pocket_id}")
        
    tryb_pracy = odczytaj_tryb_pracy(tool_new_id)                            # Odczytaj Tryb pracy nowego narzędzia
    
    # exit if axes not referenced
    check_axes_referenced()
    
    # exit if tool is in exception list for auto-tool-change 
    if tool_new_id in conf_tools_special:
        throwMessage(msg_tool_special, "exit")   
    
    # exit if air pressure is too low 
    if not get_digital_input(IN_PRESSURE):  
        throwMessage(msg_air_warning, "exit")

    # exit if tool is already in spindle
    if tool_old_id == tool_new_id: 
        throwMessage(msg_old_equal_new, "")
        sys.exit(0)
    
    # exit on tool zero
    if tool_new_id == 0: 
        throwMessage(msg_tool_zero, "exit") 
    
    # exit if tool is out of range
    if tool_new_pocket_id > TOOLCOUNT:
        throwMessage(msg_tool_count, "exit") 	 
    
    # exit if unknown tool in the holder
    if tool_old_id == 0 and get_digital_input(IN_TOOL_INSIDE):
        throwMessage(msg_unknow_tool, "exit")
    
    #-----------------------------------------------------------
    # POPRAWIONE: Główna funkcja programu z obsługą wielowątkowości
    #-----------------------------------------------------------
    
    try:
        # Resetuj stan błędów
        error_event.clear()
        error_messages.clear()
        
        # ignore softlimits
        d.ignoreAllSoftLimits(True)
        
        # Spindle off
        d.setSpindleState(SpindleState.OFF)
        if spindle_state != SpindleState.OFF:
            throwMessage(msg_spindle_error, "exit")

        # POPRAWIONE: Uruchom równoległe operacje na początku
        if mode == "debug":
            print("Rozpoczynam równoległe operacje...")
        
        t_aggregate_down = threading.Thread(target=aggregate_down, name="AggregateDownThread")
        t_aggregate_up = threading.Thread(target=aggregate_up, name="AggregateUpThread")
        t_magazine_open = threading.Thread(target=open_magazine, name="MagazineOpenThread")
        t_magazine_close = threading.Thread(target=close_magazine, name="MagazineCloseThread")
        t_curtain_up = threading.Thread(target=curtain_up, name="CurtainUpThread")
        t_curtain_down = threading.Thread(target=curtain_down, name="CurtainDownThread")
        
        # Uruchom wątki
        t_magazine_open.start()
        t_curtain_up.start()

        active_threads = [t_magazine_open, t_curtain_up]

        if not get_digital_input(IN_AGGREGATE_DOWN):
            t_aggregate_down.start()
            active_threads.append(t_aggregate_down)
                   
        # Poczekaj na zakończenie z timeout
        timeout = 10       
        for i, thread in enumerate(active_threads):
            thread.join(timeout=timeout)
            if thread.is_alive():
                thread_names = ["magazynu", "szczotki", "agregatu"]  # Kolejność musi odpowiadać active_threads
                print(f"OSTRZEŻENIE: Wątek {thread_names[i]} przekroczył timeout")
                error_event.set()

        # Jeśli wystąpiły błędy, zatrzymaj wykonanie
        if error_event.is_set():
            emergency_stop()
            return

        # Aktywuj pozycję wymiany
        activate_tool_change_position()
        
        # move to safe Z 
        machine_pos[Z] = Z_SAFE
        d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
        
        #-----------------------------------------------------------
        # if a tool is in spindle, go and drop that first
        # if there is no tool in spindle, skip this part
        #-----------------------------------------------------------
        if tool_old_id > 0:
            if get_digital_input(IN_TOOL_INSIDE):

                # Obliczenie pozycji narzędzia
                tool_pos_x = X_BASE + (X_TOOLOFFSET * (tool_old_pocket_id - 1))

                # Określenie czujnika i pozycji sprawdzającej
                if tool_old_pocket_id <= 10:
                    # Lewy czujnik (pozycja +2.5 offsetu od X_BASE)
                    check_sensor_input = IN_Narzedzie_W_Magazynie
                    sensor_pos_x = tool_pos_x + (2.5 * X_TOOLOFFSET)
                else:
                    # Prawy czujnik (pozycja -2.5 offsetu od X_BASE)
                    check_sensor_input = IN_Narzedzie_W_Magazynie_2
                    sensor_pos_x = tool_pos_x - (2.5 * X_TOOLOFFSET)
                
                # Podjazd do pozycji czujnika
                machine_pos[X] = sensor_pos_x
                machine_pos[Y] = Y_FORSLIDE
                d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
                
                # Sprawdzenie, czy narzędzie jest obecne
                if not get_digital_input(check_sensor_input):
                    throwMessage(msg_magazine, "exit")
                
                # Podjedź do pozycji narzędzia
                machine_pos[X] = tool_pos_x
                d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)            

                machine_pos[Z] = Z_TOOLGET
                d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
                machine_pos[Y] = Y_LOCK
                d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
                            
                # otwórz uchwyt
                if not open_collet():
                    return  # przerwij dalsze wykonywanie
                
                # załącz czyszczenie stożka
                set_digital_output(OUT_CLEANCONE , True)
        
                # odjedź na bezpieczną pozycję osi Z
                machine_pos[Z] = Z_SAFE
                d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
                
                # zamknij uchwyt, wyłącz czyszczenie stożka i wyświetl wiadomość
                close_collet()
                set_digital_output(OUT_CLEANCONE, False)
                
                d.setSpindleToolNumber(0)
                throwMessage(msg_tool_dropoff, "")
        
        #-----------------------------------------------------------
        # Pobierz nowe narzędzie
        #-----------------------------------------------------------
        
        # if a number > 0 was selected
        if tool_new_id > 0:
            if get_digital_input(IN_TOOL_INSIDE):
                throwMessage(msg_tool_unload_error, "exit")
            
            # odjedź na bezpieczną pozycję osi Z
            machine_pos[Z] = Z_SAFE
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
                
            # Obliczenie pozycji narzędzia
            tool_pos_x = X_BASE + (X_TOOLOFFSET * (tool_new_pocket_id - 1))

            # sprawdz czy narzędzie jest obecne
            if check_tool == True:
                # Określenie czujnika i pozycji sprawdzającej
                if tool_new_pocket_id <= 10:
                    # Lewy czujnik (pozycja +2.5 offsetu od X_BASE)
                    check_sensor_input = IN_Narzedzie_W_Magazynie
                    sensor_pos_x = tool_pos_x + (2.5 * X_TOOLOFFSET)
                else:
                    # Prawy czujnik (pozycja -2.5 offsetu od X_BASE)
                    check_sensor_input = IN_Narzedzie_W_Magazynie_2
                    sensor_pos_x = tool_pos_x - (2.5 * X_TOOLOFFSET)
                
                # Podjazd do pozycji czujnika
                machine_pos[X] = sensor_pos_x
                machine_pos[Y] = Y_FORSLIDE
                d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
                
                # Sprawdzenie, czy narzędzie JEST obecne w magazynie
                if get_digital_input(check_sensor_input):
                    throwMessage(msg_magazine_get, "exit")
            
            # Podjedź do pozycji nowego narzędzia
            machine_pos[X] = tool_pos_x
            machine_pos[Y] = Y_LOCK
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
            
            # Otwórz uchwyt
            if not open_collet():
                return  # przerwij dalsze wykonywanie
                
            # załącz czyszczenie stożka
            set_digital_output(OUT_CLEANCONE , True)
            
            machine_pos[Z] = Z_TOOLGET + Z_LIFT
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
            machine_pos[Z] = Z_TOOLGET
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
            machine_pos[Z] = Z_TOOLGET + Z_LIFT
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
            machine_pos[Z] = Z_TOOLGET
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
        
            # zamknij uchwyt i wyłącz czyszczenie stożka
            close_collet()
            set_digital_output(OUT_CLEANCONE, False)
            
            time.sleep(conf_pause_debounce)
        
            # exit if no tool was picked up 
            if not get_digital_input(IN_TOOL_INSIDE):
                throwMessage(msg_tool_load_error, "exit")
        
            # wyjedź poza uchwyt narzędzia
            machine_pos[Y] = Y_FORSLIDE
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
        
            # przejedź do bezpiecznej pozycji Z poza magazyn
            machine_pos[Z] = Z_SAFE
            machine_pos[Y] = 1550
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
        
        #-----------------------------------------------------------
        # Finish up and provide information to simCNC 
        #-----------------------------------------------------------
        
        # Set new tool in simCNC 
        d.setToolLength (tool_new_id, tool_new_length)
        d.setToolOffsetNumber(tool_new_id)
        d.setSpindleToolNumber(tool_new_id)
    
        # Dezaktywuje pozycję wymiany
        deactivate_tool_change_position()
        
        # Opuść szczotkę
        t_curtain_down.start()
        
        # Zamknij mgazyn narzędzi
        t_magazine_close.start()
        
        active_threads = [t_curtain_down, t_magazine_close]
    
        # Ustaw tryb pracy dla narzędzia
        if tryb_pracy == "Góra":
            t_aggregate_up.start()
            active_threads.append(t_aggregate_up)
        elif tryb_pracy == "Dół":
            t_aggregate_down.start()
            active_threads.append(t_aggregate_down)
            
        # Poczekaj na wszystkie aktywne wątki
        timeout = 10    
        for i, thread in enumerate(active_threads):
            thread.join(timeout=timeout)
            if thread.is_alive():
                thread_names = ["szczotki", "magazynu", "agregatu"]
                print(f"OSTRZEŻENIE: Wątek {thread_names[i]} przekroczył timeout")
                error_event.set()
            
        # Przywrócenie softlimitów
        d.ignoreAllSoftLimits(False)
        print("Softlimity przywrócone.")
        throwMessage(msg_m6_end, "")
    
        # Jeśli wystąpiły błędy, zatrzymaj wykonanie
        if error_event.is_set():
            emergency_stop()
            return

    except Exception as e:
        print(f"Krytyczny błąd w głównej pętli: {e}")
        d.stopTrajectory()
      
# Uruchomienie programu, jeśli jest wywoływany jako główny skrypt
if __name__ == "__main__":
    main()
