"""Pure NumPy B.1 projection, no FFmpeg process on interactive gestures."""
from functools import lru_cache
import numpy as np
from .geometry import camera_matrix, angles_to_uv, uv_vectors, finite
from .profiles import lens_scale, vertical_fov, camera_output


def rotation(yaw, pitch, roll=0):
    angles_to_uv(yaw, pitch)
    if not -180 <= finite(roll) <= 180:
        raise ValueError('Roll hors limites.')
    r = np.deg2rad(roll)
    c, s = np.cos(r), np.sin(r)
    return camera_matrix(yaw, pitch) @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


@lru_cache(maxsize=4)
def grid(width, height):
    x, y = np.meshgrid((np.arange(width, dtype=np.float32) + .5) * 2 / width - 1,
                       (np.arange(height, dtype=np.float32) + .5) * 2 / height - 1)
    x.flags.writeable = y.flags.writeable = False
    return x, y


def rays(camera, width, height):
    mode = camera.get('projection', {}).get('mode', 'Linear')
    vertical_fov(mode, camera['h_fov'], width / height)
    gx, gy = grid(width, height)
    scale = lens_scale(mode, camera['h_fov'])
    x, y = gx * scale, gy * scale * height / width
    if mode == 'Linear':
        local = np.stack([x, y, np.ones_like(x)], axis=-1)
    elif mode == 'Dewarp':
        local = np.stack([np.sin(x), y, np.cos(x)], axis=-1)
    else:
        radius = np.hypot(x, y)
        theta = 2 * np.arctan(radius) if mode == 'Ultra' else radius
        factor = np.divide(np.sin(theta), radius, out=np.ones_like(radius), where=radius > 0)
        local = np.stack([x * factor, y * factor, np.cos(theta)], axis=-1)
    world = local @ rotation(camera['yaw'], camera['pitch'], camera.get('roll', 0)).T.astype(np.float32)
    world /= np.linalg.norm(world, axis=-1, keepdims=True)
    return world


def render_preview(panorama, camera, width, height):
    world = rays(camera, width, height)
    lon = np.arctan2(world[..., 0], world[..., 2])
    lat = np.arcsin(np.clip(world[..., 1], -1, 1))
    h, w = panorama.shape[:2]
    x = (lon / (2 * np.pi) + .5) * w - .5
    y = np.clip((lat / np.pi + .5) * h - .5, 0, h - 1)
    ix, iy = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
    dx, dy = (x - ix).astype(np.float32)[..., None], (y - iy).astype(np.float32)[..., None]
    x0, x1, y1 = ix % w, (ix + 1) % w, np.minimum(iy + 1, h - 1)
    rgb = ((1-dx)*(1-dy)*panorama[iy,x0] + dx*(1-dy)*panorama[iy,x1]
           + (1-dx)*dy*panorama[y1,x0] + dx*dy*panorama[y1,x1])
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)


def projected_points(camera, u, v):
    """World points -> normalized frame coordinates and geometric visibility."""
    mode = camera['projection']['mode']
    local = uv_vectors(u, v) @ rotation(camera['yaw'], camera['pitch'], camera.get('roll', 0))
    x, y, z = np.moveaxis(local, -1, 0)
    if mode == 'Linear':
        valid = z > 1e-6
        px, py = x / np.maximum(z, 1e-6), y / np.maximum(z, 1e-6)
    elif mode == 'Dewarp':
        valid = np.hypot(x, z) > 1e-6
        px, py = np.arctan2(x, z), y / np.maximum(np.hypot(x, z), 1e-6)
    else:
        theta = np.arccos(np.clip(z, -1, 1))
        radius = np.tan(theta / 2) if mode == 'Ultra' else theta
        radial = np.hypot(x, y)
        factor = np.divide(radius, radial, out=np.zeros_like(radius), where=radial > 1e-8)
        px, py = x * factor, y * factor
        valid = z > -0.999999
    output = camera_output(camera)
    scale = lens_scale(mode, camera['h_fov'])
    nx, ny = px / scale, py / scale * output['width'] / output['height']
    return nx, ny, valid & (np.abs(nx) <= 1) & (np.abs(ny) <= 1)


def framing_warning(camera, reference_id):
    annotation = next((a for a in camera['annotations'] if a['reference_id'] == reference_id), None)
    if annotation is None or camera['yaw'] is None:
        return 'Sujet non annoté à cet instant : vérifier visuellement le cadre.'
    box = annotation.get('bbox')
    if box:
        u, v = np.meshgrid(np.linspace(box['u_start'], box['u_start'] + box['u_span'], 17),
                           np.linspace(box['v_top'], box['v_bottom'], 17))
    else:
        u, v = np.array([annotation['point']['u']]), np.array([annotation['point']['v']])
    if not np.all(projected_points(camera, u, v)[2]):
        return 'Attention : le point ou une partie de la zone du sujet est hors du cadre.'
    return 'Zone annotée dans le cadre (contrôle géométrique, sans suivi).'
