"""Create simple placeholder icons for Teams app."""
from PIL import Image, ImageDraw

# Color icon (192x192)
color = Image.new('RGB', (192, 192), color='#5558AF')
draw = ImageDraw.Draw(color)
draw.ellipse([40, 40, 152, 152], fill='white')
draw.text((75, 80), 'C', fill='#5558AF')
color.save('color.png')

# Outline icon (32x32)
outline = Image.new('RGBA', (32, 32), color=(0, 0, 0, 0))
draw = ImageDraw.Draw(outline)
draw.ellipse([2, 2, 30, 30], outline='#5558AF', width=2)
draw.text((11, 7), 'C', fill='#5558AF')
outline.save('outline.png')

print("Icons created: color.png (192x192), outline.png (32x32)")
