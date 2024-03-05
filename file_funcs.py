import json
import os
import shutil
import queries
import time
import glob
import subprocess
from PyQt6.QtWidgets import QFileDialog
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

def load_settings(log_queue, file_lock):
    data = {
        "ip": f"",
        "names": {},
        "server folder": {
            "path": "",
            "worlds": {}
        }
    }
    try:
        with open("manager_settings.json", 'r') as f:
            data = json.load(f)
    except:
        with open("manager_settings.json", 'w') as f:
            json.dump(data, f, indent=4)
        log_queue.put("Settings file not found.")
        log_queue.put("Created new manager_settings.json file.")
        return "", {}, "", {}
    
    host_ip = data.get("ip")
    ips = data.get("names")
    server_path = data["server folder"].get("path")
    worlds = data["server folder"].get("worlds")
    
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
        update_settings(file_lock, ips, server_path, worlds, ip=host_ip)
    
    return host_ip, ips, server_path, worlds

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

    properties_path = os.path.join(server_path, "server.properties")
    # Look for server properties file
    if os.path.isfile(properties_path):
        try:
            with open(properties_path, 'r') as f:
                lines = f.readlines()
            
            # Make sure the properties are correctly set up for queries
            edited = False
            found_query = False
            found_port = False
            for i, line in enumerate(lines):
                compare = None
                if line.startswith("enable-query="):
                    found_query = True
                    compare = "enable-query=true\n"
                elif line.startswith("query.port="):
                    found_port = True
                    compare = "query.port=25565\n"
                
                if compare and line != compare:
                    lines[i] = compare
                    edited = True
            
            if not found_query:
                lines.append("\nenable-query=true")
                edited = True
            if not found_port:
                lines.append("\nquery.port=25565")
                edited = True
            
            if edited:
                with open(properties_path, 'w') as f:
                    f.writelines(lines)
        except IOError:
            log_queue.put(f"<font color='orange'>WARNING: Was unable to check if server.properties has query enabled.</font>")
    else:
        log_queue.put(f"<font color='orange'>WARNING: Unable to find 'server.properties' in folder at '{server_path}'.</font>")
    
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
    
    save_world_versions(server_path, worlds)
    
    return worlds

def update_settings(file_lock, ips, server_path, worlds, ip=""):
    with file_lock:
        with open("manager_settings.json", 'w') as f:
            json.dump({"ip": ip, "names": ips, "server folder": {"path": server_path, "worlds": worlds}}, f, indent=4)
    save_world_versions(server_path, worlds)

def prepare_server_settings(world, version, fabric, server_path, log_queue, seed=None):
    # Change the properties
    try:
        with open(os.path.join(server_path, "eula.txt"), 'r') as f:
            content = f.read()
        if "eula=false" in content:
            log_queue.put("<font color='orange'>WARNING: The EULA has not been accepted yet! Please open eula.txt.</font>")
            return False
        
        with open(os.path.join(server_path, "server.properties"), 'r') as properties:
            lines = properties.readlines()
        
        for i, line in enumerate(lines):
            if line.startswith("level-name="):
                lines[i] = f"level-name=worlds/{world}\n"
            elif line.startswith("level-seed="):
                if seed is not None:
                    lines[i] = f"level-seed={seed}\n"
                else:
                    lines[i] = f"level-seed=\n"
        
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
            
            queries.download_server_jar(version, os.path.join(server_path, "versions", version), log_queue)
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
                line = "javaw -jar "
            command, previous_file = line.split(" -jar ")
            command.replace("java", "javaw") # Ensure using javaw instead of java
            new_command = f"{command or 'javaw'} -jar {new_name}"
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
                line = "javaw -jar "
            command, file = line.split(" -jar ")
            command.replace("java", "javaw") # Ensure using javaw instead of java
            new_command = f"{command} -jar fabric-server-{version}.jar"
            with open(os.path.join(server_path, "run.bat"), 'w') as b:
                b.write(new_command)
            time.sleep(1)
        
        return True
    except:
        return False

def pick_folder(parent, starting_path=""):
    # Show the file dialog for selecting a folder
    selected_folder = QFileDialog.getExistingDirectory(
        parent,                     # Parent widget
        "Open Folder",              # Dialog title
        starting_path               # Default directory (empty for no specific directory)
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

def save_version(folder_path, version):
    try:
        with open(os.path.join(folder_path, "version.txt"), 'w') as f:
            f.write(version)
    except:
        pass

def load_version(folder_path):
    try:
        with open(os.path.join(folder_path, "version.txt"), 'r') as f:
            line = f.readline()
        
        return line.strip()
    except FileNotFoundError:
        return None

def save_world_versions(server_path, worlds):
    for world, data in worlds.items():
        world_folder = os.path.join(server_path, "worlds", world)
        if os.path.isdir(world_folder) and data.get("version"):
            save_version(world_folder, data.get("version"))