import json
import os

def load_settings(default_ip, log_queue, file_lock):
    data = {"ip": f"{default_ip}", "names": {}, "worlds": {}}
    try:
        with open("manager_settings.json", 'r') as f:
            data = json.load(f)
    except:
        with open("manager_settings.json", 'w') as f:
            json.dump(data, f, indent=4)
        log_queue.put("Settings file not found.")
        log_queue.put("Created new manager_settings.json file.")
        return default_ip, {}, {}
    
    host_ip = data.get("ip")
    ips = data.get("names")
    world_paths = data.get("worlds")
    if world_paths is not None:
        world_paths = load_worlds(world_paths, log_queue)
    else:
        world_paths = {}
        log_queue.put(f"<font color='red'>Unable to find worlds in the settings.</font>")
    
    if host_ip is None or ips is None:
        if ips is None:
            ips = {}
        if host_ip is None:
            host_ip = default_ip
        update_names(file_lock, host_ip, ips, world_paths)
    
    return host_ip, ips, world_paths

def load_worlds(world_paths, log_queue):
    worlds_to_ignore = []
    for world, path in world_paths.items():
        # Check batch file exists
        if not os.path.isfile(path):
            log_queue.put(f"<font color='red'>ERROR: Unable to find file '{path}'.</font>")
            worlds_to_ignore.append(world)
            continue
        else:
            # Make sure the command uses javaw instead of java
            try:
                with open(path, 'r') as batch_file:
                    command = batch_file.read()
                
                new_command = command.replace("java ", "javaw ")
                if command != new_command:
                    with open(path, 'w') as batch_file:
                        batch_file.write(new_command)
            except:
                log_queue.put(f"<font color='red'>ERROR: Unable to inspect batch file at {path}.</font>")
                worlds_to_ignore.append(world)

        directory = os.path.dirname(path)
        world_folder_path = f"{directory}\\{world}"
        properties_path = f"{directory}\\server.properties"
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
                    elif line.startswith("level-name="):
                        compare = f"level-name={world}\n"
                        if line != compare:
                            other_world_name = line.split('=')[1].strip()
                            other_world_folder = f"{directory}\\{other_world_name}"
                            if os.path.isdir(world_folder_path):
                                # Will switch to reference this folder
                                pass
                            elif os.path.isdir(other_world_folder):
                                try:
                                    os.rename(other_world_folder, world_folder_path)
                                except:
                                    log_queue.put(f"<font color='red'>ERROR: Unable to rename world folder '{other_world_name}' to '{world}'.</font>")
                                    if not os.path.isdir(world_folder_path):
                                        worlds_to_ignore.append(world)
                        else:
                            if not os.path.isdir(world_folder_path):
                                log_queue.put(f"<font color='red'>ERROR: Unable to find '{world}' folder at '{directory}'.</font>")
                                worlds_to_ignore.append(world)
                    
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
                log_queue.put(f"<font color='orange'>WARNING: Was unable to check if '{path}' has query enabled \
                                    while server.properties is being accessed.</font>")
        else:
            log_queue.put(f"<font color='orange'>WARNING: Unable to find 'server.properties' in folder at '{directory}'. \
                                Make sure the server's .bat file is placed in the server folder.</font>")
    
    for world in worlds_to_ignore:
        world_paths.pop(world)
    
    return world_paths

def update_names(file_lock, host_ip, ips, world_paths):
    with file_lock:
        with open("manager_settings.json", 'w') as f:
            json.dump({"ip":host_ip, "names":ips, "worlds":world_paths}, f, indent=4)