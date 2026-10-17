"""Convention v360 e->flat, roll=0, rorder=ypr; coordonnées sur bords de pixels.

u=x/W, v=y/H (origine haut-gauche), centre du pixel i : (i+0.5)/W.
Yaw positif vers la droite du panorama; pitch positif vers le haut.
"""
import math
import numpy as np


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Nombre fini attendu.')
    return float(value)


def wrap_yaw(yaw):
    return (finite(yaw) + 180) % 360 - 180


def uv_to_angles(u, v):
    u, v = finite(u), finite(v)
    if not 0 <= v <= 1:
        raise ValueError('v doit appartenir à [0,1].')
    return wrap_yaw(360 * (u % 1) - 180), 90 - 180 * v


def angles_to_uv(yaw, pitch):
    pitch = finite(pitch)
    if not -90 <= pitch <= 90:
        raise ValueError('Pitch hors limites.')
    return ((wrap_yaw(yaw) + 180) / 360) % 1, (90 - pitch) / 180


def camera_matrix(yaw, pitch):
    y, p = math.radians(yaw), math.radians(pitch)
    cy, sy, cp, sp = math.cos(y), math.sin(y), math.cos(p), math.sin(p)
    # Ry(yaw) @ Rx(pitch), coordonnées monde x droite, y bas, z avant.
    return np.array([[cy, sy * sp, sy * cp], [0, cp, -sp], [-sy, cy * sp, cy * cp]])


def uv_vectors(u, v):
    longitude = (np.asarray(u) - .5) * (2 * np.pi)
    latitude = (np.asarray(v) - .5) * np.pi
    return np.stack([np.cos(latitude) * np.sin(longitude), np.sin(latitude),
                     np.cos(latitude) * np.cos(longitude)], axis=-1)


def normalized_box(a, b):
    """Arc horizontal le plus court; un rectangle peut traverser u=0/1.
    Pour une zone >180°, sélectionner des sous-zones: projection plate limitée.
    """
    u0, v0 = finite(a[0]) % 1, finite(a[1])
    u1, v1 = finite(b[0]) % 1, finite(b[1])
    if not (0 <= v0 <= 1 and 0 <= v1 <= 1):
        raise ValueError('Boîte hors panorama.')
    delta = (u1 - u0 + .5) % 1 - .5
    start = (u0 + min(0, delta)) % 1
    span = abs(delta)
    return {'u_start': start, 'u_span': span, 'v_top': min(v0, v1),
            'v_bottom': max(v0, v1), 'wraps_seam': start + span > 1}


def box_framing(box, aspect=16 / 9, margin=1.12):
    """FOV géométrique suggéré à partir d'une zone manuelle, sans inférence IA.
    Échantillonne la grille de la zone sphérique puis ajuste une caméra plate.
    """
    u = (box['u_start'] + box['u_span'] / 2) % 1
    v = (box['v_top'] + box['v_bottom']) / 2
    yaw, pitch = uv_to_angles(u, v)
    us, vs = np.meshgrid(np.linspace(box['u_start'], box['u_start'] + box['u_span'], 33),
                         np.linspace(box['v_top'], box['v_bottom'], 33))
    local = uv_vectors(us, vs) @ camera_matrix(yaw, pitch)
    if np.any(local[..., 2] <= 1e-6):
        return yaw, pitch, 160., False
    tangents = local[..., :2] / local[..., 2:3]
    extent = max(np.abs(tangents[..., 0]).max(), np.abs(tangents[..., 1]).max() * aspect) * margin
    required = math.degrees(2 * math.atan(extent))
    return yaw, pitch, min(160., max(10., required)), required <= 160


def preview_rgb(panorama, yaw, pitch, h_fov, width=480, height=270):
    """Projection bilinéaire NumPy en mémoire; longitude cyclique, latitude bornée."""
    if not 10 <= finite(h_fov) <= 160:
        raise ValueError('FOV horizontal entre 10 et 160 degrés.')
    angles_to_uv(yaw, pitch)  # validation
    scale = math.tan(math.radians(h_fov) / 2)
    xx, yy = np.meshgrid(((np.arange(width) + .5) * 2 / width - 1) * scale,
                         ((np.arange(height) + .5) * 2 / height - 1) * scale * height / width)
    rays = np.stack([xx, yy, np.ones_like(xx)], axis=-1) @ camera_matrix(yaw, pitch).T
    rays /= np.linalg.norm(rays, axis=-1, keepdims=True)
    lon = np.arctan2(rays[..., 0], rays[..., 2])
    lat = np.arcsin(np.clip(rays[..., 1], -1, 1))
    h, w = panorama.shape[:2]
    x = (lon / (2 * np.pi) + .5) * w - .5
    y = np.clip((lat / np.pi + .5) * h - .5, 0, h - 1)
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    dx, dy = (x - ix)[..., None], (y - iy)[..., None]
    x0, x1, y1 = ix % w, (ix + 1) % w, np.minimum(iy + 1, h - 1)
    rgb = ((1 - dx) * (1 - dy) * panorama[iy, x0] + dx * (1 - dy) * panorama[iy, x1]
           + (1 - dx) * dy * panorama[y1, x0] + dx * dy * panorama[y1, x1])
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
