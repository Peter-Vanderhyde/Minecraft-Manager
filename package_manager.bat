@echo off

rmdir /s /q "dist"

pyinstaller --onedir --noconsole ^
    --name Minecraft_Manager ^
    --icon=Images\app_icon.ico ^
    manager.py

echo Cleaning up.
rmdir /s /q "build"
del "Minecraft_Manager.spec"

mkdir "dist\Minecraft_Manager\Images"
mkdir "dist\Minecraft_Manager\Styles"
copy "Images\block_background.png" "dist\Minecraft_Manager\Images\"
copy "Images\app_icon.ico" "dist\Minecraft_Manager\Images\"
copy "Styles\manager_host_style.css" "dist\Minecraft_Manager\Styles\"
copy "Styles\manager_style.css" "dist\Minecraft_Manager\Styles\"
copy "README.md" "dist\Minecraft_Manager\"
copy "LICENSE" "dist\Minecraft_Manager\"

echo Build complete.