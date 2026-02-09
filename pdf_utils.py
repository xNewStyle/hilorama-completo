import os

def draw_marca_agua(c, ruta_logo, width, height, alpha=0.06):
    if not ruta_logo or not os.path.exists(ruta_logo):
        return

    c.saveState()

    try:
        c.setFillAlpha(alpha)
    except:
        pass  # versiones viejas de reportlab

    logo_width = width * 0.7
    logo_height = logo_width * 0.4

    x = (width - logo_width) / 2
    y = (height - logo_height) / 2

    c.drawImage(
        ruta_logo,
        x,
        y,
        width=logo_width,
        height=logo_height,
        preserveAspectRatio=True,
        mask="auto"
    )

    c.restoreState()
