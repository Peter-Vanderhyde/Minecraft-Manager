import os
import requests
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
    except TimeoutError:
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
        server_jar_url = response["downloads"]["server"]["url"]
        server_jar_response = requests.get(server_jar_url)
        
        if server_jar_response.status_code == 200:
            # Save the server JAR to the specified directory
            output_path = os.path.join(output_directory, f'server-{version}.jar')
            with open(output_path, 'wb') as file:
                file.write(server_jar_response.content)
            # log_queue.put(f"Server JAR for version {version} downloaded to {output_path}")
        else:
            log_queue.put(f"Failed to download server JAR. Status code: {server_jar_response.status_code}")
    else:
        log_queue.put(f"Failed to fetch version manifest. Status code: {response.status_code}")

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
        if int(version.split(".")[1]) < 7:
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
    
    if response.status_code == 200:
        versions = response.json()["versions"]
        if include_snapshots:
            versions = [version["id"] for version in versions]
        else:
            versions = [version["id"] for version in versions if version["type"] == "release"]
        return versions
    else:
        return None