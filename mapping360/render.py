"""Extraction ponctuelle et rendu depuis la source originale, sans dépendance UI."""
import copy
import datetime as dt
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import uuid
import numpy as np
from PIL import Image
import step1
from .geometry import preview_rgb, finite, uv_to_angles
from .project import atomic_json, validate_document

LOG = logging.getLogger('step2')


def command(args, timeout=300):
    args = [str(x) for x in args]
    LOG.info('Commande: %s', subprocess.list2cmdline(args))
    p = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace',
                       shell=False, timeout=timeout)
    if p.stderr:
        LOG.info('FFmpeg: %s', p.stderr.strip())
    if p.returncode:
        raise RuntimeError(f'Commande échouée ({p.returncode}) : {p.stderr[-3000:]}')
    return p.stdout


def source_fingerprint(path):
    path = Path(path)
    size = path.stat().st_size
    # Empreinte rapide explicitement partielle, sans lecture des 2 Go complets.
    h = hashlib.sha256()
    with path.open('rb') as f:
        h.update(f.read(1048576))
        if size > 1048576:
            f.seek(max(1048576, size - 1048576))
            h.update(f.read(1048576))
    return {'algorithm': 'sha256_first_last_1MiB_plus_size',
            'digest': hashlib.sha256(h.digest() + str(size).encode()).hexdigest()}


def attach_source(document, source, ffprobe='ffprobe'):
    path = Path(source).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() == '.insv':
        raise ValueError('Sélectionner un export vidéo équirectangulaire, pas un .insv.')
    existing = document.get('source') or {}
    if existing.get('size_bytes') is not None and path.stat().st_size != existing['size_bytes']:
        raise ValueError('Taille différente de la source du projet. Créer un autre projet pour une autre vidéo.')
    fingerprint = source_fingerprint(path)
    if existing.get('fingerprint') and fingerprint != existing['fingerprint']:
        raise ValueError('Le contenu ne correspond pas à la source déjà liée.')
    raw, stream, duration = step1.inspect_video(path, step1.binary(ffprobe))
    if existing.get('duration_seconds') and abs(existing['duration_seconds'] - duration) > .1:
        raise ValueError('Durée différente de la source attendue.')
    if any(ref['requested_time_seconds'] >= duration for ref in document['references']):
        raise ValueError('Une référence dépasse la durée de cette vidéo.')
    st = path.stat()
    return {**existing, 'path': str(path), 'size_bytes': st.st_size, 'mtime_ns': st.st_mtime_ns,
            'fingerprint': fingerprint, 'duration_seconds': duration, 'video_stream_index': stream['index'],
            'width': stream['width'], 'height': stream['height'], 'probe': raw,
            'projection': 'equirectangular_mono_user_confirmed'}


def checked_source(document, ffprobe):
    if not document.get('source'):
        raise ValueError('Lier la vidéo source pour extraire un autre instant ou un extrait.')
    info = attach_source(document, document['source']['path'], ffprobe)
    return Path(info['path']), info


def extract_reference(document, cache_dir, time, ffmpeg='ffmpeg', ffprobe='ffprobe'):
    """Décodage par recherche à un instant uniquement; cache identifié par source et temps."""
    source, info = checked_source(document, ffprobe)
    time = finite(time)
    if not 0 <= time < info['duration_seconds']:
        raise ValueError('Instant en dehors de la vidéo.')
    key = hashlib.sha256(json.dumps([info['fingerprint'], time, 1920]).encode()).hexdigest()[:24]
    cache = Path(cache_dir)
    cache.mkdir(exist_ok=True)
    dest = cache / (key + '.png')
    if dest.exists():
        with Image.open(dest) as im:
            im.verify()
        return dest
    before = source.stat()
    temp = cache / (key + '.' + uuid.uuid4().hex + '.png')
    try:
        command([step1.binary(ffmpeg), '-hide_banner', '-loglevel', 'error', '-xerror', '-nostdin', '-n',
                 '-ss', f'{time:.9f}', '-noautorotate', '-i', source, '-map', f"0:{info['video_stream_index']}",
                 '-an', '-sn', '-dn', '-vf', 'scale=1920:960,setsar=1', '-frames:v', '1',
                 '-threads', '1', '-update', '1', temp])
        with Image.open(temp) as im:
            im.verify()
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('Source modifiée pendant l’extraction.')
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)
    return dest


def export_previews(project):
    """Exporte uniquement les cadrages réellement renseignés, sans fausse caméra par défaut."""
    root = project.root / ('previews_' + uuid.uuid4().hex[:8])
    root.mkdir()
    manifest = {'type': 'manual_still_previews', 'renderer': 'numpy_bilinear_v360_compatible', 'images': []}
    for ref in project.doc['references']:
        with Image.open(project.reference_path(ref)) as im:
            pano = np.array(im.convert('RGB'))
        for cam in project.doc['cameras']:
            if cam['yaw'] is None:
                continue
            name = ref['id'] + '_' + cam['id'] + '.png'
            rgb = preview_rgb(pano, cam['yaw'], cam['pitch'], cam['h_fov'], 960, 540)
            Image.fromarray(rgb).save(root / name)
            manifest['images'].append({'file': name, 'reference_id': ref['id'], 'camera_id': cam['id'],
                                       'requested_time_seconds': ref['requested_time_seconds'],
                                       'camera': copy.deepcopy(cam), 'reference_sha256': ref['sha256']})
    atomic_json(root / 'manifest.json', manifest)
    return root


