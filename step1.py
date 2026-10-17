#!/usr/bin/env python3
"""Diagnostic et références 360 locales. Bibliothèque standard Python uniquement."""
import argparse
import datetime as dt
import html
import importlib.metadata
import json
import logging
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import uuid

LOG = logging.getLogger('step1')


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def run(cmd, timeout=180):
    LOG.info('Commande: %s', subprocess.list2cmdline([str(x) for x in cmd]))
    try:
        p = subprocess.run([str(x) for x in cmd], capture_output=True,
                           encoding='utf-8', errors='replace', timeout=timeout,
                           shell=False)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f'Délai dépassé ({timeout}s): {cmd[0]}') from e
    if p.stderr:
        LOG.info('stderr: %s', p.stderr.strip())
    if p.returncode:
        raise RuntimeError(f'Échec ({p.returncode}): {cmd[0]}\n{p.stderr[-4000:]}')
    return p.stdout


def binary(value):
    found = shutil.which(value)
    if not found:
        raise ValueError(f'Exécutable introuvable: {value}. Installer FFmpeg ou fournir son chemin complet.')
    return str(Path(found).resolve())


def environment(ffmpeg, ffprobe):
    versions = {}
    for package in ('opencv-python', 'opencv-python-headless', 'librosa'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    info = {'python': sys.version, 'platform': platform.platform(),
            'ffmpeg_path': ffmpeg, 'ffprobe_path': ffprobe,
            'ffmpeg': run([ffmpeg, '-version']).splitlines()[0],
            'ffprobe': run([ffprobe, '-version']).splitlines()[0],
            'optional_packages': versions}
    filters = run([ffmpeg, '-hide_banner', '-filters'])
    if not re.search(r'\bv360\s', filters):
        raise ValueError('Ce FFmpeg ne contient pas le filtre v360.')
    # Réel test de filtrage v360 en mémoire, sans vidéo utilisateur.
    run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
         'color=c=black:s=128x64:d=0.1', '-vf',
         'v360=input=e:output=flat:w=64:h=36:h_fov=90:v_fov=58.7155',
         '-frames:v', '1', '-threads', '1', '-f', 'null', '-'])
    info['v360_smoke_test'] = 'passed'
    return info


def number(value, label, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label}: nombre attendu.')
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{label}: valeur attendue entre {lo} et {hi}.')
    return float(value)


def load_views(path):
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    views = config.get('views')
    if not isinstance(views, list) or len(views) != 5:
        raise ValueError('La configuration doit contenir exactement cinq vues.')
    ids = set()
    for view in views:
        if not isinstance(view, dict):
            raise ValueError('Chaque vue doit être un objet JSON.')
        ident = view.get('id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', ident) or ident in ids:
            raise ValueError('Identifiant de vue invalide ou dupliqué.')
        ids.add(ident)
        for key, lo, hi in [('yaw', -180, 180), ('pitch', -90, 90), ('h_fov', 10, 160)]:
            number(view.get(key), f'{ident}.{key}', lo, hi)
        if view.get('subject') is not None and not isinstance(view['subject'], str):
            raise ValueError('subject doit être null ou un texte renseigné manuellement.')
    return views


def projection(view, width, height):
    vfov = math.degrees(2 * math.atan(math.tan(math.radians(view['h_fov']) / 2) * height / width))
    return (f"v360=input=e:output=flat:in_stereo=2d:out_stereo=2d:"
            f"w={width}:h={height}:yaw={view['yaw']}:pitch={view['pitch']}:"
            f"roll=0:rorder=ypr:h_fov={view['h_fov']}:v_fov={vfov:.8f}:interp=linear,setsar=1")


