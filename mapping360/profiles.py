"""Output and lens contracts shared by the GUI, NumPy renderer and FFmpeg.

Names inspired by Studio are approximations, not proprietary implementations.
FOV is measured across the horizontal centre line. All pixels are square.
"""
import math
from .geometry import finite

FORMATS = {'16:9': (1920, 1080), '9:16': (1080, 1920),
           '4:3': (1440, 1080), '3:4': (1080, 1440),
           '1:1': (1080, 1080), '2.35:1': (1880, 800)}
MODES = {
    'Linear': {'ffmpeg': 'flat', 'default_fov': 90, 'max_fov': 160},
    'Dewarp': {'ffmpeg': 'cylindrical', 'default_fov': 110, 'max_fov': 200},
    'Ultra': {'ffmpeg': 'sg', 'default_fov': 130, 'max_fov': 240},
    'Mega': {'ffmpeg': 'fisheye', 'default_fov': 150, 'max_fov': 240},
}
PREVIEW_EDGES = {'Rapide': 480, 'Équilibré': 720, 'Détaillé': 960}


def output_format(name='16:9', width=None, height=None):
    if name not in FORMATS:
        raise ValueError('Format inconnu.')
    if (width is None) != (height is None):
        raise ValueError('Fournir largeur ET hauteur.')
    width, height = FORMATS[name] if width is None else (width, height)
    if any(type(v) is not int or v < 64 or v > 4096 or v % 2 for v in (width, height)):
        raise ValueError('Dimensions entières paires entre 64 et 4096 requises.')
    rw, rh = FORMATS[name]
    if width * rh != height * rw:
        raise ValueError('La résolution doit respecter exactement le ratio sélectionné.')
    return {'format': name, 'width': width, 'height': height}


def output_for_size(width, height):
    for name, (w, h) in FORMATS.items():
        if width * h == height * w:
            return output_format(name, width, height)
    raise ValueError('Ratio non pris en charge.')


def preview_size(output, edge=720):
    """Integer dimensions with exactly the same ratio, including 47:20."""
    w, h = output['width'], output['height']
    d = math.gcd(w, h)
    a, b = w // d, h // d
    factor = max(1, int(edge) // max(a, b))
    return a * factor, b * factor


def lens_scale(mode, fov):
    angle = math.radians(fov)
    if mode == 'Linear':
        return math.tan(angle / 2)
    if mode == 'Ultra':
        return math.tan(angle / 4)
    return angle / 2


def scale_fov(mode, scale):
    if mode == 'Linear':
        return math.degrees(2 * math.atan(scale))
    if mode == 'Ultra':
        return math.degrees(4 * math.atan(scale))
    return math.degrees(2 * scale)


def max_fov(mode, aspect):
    if mode not in MODES:
        raise ValueError('Projection inconnue.')
    limit = MODES[mode]['max_fov']
    if mode == 'Mega':
        # Keep all corner rays below 150 degrees from the forward axis.
        limit = min(limit, 300 / math.sqrt(1 + 1 / aspect ** 2))
    return limit


def vertical_fov(mode, horizontal, aspect):
    if mode not in MODES or not 10 <= finite(horizontal) <= max_fov(mode, aspect) + 1e-8:
        raise ValueError('FOV hors limites pour cette projection et ce ratio.')
    scale = lens_scale(mode, horizontal) / aspect
    return math.degrees(2 * math.atan(scale)) if mode == 'Dewarp' else scale_fov(mode, scale)


def camera_output(camera):
    return camera.get('output', output_format('16:9', 1280, 720))


def projection_filter(camera, width, height):
    mode = camera.get('projection', {}).get('mode', 'Linear')
    vfov = vertical_fov(mode, camera['h_fov'], width / height)
    return (f"v360=input=e:output={MODES[mode]['ffmpeg']}:in_stereo=2d:out_stereo=2d:"
            f"w={width}:h={height}:yaw={camera['yaw']}:pitch={camera['pitch']}:"
            f"roll={camera.get('roll', 0)}:rorder=ypr:h_fov={camera['h_fov']}:"
            f"v_fov={vfov:.8f}:interp=linear,setsar=1")
