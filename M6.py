from ___CONF import *
from ___FUNCTION import * 
import time   
import sys

timezone = time.localtime() 

mode = "debug" # normal or debug (for more info output)

#-----------------------------------------------------------
# Prep
#-----------------------------------------------------------

# Store some info for later use
tool_old_id     =  d.getSpindleToolNumber()
tool_new_id     =  d.getSelectedToolNumber()
tool_new_length =  d.getToolLength(tool_new_id)
machine_pos     =  d.getPosition(CoordMode.Machine)
# spindle_speed =  d.getSpindleSpeed()
spindle_state   =  d.getSpindleState()

# if debug is enabled, output some helpful information
if mode == "debug":
    print(f"{tool_old_id}  -> {tool_new_id}")

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



#-----------------------------------------------------------
#-----------------------------------------------------------
# M6 START
#-----------------------------------------------------------
#-----------------------------------------------------------

def main():

    ustaw_stan_procesu("M6")  # Oznaczamy, że wymiana narzędzia jest aktywna

    #-----------------------------------------------------------
    # Perform pre-checks
    #-----------------------------------------------------------
    
    # Odczytaj z json
    tool_old_pocket_id = odczytaj_kieszen(tool_old_id)               # Odczytaj kieszeń dla starego narzędzia
    if tool_old_pocket_id is not None:
         print(f"Numer kieszeni dla  T{tool_old_id}: {tool_old_pocket_id}")
        
    tool_new_pocket_id = odczytaj_kieszen(tool_new_id)               # Odczytaj kieszeń dla nowego narzędzia
    if tool_new_pocket_id is not None:
         print(f"Numer kieszeni dla  T{tool_new_id}: {tool_new_pocket_id}")
        
    tryb_pracy = odczytaj_tryb_pracy(tool_new_id)                    # Odczytaj Tryb pracy nowego narzędzia
    
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
        throwMessage(msg_old_equal_new, "exit")
    
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
    # Główna funkcja programu
    #-----------------------------------------------------------
    
    # ignore softlimits
    d.ignoreAllSoftLimits(True)
    
    # Spindle off
    d.setSpindleState(SpindleState.OFF)
    if spindle_state != SpindleState.OFF:
        throwMessage(msg_spindle_error, "exit")
    
    # Opuść Agregat
    aggregate_down()
    
    # Curtain up 
    curtain_up()
    
    # Aktywuj pozycję wymiany
    activate_tool_change_position()
    
    # Otwórz mgazyn narzędzi
    open_magazine()
    
    # move to safe Z 
    machine_pos[Z] = Z_SAFE
    d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
    
    #-----------------------------------------------------------
    # if a tool is in spindle, go and drop that first
    # if there is no tool in spindle, skip this part
    #-----------------------------------------------------------
    if tool_old_id > 0:
        if get_digital_input(IN_TOOL_INSIDE):
                       
            # move to the toolholder
            # Obliczenie nowej pozycji na podstawie ToolOld
            machine_pos[X] = X_BASE + (X_TOOLOFFSET * (tool_old_pocket_id - 1))
            machine_pos[Y] = Y_FORSLIDE
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
            
            # Sprawdź, czy jest wolne miejsce w magazynie narzędziowym
            if not get_digital_input(IN_Narzedzie_W_Magazynie):
                throwMessage(msg_magazine, "exit")
            
            # opuść Agregat
            aggregate_down()
            
            machine_pos[Z] = Z_TOOLGET
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
            machine_pos[Y] = Y_LOCK
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
                        
            # otwórz uchwyt
            open_collet()
            
            # załącz czyszczenie stożka
            set_digital_output(OUT_CLEANCONE , True)
    
            # odjedź na bezpieczną pozycję osi Z
            machine_pos[Z] = Z_SAFE
            d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
            
            # zamknij uchwyt, wyłącz czyszczenie stożka, podnieś agregat i wyświetl wiadomość
            close_collet()
            set_digital_output(OUT_CLEANCONE, False)
            aggregate_up()    
            d.setSpindleToolNumber(0)
            throwMessage(msg_tool_dropoff, "")
    
    #-----------------------------------------------------------
    # Pobierz nowe narzędzie
    #-----------------------------------------------------------
    
    # if a number > 0 was selected
    if tool_new_id > 0:
        if get_digital_input(IN_TOOL_INSIDE):
            throwMessage(msg_tool_unload_error, "exit")
            
        # podnieś Agregat
        aggregate_up()
        
        # Sprawdź, czy narzędzie jest w magazynie narzędzi
        machine_pos[Y] = Y_FORSLIDE
        machine_pos[X] = X_BASE + (X_TOOLOFFSET * (tool_new_pocket_id - 1))
        d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
        
        if get_digital_input(IN_Narzedzie_W_Magazynie):
            throwMessage(msg_magazine_get, "exit")
    
        # przejedź do pozycji nowego narzędzia
        machine_pos[Y] = Y_LOCK
        machine_pos[X] = X_BASE + (X_TOOLOFFSET * (tool_new_pocket_id - 1))
        d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_xy)
    
        # otwórz uchwyt
        open_collet()
    
        # opuść Agregat
        aggregate_down()
    
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
        machine_pos[Z] = Z_TOOLGET + Z_LIFT
        d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_fast)
        machine_pos[Z] = Z_TOOLGET
        d.moveToPosition(CoordMode.Machine, machine_pos, feed_atc_z_final)
    
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
    curtain_down()

    # Ustaw tryb pracy dla narzędzia
    if tryb_pracy is not None:
        print(f"Tryb pracy dla narzędzia T{tool_new_id}: {tryb_pracy}")
    if tryb_pracy == "Góra":
        aggregate_up()
    elif tryb_pracy == "Dół":
        aggregate_down()

    ustaw_stan_procesu(None)
    
    # Zamknij mgazyn narzędzi
    close_magazine()
    
    # Przywrócenie softlimitów
    d.ignoreAllSoftLimits(False)
    print("Softlimity przywrócone.")
    throwMessage(msg_m6_end, "")
    
# Uruchomienie programu, jeśli jest wywoływany jako główny skrypt
if __name__ == "__main__":
    main()
