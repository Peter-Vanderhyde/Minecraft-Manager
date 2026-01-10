import os
import requests
import uuid
from mcstatus import JavaServer

def status(ip, port):
    try:
        query = JavaServer.lookup(f"{ip}:{port}", 1).query()
        return "online", query.software.brand, query.software.version, query.map
    except:
        return "offline", "", "", ""

def players(ip, port):
    try:
        query = JavaServer.lookup(f"{ip}:{port}", 1).query()
        return query.players.names
    except (TimeoutError, ConnectionResetError):
        return []

def get_json(version, log_queue):
    version_url = f'https://launchermeta.mojang.com/mc/game/version_manifest.json'

    # Fetch the version manifest
    try:
        response = requests.get(version_url)
    except:
        log_queue.put(f"Failed to download necessary jar file.")
        raise RuntimeError("Failed to download jar file.")
    if response.status_code == 200:
        manifest = response.json()
        version_info = next(v for v in manifest['versions'] if v['id'] == version)

        # Get the download URL for the server JAR
        server_json_url = version_info['url']
        server_json_response = requests.get(server_json_url).json()
        return True, server_json_response
    return False, response

def download_server_jar(version, output_directory, log_queue):
    success, response = get_json(version, log_queue)
    if success:
        try:
            server_jar_url = response["downloads"]["server"]["url"]
            server_jar_response = requests.get(server_jar_url)
        except:
            log_queue.put(f"Failed to download server JAR.")
            sections = version.split(".")
            if int(sections[1]) > 2:
                return False
            elif len(sections) > 2 and int(sections[2]) >= 5:
                return False
            log_queue.put("Minecraft only supports servers from version 1.2.5 and later.")
            return False
        
        if server_jar_response.status_code == 200:
            # Save the server JAR to the specified directory
            output_path = os.path.join(output_directory, f'server-{version}.jar')
            with open(output_path, 'wb') as file:
                file.write(server_jar_response.content)
            return True
            # log_queue.put(f"Server JAR for version {version} downloaded to {output_path}")
        else:
            log_queue.put(f"Failed to download server JAR. Status code: {server_jar_response.status_code}")
            return False
    else:
        log_queue.put(f"Failed to fetch version manifest. Status code: {response.status_code}")
        return False

def get_latest_release(log_queue):
    version_url = 'https://launchermeta.mojang.com/mc/game/version_manifest.json'

    # Fetch the version manifest
    try:
        response = requests.get(version_url)
    except:
        log_queue.put(f"Failed to download necessary jar file.")
        return False
    
    if response.status_code == 200:
        manifest = response.json()
        latest_version = manifest["latest"]["release"]
        return latest_version

def download_latest_server_jar(server_path, log_queue):
    latest_version = get_latest_release(log_queue)
    if not latest_version:
        return False

    download_server_jar(latest_version, server_path, log_queue)
    return latest_version

def get_required_java_version(version, log_queue):
    if "." in version:
        version_segments = version.split(".")
        if int(version_segments[0]) == 1 and int(version_segments[1]) < 7:
            return 8
    success, response = get_json(version, log_queue)
    if success:
        required_version = response["javaVersion"]["majorVersion"]
        return required_version
    else:
        log_queue.put(f"Failed to fetch required Java version. Status code: {response.status_code}")

def download_fabric_server_jar(version, server_path, log_queue):
    loader_versions_url = f'https://meta.fabricmc.net/v2/versions/loader'
    installer_versions_url = f'https://meta.fabricmc.net/v2/versions/installer'

    # Fetch the version manifest
    try:
        loader_response = requests.get(loader_versions_url)
        installer_response = requests.get(installer_versions_url)

        if loader_response.status_code == 200 and installer_response.status_code == 200:
            loader_versions = loader_response.json()
            installer_versions = installer_response.json()

            mc_version = version
            loader_version = loader_versions[0]["version"]
            installer_version = installer_versions[0]["version"]

            jar_url = f'https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/{installer_version}/server/jar'

            jar_response = requests.get(jar_url)
            if jar_response.status_code == 200:
                output_path = os.path.join(server_path, f"fabric-server-{mc_version}.jar")
                with open(output_path, 'wb') as file:
                    file.write(jar_response.content)

                return True
            else:
                raise RuntimeError("Unable to download")
        else:
            raise RuntimeError("Unable to download")
    except:
        log_queue.put(f"Failed to download necessary jar file.")
        return False

def verify_fabric_version(version):
    game_versions_url = 'https://meta.fabricmc.net/v2/versions/game'
    try:
        response = requests.get(game_versions_url)
    except:
        return None
    
    if response.status_code == 200:
        versions = response.json()
        found_version = False
        for version_object in versions:
            if version_object["version"] == version:
                found_version = True
        
        if found_version:
            return True
    
    return False

def get_mc_versions(include_snapshots=False):
    versions_url = 'https://launchermeta.mojang.com/mc/game/version_manifest.json'
    try:
        response = requests.get(versions_url)
    except:
        return None
    
    def supported_version(version: dict, allow_snapshots=True):
        if version["type"] == "old_beta":
            return False
        
        elif version["type"] == "snapshot" and allow_snapshots:
            return True
        
        elif version["type"] == "release":
            sections = version["id"].split(".")
            if len(sections) == 2 and int(sections[1]) <= 2:
                return False
            elif len(sections) == 3 and int(sections[1]) == 2 and int(sections[2]) <= 4:
                return False

            return True

        return False
    
    if response.status_code == 200:
        versions = response.json()["versions"]
        versions = [version["id"] for version in versions if supported_version(version, allow_snapshots=include_snapshots)]
        return versions
    else:
        return None

def version_comparison(version, test_version, before=False, after=False, equal=False):
    versions = get_mc_versions(include_snapshots=True)
    if versions[0] == test_version and after:
        return False
    
    v_index = versions.index(version)
    test_index = versions.index(test_version)
    if v_index == test_index and equal:
        return True
    elif v_index > test_index and before:
        return True
    elif v_index < test_index and after:
        return True
    else:
        return False

def get_player_uuid(name):
    url = "https://api.minecraftservices.com/minecraft/profile/lookup/name/" + name
    try:
        response = requests.get(url)
    except:
        return False
    
    if response.status_code == 200:
        obj: dict = response.json()
        obj["id"] = str(uuid.UUID(obj.get("id")))
        return obj

    return False

def check_for_newer_app_version(curr_ver):
    try:
        response = requests.get("https://api.github.com/repos/Peter-Vanderhyde/Minecraft-Manager/releases/latest")
    except:
        return False, {}
    
    if response.status_code == 200:
        content = response.json()
        latest_ver = content["tag_name"]
        if curr_ver != latest_ver:
            return content["name"], content
        
    return False, {}