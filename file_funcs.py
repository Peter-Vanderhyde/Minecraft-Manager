import json
import os
import shutil
import queries
import time
import glob
import subprocess
import zipfile
from pathlib import Path
from PyQt6.QtWidgets import QFileDialog, QProgressDialog, QApplication, QMessageBox
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from queries import version_comparison

def get_appdata_path():
    base = (os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA"))
    if not base:
        raise RuntimeError("No APPDATA or LOCALAPPDATA available.")

    path = os.path.join(base, "Minecraft Manager")
    os.makedirs(path, exist_ok=True)
    return path

APPDATA_PATH = get_appdata_path()
MANAGER_SETTINGS = os.path.join(APPDATA_PATH, "manager_settings.json")

def load_settings(log_queue, file_lock):
    data = {
        "ip": f"",
        "names": {},
        "server folder": {
            "path": "",
            "worlds": {},
            "world order": []
        },
        "universal settings": {
            "gui enabled": False,
            "whitelist enabled": False,
            "view distance": 10,
            "simulation distance": 10
        }
    }
    try:
        with open(MANAGER_SETTINGS, 'r') as f:
            data = json.load(f)
    except:
        with open(MANAGER_SETTINGS, 'w') as f:
            json.dump(data, f, indent=4)
        log_queue.put("Settings file not found.")
        log_queue.put("Created new manager_settings.json file.")
        return "", {}, "", {}, [], {}
    
    host_ip = data.get("ip")
    ips = data.get("names")
    server_path = data["server folder"].get("path")
    worlds = data["server folder"].get("worlds")
    world_order = data["server folder"].get("world order", [])
    universal_settings = data.get("universal settings")
    
    if worlds is not None:
        if server_path:
            worlds = load_worlds(server_path, worlds, log_queue)
    else:
        worlds = {}
        log_queue.put(f"<font color='red'>Missing worlds key in the settings.</font>")
    
    if host_ip is None or ips is None:
        if ips is None:
            ips = {}
        if host_ip is None:
            host_ip = ""
        update_settings(file_lock, ips, server_path, worlds, world_order, universal_settings, ip=host_ip)
    return host_ip, ips, server_path, worlds, world_order, universal_settings

def load_worlds(server_path, worlds, log_queue):
    # Add worlds folder if not already present
    if not os.path.isdir(os.path.join(server_path, "worlds")):
        try:
            if not os.path.isdir(server_path):
                return worlds
            os.mkdir(os.path.join(server_path, "worlds"))
        except:
            return {}
    
    worlds_to_ignore = []
    
    for world, data in worlds.items():
        directory = os.path.join(server_path, "worlds")
        world_folder_path = os.path.join(directory, world)
        if not os.path.isdir(world_folder_path):
            if data.get("seed") is None:
                log_queue.put(f"<font color='red'>ERROR: Unable to find the '{world}' world folder.</font>")
                worlds_to_ignore.append(world)
        elif not data.get("version"):
            log_queue.put(f"<font color='red'>ERROR: Unspecified version for '{world}' world.</font>")
            worlds_to_ignore.append(world)
        elif not data.get("fabric") or data.get("fabric") != True:
            worlds[world]["fabric"] = False
        
    for world in worlds_to_ignore:
        worlds.pop(world)
    
    save_all_world_properties(server_path, worlds)
    
    return worlds

def update_settings(file_lock, ips, server_path, worlds, world_order, universal_settings, ip=""):
    with file_lock:
        with open(MANAGER_SETTINGS, 'w') as f:
            json.dump({"ip": ip, "names": ips, "server folder": {"path": server_path, "worlds": worlds, "world order": world_order}, "universal settings": universal_settings}, f, indent=4)
    save_all_world_properties(server_path, worlds)

def prepare_server_settings(world, version, gamemode, difficulty, fabric, level_type, server_path, log_queue, seed=None):
    # Change the properties
    try:
        with open(os.path.join(server_path, "eula.txt"), 'r') as f:
            content = f.read()
        if "eula=false" in content:
            log_queue.put("<font color='orange'>WARNING: The EULA has not been accepted yet! Please open eula.txt.</font>")
            return False
        
        with open(MANAGER_SETTINGS, 'r') as manager_settings:
            settings = json.loads(manager_settings.read())
        
        universal_settings = settings.get("universal settings", {
            "gui enabled": False,
            "whitelist enabled": False,
            "view distance": 10,
            "simulation distance": 10
        })
        
        with open(os.path.join(server_path, "server.properties"), 'r') as properties:
            lines = properties.readlines()
        
        found_world = False
        found_seed = False
        found_gamemode = False
        found_force_gamemode = False
        found_hardcore = False
        found_difficulty = False
        found_level_type = False
        found_query = False
        found_port = False
        found_fabric = False
        found_version = False
        found_whitelist = False
        found_view = False
        found_simulation = False
        for i, line in enumerate(lines):
            if line.startswith("level-name="):
                lines[i] = f"level-name=worlds/{world}\n"
                found_world = True
            elif line.startswith("level-seed="):
                if seed is not None:
                    lines[i] = f"level-seed={seed}\n"
                else:
                    lines[i] = f"level-seed=\n"
                found_seed = True
            elif line.startswith("gamemode="):
                if gamemode == "Hardcore":
                    lines[i] = "gamemode=survival\n"
                else:
                    lines[i] = f"gamemode={gamemode.lower()}\n"
                found_gamemode = True
            elif gamemode == "Creative" and line.startswith("force-gamemode="):
                lines[i] = "force-gamemode=true\n"
                found_force_gamemode = True
            elif line.startswith("hardcore="):
                if gamemode == "Hardcore":
                    lines[i] = "hardcore=true\n"
                else:
                    lines[i] = "hardcore=false\n"
                found_hardcore = True
            elif line.startswith("difficulty="):
                lines[i] = f"difficulty={difficulty.lower()}\n"
                found_difficulty = True
            elif line.startswith("level-type"):
                if version_comparison(version, "1.13", before=True):
                    lines[i] = f"level-type={level_type.upper().replace(' ', '')}\n"
                else:
                    lines[i] = f"level-type=minecraft\\:{level_type.lower().replace(' ', '_')}\n"
                found_level_type = True
            elif line.startswith("enable-query="):
                lines[i] = "enable-query=true\n"
                found_query = True
            elif line.startswith("query.port="):
                lines[i] = "query.port=25565\n"
                found_port = True
            elif line.startswith("fabric="):
                lines[i] = f"fabric={"true" if fabric else "false"}\n"
                found_fabric = True
            elif line.startswith("version="):
                lines[i] = f"version={version}\n"
                found_version = True
            elif line.startswith("white-list="):
                lines[i] = f"white-list={"true" if universal_settings.get("whitelist enabled") else "false"}\n"
                found_whitelist = True
            elif line.startswith("view-distance="):
                lines[i] = f"view-distance={str(min(32, max(3, universal_settings.get("view distance")))) or "10"}\n"
                found_view = True
            elif line.startswith("simulation-distance="):
                lines[i] = f"simulation-distance={str(min(32, max(3, universal_settings.get("simulation distance")))) or "10"}\n"
                found_simulation = True
        
        if not found_world:
            lines.append(f"level-name=worlds/{world}\n")
        if not found_seed:
            lines.append(f"level-seed={seed if seed is not None else ""}\n")
        if not found_gamemode:
            if gamemode == "Hardcore":
                lines.append("gamemode=survival\n")
            else:
                lines.append(f"gamemode={gamemode.lower()}\n")
        elif not found_force_gamemode and gamemode == "Creative":
            lines.append("force-gamemode=true\n")
        if not found_hardcore:
            if gamemode == "Hardcore":
                lines.append("hardcore=true\n")
        if not found_difficulty:
            lines.append(f"difficulty={difficulty.lower()}\n")
        if not found_level_type:
            if version_comparison(version, "1.13", before=True):
                lines.append(f"level-type={level_type.upper().replace(' ', '')}\n")
            else:
                lines.append(f"level-type=minecraft\\:{level_type.lower().replace(' ', '_')}\n")
        if not found_query:
            lines.append("enable-query=true\n")
        if not found_port:
            lines.append("query.port=25565\n")
        if not found_fabric:
            lines.append("fabric=false\n")
        if not found_version:
            lines.append(f"version={version}\n")
        if not found_whitelist:
            lines.append(f"white-list=false\n")
        if not found_view:
            lines.append(f"view-distance=10\n")
        if not found_simulation:
            lines.append(f"simulation-distance=10\n")
        
        with open(os.path.join(server_path, "server.properties"), 'w') as properties:
            properties.writelines(lines)
        
        if not fabric:
            source_path = os.path.join(server_path, "versions", version, f"server-{version}.jar")
            if not os.path.isfile(source_path):
                # Download needed jar
                if not os.path.isdir(os.path.join(server_path, "versions")):
                    os.mkdir(os.path.join(server_path, "versions"))
                if not os.path.isdir(os.path.join(server_path, "versions", version)):
                    os.mkdir(os.path.join(server_path, "versions", version))
            
            jars = glob.glob(os.path.join(server_path, "*.jar"))
            for jar in jars:
                os.remove(jar)
            
            if not queries.download_server_jar(version, os.path.join(server_path, "versions", version), log_queue):
                return False
            
            time.sleep(1)
            # Delete libraries and re-extract them
            if os.path.isdir(os.path.join(server_path, "libraries")):
                os.system(f"rmdir /s /q {os.path.join(server_path, 'libraries')}")
            
            destination = server_path
            new_name = f"server-{version}.jar"
            shutil.copy2(source_path, os.path.join(destination, new_name))
            try:
                with open(os.path.join(server_path, "run.bat"), 'r') as b:
                    line = b.read()
            except:
                # No run.bat but will create new one with default "java -jar <file>" commands
                line = "java -jar "
            command, previous_file = line.split(" -jar ")
            command.replace("javaw", "java") # Ensure using java instead of javaw
            new_command = f"{command or 'java'} -jar {new_name}"
            with open(os.path.join(server_path, "run.bat"), 'w') as b:
                b.write(new_command)
            time.sleep(1)
        
        else:
            jars = glob.glob(os.path.join(server_path, f"fabric-server-*.jar"))
            while len(jars) > 1:
                os.remove(os.path.join(server_path, jars[0]))
            
            queries.download_fabric_server_jar(version, server_path, log_queue)
            
            time.sleep(1)
            # Delete libraries and re-extract them
            if os.path.isdir(os.path.join(server_path, "libraries")):
                os.system(f"rmdir /s /q {os.path.join(server_path, 'libraries')}")
            
            try:
                with open(os.path.join(server_path, "run.bat"), 'r') as b:
                    line = b.read()
            except:
                # No run.bat but will create new one with default "java -jar <file>" commands
                line = "java -jar "
            command, file = line.split(" -jar ")
            command.replace("javaw", "java") # Ensure using java instead of javaw
            new_command = f"{command} -jar fabric-server-{version}.jar"
            with open(os.path.join(server_path, "run.bat"), 'w') as b:
                b.write(new_command)
            time.sleep(1)
        
        return True
    except Exception as e:
        print(e)
        return False

def get_api_settings(server_path, api_version=1):
    try:
        # api_version:
        # 1: first basic implementation
        # 2: 25w37a added client authorization requirement
        # 3: 1.21.9 changed the notification syntax
        with open(os.path.join(server_path, "server.properties"), "r") as f:
            lines = f.readlines()
        
        host = ""
        port = ""
        auth_token = ""
        found_enabled = False
        found_host = False
        found_port = False
        found_tls = False
        found_secret = False
        found_interval = False
        for i, line in enumerate(lines):
            if line.startswith("management-server-enabled="):
                lines[i] = "management-server-enabled=true\n"
                found_enabled = True
            elif line.startswith("management-server-host="):
                found_host = True
                host = line.strip().split("=")[1]
                if not host:
                    host = "localhost"
                    lines[i] = "management-server-host=localhost\n"
            elif line.startswith("management-server-port="):
                found_port = True
                port = line.strip().split("=")[1]
                if not port or port == "0":
                    port = "25585"
                    lines[i] = "management-server-port=25585\n"
            elif line.startswith("management-server-tls-enabled="):
                found_tls = True
                lines[i] = "management-server-tls-enabled=false\n"
            elif line.startswith("management-server-secret="):
                found_secret = True
                auth_token = line.strip().split("=")[1]
            elif line.startswith("status-heartbeat-interval="):
                found_interval = True
                lines[i] = "status-heartbeat-interval=60\n"
        
        if not found_enabled:
            lines.append("management-server-enabled=true\n")
        if not found_host:
            lines.append("management-server-host=localhost\n")
            host = "localhost"
        if not found_port:
            lines.append("management-server-port=25585\n")
            port = "25585"
        if not found_tls and api_version > 1:
            lines.append("management-server-tls-enabled=false\n")
        if not found_secret and api_version > 1:
            pass
        if not found_interval:
            lines.append("status-heartbeat-interval=60\n")
        
        with open(os.path.join(server_path, "server.properties"), "w") as f:
            f.writelines(lines)
        
        return (host, port, auth_token)
    except:
        return ("localhost", "25585", "")

def pick_folder(parent, starting_path: Path | str="", dialog_title="Open Folder"):
    # Show the file dialog for selecting a folder
    selected_folder = QFileDialog.getExistingDirectory(
        parent,                     # Parent widget
        dialog_title,              # Dialog title
        str(starting_path)               # Default directory (empty for no specific directory)
    )

    # If a folder was selected, return it's path
    if selected_folder:
        return selected_folder

def open_folder_explorer(folder_path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

def open_file(path):
    try:
        subprocess.run(['start', '', path], shell=True)
        return True
    except FileNotFoundError:
        return False

def save_world_properties(folder_path, properties: dict):
    file_path = os.path.join(folder_path, "saved_properties.properties")
    if not os.path.isfile(file_path):
        with open(file_path, 'w') as f:
            f.write("")
    
    with open(file_path, 'r') as props:
        lines = props.readlines()
    
    found_version = False
    found_gamemode = False
    found_force_gamemode = False
    found_hardcore = False
    found_difficulty = False
    found_fabric = False
    found_level_type = False
    for i, line in enumerate(lines):
        if line.startswith("version="):
            lines[i] = f"version={properties.get("version")}\n"
            found_version = True
        elif line.startswith("gamemode="):
            if properties.get("gamemode", "Survival") == "Hardcore":
                lines[i] = "gamemode=survival\n"
            else:
                lines[i] = f"gamemode={properties.get("gamemode", "Survival").lower()}\n"
            found_gamemode = True
        elif properties.get("gamemode", "Survival") == "Creative" and line.startswith("force-gamemode="):
            lines[i] = "force-gamemode=true\n"
            found_force_gamemode = True
        elif line.startswith("hardcore="):
            if properties.get("gamemode", "Survival") == "Hardcore":
                lines[i] = "hardcore=true\n"
            else:
                lines[i] = "hardcore=false\n"
            found_hardcore = True
        elif line.startswith("difficulty="):
            lines[i] = f"difficulty={properties.get("difficulty", "Easy").lower()}\n"
            found_difficulty = True
        elif line.startswith("fabric="):
            lines[i] = f"fabric={"true" if properties.get("fabric", False) else "false"}\n"
            found_fabric = True
        elif line.startswith("level-type="):
            version = properties.get("version") or "1.13"
            if version_comparison(version, "1.13", before=True):
                lines[i] = f"level-type={properties.get("level-type", "Normal").upper().replace(' ', '')}\n"
            else:
                lines[i] = f"level-type=minecraft\\:{properties.get("level-type", "Normal").lower().replace(' ', '_')}\n"
            found_level_type = True
    
    if not found_version:
        lines.append(f"version={properties.get("version")}\n")
    if not found_gamemode:
        gamemode = properties.get("gamemode", "Survival")
        if gamemode == "Hardcore":
            lines.append("gamemode=survival\n")
        else:
            lines.append(f"gamemode={gamemode.lower()}\n")
    if not found_force_gamemode and properties.get("gamemode", "Survival") == "Creative":
        lines.append("force-gamemode=true\n")
    if not found_hardcore:
        if properties.get("gamemode") == "Hardcore":
            lines.append("hardcore=true\n")
        else:
            pass
    if not found_difficulty:
        lines.append(f"difficulty={properties.get("difficulty", "Easy").lower()}\n")
    if not found_fabric:
        lines.append(f"fabric={"true" if properties.get("fabric", False) else "false"}\n")
    if not found_level_type:
        version = properties.get("version") or "1.13"
        if version_comparison(version, "1.13", before=True):
            lines.append(f"level-type={properties.get("level-type", "Normal").upper().replace(' ', '')}\n")
        else:
            lines.append(f"level-type=minecraft\\:{properties.get("level-type", "Normal").lower().replace(' ', '_')}\n")
    
    with open(file_path, 'w') as props:
        props.writelines(lines)

def load_world_properties(folder_path):
    file_path = os.path.join(folder_path, "saved_properties.properties")
    properties = {
        "version": None,
        "gamemode": "Survival",
        "difficulty": "Easy",
        "fabric": False,
        "level-type": "Normal"
    }

    if not os.path.isfile(file_path):
        if os.path.isfile(os.path.join(folder_path, "version.txt")):
            with open(os.path.join(folder_path, "version.txt"), 'r') as f:
                version = f.readline()
            properties["version"] = version
            os.remove(os.path.join(folder_path, "version.txt"))
        return properties

    with open(file_path, 'r') as props:
        lines = props.readlines()

    hardcore = False
    saved_line = ""
    for line in lines:
        if line.startswith("version="):
            properties["version"] = line.strip().split("=")[1]
        elif line.startswith("gamemode="):
            properties["gamemode"] = line.strip().split("=")[1].capitalize()
        elif line.startswith("hardcore="):
            if line.strip() == "hardcore=true":
                hardcore = True
        elif line.startswith("difficulty"):
            properties["difficulty"] = line.strip().split("=")[1].capitalize()
        elif line.startswith("fabric="):
            properties["fabric"] = (line.strip().split("=")[1] == "true")
        elif line.startswith("level-type="):
            saved_line = line
    
    if saved_line and properties.get("version"):
        if "\\:" in line:
            properties["level-type"] = line.strip().split(":")[1].capitalize().replace('_', ' ')
        else:
            level_type = line.strip().split("=")[1]
            if level_type == "LARGEBIOMES":
                properties["level-type"] = "Large Biomes"
            else:
                properties["level-type"] = level_type.capitalize()
    
    if hardcore:
        properties["gamemode"] = "Hardcore"

    return properties

def save_all_world_properties(server_path, worlds):
    for world, data in worlds.items():
        world_folder = os.path.join(server_path, "worlds", world)
        if os.path.isdir(world_folder):
            save_world_properties(world_folder, data)

def check_for_property_updates(server_folder, world, file_lock, ips, host_ip):
    props_file = os.path.join(server_folder, "worlds", world, "saved_properties.properties")

    with open(props_file, 'r') as f:
        lines = f.readlines()
    
    with open(MANAGER_SETTINGS, 'r') as settings:
        old_settings = settings.read()
    old_settings = json.loads(old_settings)
    old_props = old_settings["server folder"]["worlds"].get(world)
    old_universal = old_settings.get("universal settings")
    
    props = {}
    was_hardcore = (old_props.get("gamemode", "Survival") == "Hardcore")
    gamemode = old_props.get("gamemode", "Survival")
    difficulty = old_props.get("difficulty", "Easy")
    hardcore = "true" if gamemode == "Hardcore" else "false"
    changed = False
    for line in lines:
        if line.startswith("level-seed=") and old_props.get("seed") is not None:
            props["seed"] = line.strip().split("=")[1]
        elif line.startswith("gamemode="):
            gamemode = line.strip().split("=")[1].capitalize()
            if was_hardcore and gamemode != "Survival":
                changed = True
        elif line.startswith("hardcore="):
            hardcore = line.strip().split("=")[1]
            if (was_hardcore and hardcore != "true") or (not was_hardcore and hardcore == "true"):
                changed = True
        elif line.startswith("difficulty="):
            difficulty = line.strip().split("=")[1].capitalize()
            if was_hardcore and difficulty != "Hard":
                changed = True
        elif line.startswith("fabric="):
            props["fabric"] = True if line.strip().split("=")[1] == "true" else False
        elif line.startswith("level-type=") and old_props.get("seed") is not None:
            props["level-type"] = line.strip().split(":")[1].capitalize().replace('_', ' ')
        elif line.startswith("white-list="):
            old_universal["whitelist enabled"] = True if line.strip().split("=")[1] == "true" else False
        elif line.startswith("view-distance="):
            distance = line.strip().split("=")[1]
            if distance:
                try:
                    old_universal["view distance"] = min(32, max(3, int(distance)))
                except:
                    pass
        elif line.startswith("simulation-distance="):
            distance = line.strip().split("=")[1]
            if distance:
                try:
                    old_universal["simulation distance"] = min(32, max(3, int(distance)))
                except:
                    pass
    
    if changed:
        if not was_hardcore:
            props["gamemode"] = "Hardcore"
            props["difficulty"] = "Hard"
            gamemode = "survival"
            difficulty = "hard"
            hardcore = "true"
        else:
            props["gamemode"] = gamemode
            props["difficulty"] = difficulty
            hardcore = "false"
            gamemode = gamemode.lower()
            difficulty = difficulty.lower()
    else:
        props["gamemode"] = gamemode
        props["difficulty"] = difficulty
    
    if changed:
        for i, line in enumerate(lines):
            if line.startswith("gamemode="):
                lines[i] = f"gamemode={gamemode}\n"
            elif line.startswith("difficulty="):
                lines[i] = f"difficulty={difficulty}\n"
            elif line.startswith("hardcore="):
                lines[i] = f"hardcore={hardcore}\n"
    
    for key, value in props.items():
        old_props[key] = value
    
    worlds = old_settings["server folder"]["worlds"]
    worlds[world] = old_props
    world_order = old_settings["server folder"].get("world order", [])
    
    update_settings(file_lock, ips, server_folder, worlds, world_order, old_universal, host_ip)
    update_all_universal_settings(server_folder)
    return old_universal

def update_all_universal_settings(server_folder):
    with open(MANAGER_SETTINGS, 'r') as manager_settings:
        settings = json.loads(manager_settings.read())
    
    world_names = settings.get("server folder").get("worlds").keys()
    universals = settings.get("universal settings")
    for world in world_names:
        try:
            with open(os.path.join(server_folder, "worlds", world, "saved_properties.properties"), 'r') as props:
                lines = props.readlines()
            
            found_whitelist = False
            found_view = False
            found_simulation = False
            for i, line in enumerate(lines):
                if line.startswith("white-list="):
                    lines[i] = f"white-list={"true" if universals.get("whitelist enabled") else "false"}\n"
                    found_whitelist = True
                elif line.startswith("view-distance="):
                    lines[i] = f"view-distance={str(min(32, max(3, universals.get("view distance")))) or "10"}\n"
                    found_view = True
                elif line.startswith("simulation-distance="):
                    lines[i] = f"simulation-distance={str(min(32, max(3, universals.get("simulation distance")))) or "10"}\n"
                    found_simulation = True
            
            if not found_whitelist:
                lines.append("white-list=false\n")
            if not found_view:
                lines.append("view-distance=10\n")
            if not found_simulation:
                lines.append("simulation-distance=10\n")
            
            with open(os.path.join(server_folder, "worlds", world, "saved_properties.properties"), 'w') as props:
                props.writelines(lines)
        except:
            pass

def apply_universal_settings(server_folder):
    with open(MANAGER_SETTINGS, 'r') as settings:
        universal = json.loads(settings.read()).get("universal settings")
    
    with open(os.path.join(server_folder, "server.properties"), 'r') as f:
        lines = f.readlines()
    
    found_whitelist = False
    found_view = False
    found_simulation = False
    for i, line in enumerate(lines):
        if line.startswith("white-list="):
            lines[i] = f"white-list={"true" if universal.get("whitelist enabled") else "false"}\n"
            found_whitelist = True
        elif line.startswith("view-distance="):
            lines[i] = f"view-distance={str(min(32, max(3, universal.get("view distance")))) or "10"}\n"
            found_view = True
        elif line.startswith("simulation-distance="):
            lines[i] = f"simulation-distance={str(min(32, max(3, universal.get("simulation distance")))) or "10"}\n"
            found_simulation = True
        
    if not found_whitelist:
        lines.append("white-list=false\n")
    if not found_view:
        lines.append("view-distance=10\n")
    if not found_simulation:
        lines.append("simulation-distance=10\n")
    
    with open(os.path.join(server_folder, "server.properties"), 'w') as f:
        f.writelines(lines)

def format_size(bytes_size):
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(bytes_size)
    for unit in units:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def get_total_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total

def get_disk_space(path):
    # Needs a path to know which drive to check
    usage = shutil.disk_usage(os.path.dirname(path))
    return usage.free

def backup_world(world_folder_path, backup_zip_path, parent, progress_function=None, socket_writer=None):
    if not socket_writer:
        os.makedirs(os.path.dirname(backup_zip_path), exist_ok=True)
        # World folder size
        total_size = get_total_size(world_folder_path)
        free_bytes = get_disk_space(backup_zip_path)

        if total_size >= free_bytes:
            box = QMessageBox(parent)
            box.setWindowTitle("Low Disk Space")
            box.setText(f"Not enough disk space!<br>{os.path.basename(world_folder_path)} folder is {format_size(total_size)}.")
            box.setIcon(QMessageBox.Icon.Critical)
            box.setStandardButtons(QMessageBox.StandardButton.Close)
            box.setStyleSheet("QLabel { color: black; }")
            box.exec()
            return False

    total_files = 0
    for _, _, files in os.walk(world_folder_path):
        total_files += len(files)
    
    dialog_box = QProgressDialog(
        ("Backing up world..." if not socket_writer else "Transferring world..."),
        "Cancel",
        0,
        total_files,
        parent
    )
    dialog_box.setWindowTitle("World Backup" if not socket_writer else "World Transfer")
    dialog_box.setMinimumDuration(500)
    dialog_box.setStyleSheet("QLabel {color: black;}")
    dialog_box.setModal(True)
    
    processed = 0
    last_updated = time.time()
    try:
        with zipfile.ZipFile((socket_writer if socket_writer else backup_zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for root, _, files in os.walk(world_folder_path):
                for name in files:
                    dialog_box.setLabelText("Copying files...<br>" + name)
                    full_path = os.path.join(root, name)
                    arcname = os.path.relpath(full_path, world_folder_path)
                    try:
                        zf.write(full_path, arcname)
                    except RuntimeError:
                        dialog_box.cancel()
                    
                    QApplication.processEvents()
                    if dialog_box.wasCanceled():
                        dialog_box.setCancelButton(None)
                        dialog_box.setLabelText("Cancelling...")
                        raise RuntimeError("Backup cancelled")

                    processed += 1
                    dialog_box.setValue(processed)
                    if progress_function and time.time() - last_updated >= 0.1:
                        last_updated = time.time()
                        progress_function(processed, name)
        
        if socket_writer:
            socket_writer.end_transfer()
        return True
    except RuntimeError:
        if not socket_writer and os.path.exists(backup_zip_path):
            os.remove(backup_zip_path)
        
        return False
    except Exception as e:
        print("File exception")
        print(e)
