Add-Type -AssemblyName System.Drawing

$sourcePath = "C:\Users\JoelBentley\Downloads\Gemini_Generated_Image_1yy9ep1yy9ep1yy9.png"
$colorPath = "C:\Projects\n8n Call Notes\teams-app\color.png"
$outlinePath = "C:\Projects\n8n Call Notes\teams-app\outline.png"

$img = [System.Drawing.Image]::FromFile($sourcePath)

# Create 192x192 color icon
$color = New-Object System.Drawing.Bitmap(192, 192)
$graphics = [System.Drawing.Graphics]::FromImage($color)
$graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$graphics.DrawImage($img, 0, 0, 192, 192)
$color.Save($colorPath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$color.Dispose()

# Create 32x32 outline icon
$outline = New-Object System.Drawing.Bitmap(32, 32)
$graphics2 = [System.Drawing.Graphics]::FromImage($outline)
$graphics2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$graphics2.DrawImage($img, 0, 0, 32, 32)
$outline.Save($outlinePath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics2.Dispose()
$outline.Dispose()

$img.Dispose()

Write-Host "Icons created successfully!"
Write-Host "color.png: 192x192"
Write-Host "outline.png: 32x32"