def export_clips(document, output_parent, start, duration=5, ffmpeg='ffmpeg', ffprobe='ffprobe',
                 width=1280, height=720, progress=None):
    """Cinq plans fixes depuis le fichier source; aucune lecture du panorama pour le rendu.
    Extraits autonomes H.264/AAC. Pas d'assemblage ni de timeline à cette étape.
    """
    validate_document(document)
    if any(not cam['validated'] for cam in document['cameras']):
        raise ValueError('Valider manuellement les cinq caméras avant de rendre les extraits.')
    start, duration = finite(start), finite(duration)
    if not 0 < duration <= 30:
        raise ValueError('Durée des extraits entre 0 et 30 secondes.')
    if not (width >= 160 and height >= 90 and width <= 3840 and width % 2 == height % 2 == 0
            and width * 9 == height * 16):
        raise ValueError('Résolution paire 16:9 requise (maximum 3840 pixels de large).')
    source, info = checked_source(document, ffprobe)
    if start < 0 or start + duration > info['duration_seconds']:
        raise ValueError('Extrait hors de la durée source; réduire début ou durée.')
    ffmpeg = step1.binary(ffmpeg)
    ffprobe = step1.binary(ffprobe)
    folder = Path(output_parent) / ('clips_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 1, 'status': 'running', 'source': info, 'source_resolution_used': [info['width'], info['height']],
              'requested_start_seconds': start, 'requested_duration_seconds': duration,
              'ffmpeg_version': command([ffmpeg, '-version']).splitlines()[0],
              'output_size': [width, height], 'clips': [], 'audio_policy': 'first_audio_stream_if_present_aac_192k'}
    before = source.stat()
    atomic_json(folder / 'musiciens.snapshot.json', document)
    try:
        for index, cam in enumerate(document['cameras']):
            if progress:
                progress(f'Export {index + 1}/5 : {cam["label"]}')
            target = folder / (cam['id'] + '.mp4')
            vf = step1.projection(cam, width, height)
            args = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-xerror', '-nostdin', '-n',
                    '-ss', f'{start:.9f}', '-noautorotate', '-i', source, '-t', f'{duration:.9f}',
                    '-map', f"0:{info['video_stream_index']}", '-map', '0:a:0?', '-sn', '-dn',
                    '-map_metadata', '-1', '-map_chapters', '-1', '-vf', vf,
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', target]
            command(args, timeout=3600)
            probe = json.loads(command([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', target]))
            video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            actual = float(video.get('duration') or probe['format']['duration'])
            if video['width'] != width or video['height'] != height or actual <= 0:
                raise RuntimeError('Sortie invalide.')
            report['clips'].append({'camera_id': cam['id'], 'file': target.name, 'command': [str(x) for x in args],
                                    'filter': vf, 'actual_video_duration_seconds': actual, 'probe': probe})
            atomic_json(folder / 'render_report.json', report)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('La source a changé pendant le rendu.')
        report['source_stat_unchanged'] = True
        report['status'] = 'success'
    except Exception as e:
        report.update(status='failed', error=str(e))
        raise
    finally:
        atomic_json(folder / 'render_report.json', report)
    return folder


def check_conventions(folder, ffmpeg='ffmpeg'):
    """Expérience reproductible sur mire RGB sphérique : signes ET projection entière."""
    ffmpeg = step1.binary(ffmpeg)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    w, h = 1440, 720
    u, v = np.meshgrid((np.arange(w) + .5) / w, (np.arange(h) + .5) / h)
    # Fonction périodique, donc aucune discontinuité artificielle à la jonction.
    texture = np.stack([127 + 100 * np.sin(2 * np.pi * u), 255 * v,
                        127 + 100 * np.cos(2 * np.pi * u)], axis=-1).astype(np.uint8)
    src = folder / 'convention_mire.png'
    Image.fromarray(texture).save(src)
    results = []
    for yaw, pitch, fov in [(0, 0, 70), (90, 0, 70), (-90, 0, 70), (0, 45, 70),
                             (90, 35, 95), (179, -25, 90), (-179, 30, 110), (35, 80, 45)]:
        dest = folder / f'ffmpeg_{yaw}_{pitch}.png'
        cam = {'yaw': yaw, 'pitch': pitch, 'h_fov': fov}
        command([ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', src, '-vf', step1.projection(cam, 321, 181),
                 '-frames:v', '1', '-threads', '1', dest])
        actual = np.array(Image.open(dest).convert('RGB'))
        expected = preview_rgb(texture, yaw, pitch, fov, 321, 181)
        error = np.abs(actual.astype(float) - expected.astype(float))
        center_uv = ((yaw + 180) / 360 % 1, (90 - pitch) / 180)
        cu, cv = center_uv
        target_rgb = np.array([127 + 100 * np.sin(2*np.pi*cu), 255*cv, 127 + 100*np.cos(2*np.pi*cu)])
        center_error = float(np.max(np.abs(actual[90, 160].astype(float) - target_rgb)))
        results.append({'yaw': yaw, 'pitch': pitch, 'h_fov': fov, 'mean_absolute_error_8bit': float(error.mean()),
                        'p99_error_8bit': float(np.percentile(error, 99)), 'center_error_8bit': center_error,
                        'expected_center_uv': list(center_uv),
                        'passed': bool(error.mean() < 2 and np.percentile(error, 99) < 5 and center_error < 3)})
    report = {'ffmpeg': command([ffmpeg, '-version']).splitlines()[0], 'synthetic_test': True,
              'status': 'passed' if all(r['passed'] for r in results) else 'failed', 'cases': results}
    atomic_json(folder / 'conventions.json', report)
    if report['status'] != 'passed':
        raise RuntimeError('Écart géométrique avec FFmpeg : voir conventions.json.')
    return report
