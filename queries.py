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

def download_server_jar(version, output_directory, log_queue):
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
        server_jar_url = server_json_response["downloads"]["server"]["url"]
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

