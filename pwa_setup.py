offline_html = '''{% extends "base.html" %}
{% block content %}
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;text-align:center;padding:2rem;">
  <div style="font-size:4rem;margin-bottom:1rem;">📵</div>
  <h1 style="font-size:1.5rem;font-weight:700;color:#004F9F;margin:0 0 .8rem;">You are offline</h1>
  <p style="color:#6b7280;max-width:320px;line-height:1.6;margin:0 0 1.5rem;">
    No internet connection detected. Please check your network and try again.
  </p>
  <button onclick="window.location.reload()"
          style="padding:.7rem 1.5rem;background:#004F9F;color:#fff;border:none;border-radius:8px;font-weight:600;font-size:.9rem;cursor:pointer;">
    Try Again
  </button>
  <p style="font-size:.78rem;color:#9ca3af;margin-top:1rem;">
    GPSL ERP — Global Phonelinz Systems Ltd
  </p>
</div>
{% endblock %}'''

icon_script = '''"""
Generate PWA icons using Pillow.
Run once: python generate_icons.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

sizes = [72, 96, 128, 144, 152, 192, 384, 512]
output_dir = "static/icons"
os.makedirs(output_dir, exist_ok=True)

for size in sizes:
    img = Image.new("RGB", (size, size), color="#004F9F")
    draw = ImageDraw.Draw(img)
    
    # Draw GPSL text centered
    font_size = size // 4
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    text = "GPSL"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2
    y = (size - text_h) // 2
    
    # Yellow text
    draw.text((x, y), text, fill="#FFCB05", font=font)
    
    img.save(f"{output_dir}/icon-{size}.png")
    print(f"Created icon-{size}.png")

print("All icons generated in static/icons/")
'''

# Write offline.html template
with open('/home/claude/offline.html', 'w') as f:
    f.write(offline_html)
print("offline.html created")

# Write icon generator
with open('/home/claude/generate_icons.py', 'w') as f:
    f.write(icon_script)
print("generate_icons.py created")
