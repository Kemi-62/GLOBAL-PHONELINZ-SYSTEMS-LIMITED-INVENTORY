import os
from PIL import Image, ImageDraw, ImageFont
sizes = [72,96,128,144,152,192,384,512]
os.makedirs("static/icons", exist_ok=True)
for s in sizes:
    img = Image.new("RGB", (s,s), color="#004F9F")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", s//4)
    except:
        font = ImageFont.load_default()
    text = "GPSL"
    bbox = draw.textbbox((0,0), text, font=font)
    x = (s-(bbox[2]-bbox[0]))//2
    y = (s-(bbox[3]-bbox[1]))//2
    draw.text((x,y), text, fill="#FFCB05", font=font)
    img.save(f"static/icons/icon-{s}.png")
    print(f"icon-{s}.png created")
print("All icons done")
