# make_icon.py
from PIL import Image
sizes = [16,24,32,48,64,128,256]
img = Image.open("Images/app_icon.png").convert("RGBA")
img.save("Images/app_icon.ico", sizes=[(s, s) for s in sizes])
