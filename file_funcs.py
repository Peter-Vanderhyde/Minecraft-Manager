import json
import os
import shutil
import queries
import time
import glob

def load_settings(default_ip, log_queue, file_lock):
    data = {
        "ip": f"{default_ip}",
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
        return default_ip, {}, "", {}
    
    host_ip = data.get("ip")
    ips = data.get("names")
    server_path = data["server folder"].get("path")
    worlds = data["server folder"].get("worlds")
    # Check batch file exists
    if not os.path.isfile(os.path.join(server_path, "run.bat")):
        log_queue.put(f"<font color='red'>ERROR: Unable to find .bat file at '{server_path}'.</font>")
        worlds = {}
    
    if worlds is not None:
        worlds = load_worlds(server_path, worlds, log_queue)
    else:
        worlds = {}
        log_queue.put(f"<font color='red'>Missing worlds key in the settings.</font>")
    
    if host_ip is None or ips is None:
        if ips is None:
            ips = {}
        if host_ip is None:
            host_ip = default_ip
        update_names(file_lock, host_ip, ips, server_path, worlds)
    
    return host_ip, ips, server_path, worlds

def load_worlds(server_path, worlds, log_queue):
    # Add worlds folder if not already present
    if not os.path.isdir(os.path.join(server_path, "worlds")):
        try:
            if not os.path.isdir(server_path):
                return []
            os.mkdir(os.path.join(server_path, "worlds"))
        except:
            return []
    
    worlds_to_ignore = []
    batch_path = os.path.join(server_path, "run.bat")
    # Make sure the command uses javaw instead of java
    try:
        with open(batch_path, 'r') as batch_file:
            command = batch_file.read()
        
        new_command = command.replace("java ", "javaw ")
        if command != new_command:
            with open(batch_path, 'w') as batch_file:
                batch_file.write(new_command)
    except:
        log_queue.put(f"<font color='red'>ERROR: Unable to inspect batch file at {batch_path}.</font>")
        return {}

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
        log_queue.put(f"<font color='orange'>WARNING: Unable to find 'server.properties' in folder at '{directory}'.</font>")
    
    for world, data in worlds.items():
        directory = os.path.join(server_path, "worlds")
        world_folder_path = os.path.join(directory, world)
        if not os.path.isdir(world_folder_path):
            log_queue.put(f"<font color='red'>ERROR: Unable to find the '{world}' world folder.</font>")
            worlds_to_ignore.append(world)
    
    for world in worlds_to_ignore:
        worlds.pop(world)
    
    return worlds

def update_names(file_lock, host_ip, ips, server_path, worlds):
    with file_lock:
        with open("manager_settings.json", 'w') as f:
            json.dump({"ip": host_ip, "names": ips, "server folder": {"path": server_path, "worlds": worlds}}, f, indent=4)

def prepare_server_settings(world, version, fabric, server_path, log_queue):
    # Change the properties
    # try:
    with open(os.path.join(server_path, "server.properties"), 'r') as properties:
        lines = properties.readlines()
    
    for i, line in enumerate(lines):
        if line.startswith("level-name="):
            lines[i] = f"level-name=worlds/{world}\n"
    
    with open(os.path.join(server_path, "server.properties"), 'w') as properties:
        properties.writelines(lines)
    
    # TODO Change the .jar
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
    with open(os.path.join(server_path, "run.bat"), 'r') as b:
        line = b.read()
    command, file = line.split(" -jar ")
    new_command = f"{command} -jar {new_name}"
    with open(os.path.join(server_path, "run.bat"), 'w') as b:
        b.write(new_command)
    time.sleep(1)
    
    return True
    # except:
    #     return False