def inspect_video(source, ffprobe):
    raw = json.loads(run([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', source]))
    videos = [s for s in raw.get('streams', []) if s.get('codec_type') == 'video'
              and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise ValueError('Aucune piste vidéo exploitable.')
    stream = videos[0]
    try:
        duration = float(stream.get('duration') or raw['format']['duration'])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError('Durée vidéo absente ou invalide.') from e
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Durée vidéo invalide.')
    w, h = stream.get('width', 0), stream.get('height', 0)
    if not w or not h or abs(w / h - 2) > .02:
        raise ValueError(f'Image {w}x{h}: ratio 2:1 requis pour ce prototype mono équirectangulaire.')
    if stream.get('sample_aspect_ratio', '1:1') not in ('1:1', '0:1', 'N/A'):
        raise ValueError('Pixels non carrés: exporter à nouveau avec un SAR 1:1.')
    rotation = float(stream.get('tags', {}).get('rotate', 0))
    for data in stream.get('side_data_list', []):
        rotation = float(data.get('rotation', rotation))
    if rotation % 360:
        raise ValueError('Rotation de métadonnées non nulle: réexporter un panorama horizontal.')
    return raw, stream, duration


def sample_times(start, end, interval, limit):
    count = math.ceil((end - start) / interval)
    if count > limit:
        raise ValueError(f'{count} références demandées; limite {limit}. Augmenter --interval ou --max-samples.')
    return [start + i * interval for i in range(count) if start + i * interval < end]


def gallery(out, records, views):
    sections = []
    for record in records:
        cards = [f'<figure><img src="{record["panorama"]}"><figcaption>Panorama</figcaption></figure>']
        for view, item in zip(views, record['views']):
            label = html.escape(f"{view['id']} | yaw {view['yaw']}° | pitch {view['pitch']}° | FOV H {view['h_fov']}° | sujet: {view.get('subject') or 'non attribué'}")
            cards.append(f'<figure><img src="{item["file"]}"><figcaption>{label}</figcaption></figure>')
        sections.append(f'<section><h2>Temps demandé : {record["requested_time_seconds"]:.3f} s</h2><div>{"".join(cards)}</div></section>')
    (out / 'gallery.html').write_text('''<!doctype html><html lang="fr"><meta charset="utf-8"><title>Références 360</title>
<style>body{background:#141922;color:#edf2f7;font:16px system-ui;margin:28px}section{margin-bottom:40px}section>div{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}figure{margin:0;background:#242e3d;padding:12px}img{width:100%}figcaption{padding-top:10px}</style>
<h1>Références 360 — étape 1</h1><p>Angles géométriques configurés manuellement. Aucune détection IA. Les temps affichés sont les temps de recherche demandés, pas des PTS mesurés.</p>''' + ''.join(sections) + '</html>', encoding='utf-8')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path)
    p.add_argument('--output', type=Path, default=Path('outputs'))
    p.add_argument('--views', type=Path, default=Path(__file__).with_name('views.json'))
    p.add_argument('--ffmpeg', default='ffmpeg')
    p.add_argument('--ffprobe', default='ffprobe')
    p.add_argument('--check-only', action='store_true')
    p.add_argument('--confirm-equirectangular', action='store_true')
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--end', type=float)
    p.add_argument('--interval', type=float, default=30)
    p.add_argument('--max-samples', type=int, default=100)
    p.add_argument('--width', type=int, default=640)
    p.add_argument('--height', type=int, default=360)
    p.add_argument('--panorama-width', type=int, default=1920)
    p.add_argument('--full-decode-check', action='store_true')
    p.add_argument('--timeout', type=int, default=180, help='Délai par extraction (s).')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    out = args.output.expanduser().resolve() / ('run_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    try:
        out.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        print(f'Impossible de créer le dossier de sortie: {e}', file=sys.stderr)
        return 1
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    for handler in (logging.FileHandler(out / 'run.log', encoding='utf-8'), logging.StreamHandler()):
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        LOG.addHandler(handler)
    report = {'schema_version': 1, 'status': 'running', 'output': str(out), 'ai_configured': False}
    try:
        if sys.version_info < (3, 10):
            raise ValueError('Python 3.10 ou plus récent requis; 3.11/3.12 conseillé.')
        ffmpeg, ffprobe = binary(args.ffmpeg), binary(args.ffprobe)
        report['environment'] = environment(ffmpeg, ffprobe)
        write_json(out / 'environment.json', report['environment'])
        if args.check_only:
            report['status'] = 'success'
            return 0
        if args.source is None:
            raise ValueError('--source est obligatoire hors --check-only.')
        source = args.source.expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError('La source doit être un fichier local.')
        if source.suffix.lower() == '.insv':
            raise ValueError('Exporter le .insv en vidéo 360 mono équirectangulaire assemblée avant ce test.')
        if not args.confirm_equirectangular:
            raise ValueError('Confirmer la projection avec --confirm-equirectangular. Le ratio seul ne la prouve pas.')
        for value, label, lo, hi in [(args.start, 'start', 0, 1e9), (args.interval, 'interval', .01, 1e9),
                                      (args.width, 'width', 64, 4096), (args.height, 'height', 64, 4096),
                                      (args.panorama_width, 'panorama-width', 128, 8192),
                                      (args.max_samples, 'max-samples', 1, 10000), (args.timeout, 'timeout', 1, 86400)]:
            number(value, label, lo, hi)
        if args.panorama_width % 2:
            raise ValueError('--panorama-width doit être pair.')
        views = load_views(args.views)
        raw, stream, duration = inspect_video(source, ffprobe)
        write_json(out / 'probe.json', raw)
        write_json(out / 'views.used.json', {'views': views})
        end = duration if args.end is None else number(args.end, 'end', 0, duration)
        if args.start >= end:
            raise ValueError('--start doit précéder --end et la fin de la vidéo.')
        times = sample_times(args.start, end, args.interval, args.max_samples)
        before = source.stat()
        report['source'] = {'path': str(source), 'size_bytes': before.st_size, 'mtime_ns': before.st_mtime_ns,
                            'duration_seconds': duration, 'video_stream_index': stream['index'],
                            'projection': 'equirectangular_mono_user_confirmed'}
        report['validation'] = 'metadata_and_sampled_decode'
        if args.full_decode_check:
            run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-xerror', '-nostdin', '-noautorotate',
                 '-i', source, '-map', f"0:{stream['index']}", '-an', '-sn', '-dn', '-f', 'null', '-'], timeout=3600)
            report['validation'] = 'full_video_decode'
        records = []
        for index, time in enumerate(times):
            LOG.info('Référence %s/%s à %.3fs', index + 1, len(times), time)
            folder = out / f'ref_{index:04d}'
            folder.mkdir()
            pano = folder / 'panorama.png'
            run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-xerror', '-nostdin', '-n',
                 '-ss', f'{time:.9f}', '-noautorotate', '-i', source, '-map', f"0:{stream['index']}",
                 '-an', '-sn', '-dn', '-vf', f'scale={args.panorama_width}:{args.panorama_width // 2},setsar=1',
                 '-frames:v', '1', '-threads', '1', '-update', '1', pano], timeout=args.timeout)
            if not pano.is_file() or pano.stat().st_size == 0:
                raise RuntimeError(f'Aucune image décodée à {time}s.')
            record = {'requested_time_seconds': time, 'panorama': pano.relative_to(out).as_posix(), 'views': []}
            # Toutes les vues utilisent exactement la même image décodée, en basse résolution.
            for view in views:
                dest = folder / (view['id'] + '.png')
                run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n', '-i', pano,
                     '-vf', projection(view, args.width, args.height), '-frames:v', '1',
                     '-threads', '1', '-update', '1', dest], timeout=args.timeout)
                if not dest.is_file() or dest.stat().st_size == 0:
                    raise RuntimeError(f'Vue vide: {dest}')
                record['views'].append({'file': dest.relative_to(out).as_posix(), **view,
                                        'position_source': 'manual_configuration', 'ai_detection': None})
            records.append(record)
            write_json(out / 'references.json', {'schema_version': 1, 'samples': records})
        gallery(out, records, views)
        after = source.stat()
        report['source_stat_unchanged'] = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        if not report['source_stat_unchanged']:
            raise RuntimeError('La source a changé pendant le traitement (taille/date).')
        report['sample_count'] = len(records)
        report['status'] = 'success'
        LOG.info('Terminé. Ouvrir %s', out / 'gallery.html')
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as e:
        report.update(status='failed', error=str(e))
        LOG.exception('Échec: %s', e)
        return 1
    except KeyboardInterrupt:
        report.update(status='interrupted', error='Interruption utilisateur')
        LOG.warning('Interrompu; sorties partielles conservées.')
        return 130
    finally:
        write_json(out / 'report.json', report)
        LOG.info('Rapport: %s', out / 'report.json')
        for handler in LOG.handlers[:]:
            handler.close()
            LOG.removeHandler(handler)


if __name__ == '__main__':
    raise SystemExit(main())
