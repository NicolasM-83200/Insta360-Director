"""Projet versionné : annotations manuelles, références copiées et caméras fixes."""
import copy
import datetime as dt
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import uuid
from PIL import Image
from .geometry import angles_to_uv, uv_to_angles, finite
from .profiles import (output_format, MODES, vertical_fov, lens_scale,
                       scale_fov, max_fov)

LOG = logging.getLogger('step2')
SUBJECTS = [('chanteur', 'Chanteur', 65), ('guitariste', 'Guitariste', 70),
            ('bassiste', 'Bassiste', 70), ('batteur', 'Batteur', 90), ('groupe', 'Groupe entier', 115)]
VISIBILITY = ('visible', 'partiel', 'masque', 'hors_champ')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def new_document():
    return {'schema_version': 2, 'artifact_type': 'manual_musician_mapping', 'app_version': '0.3.0',
            'created_at': now(), 'updated_at': now(), 'annotation_origin': 'manual', 'ai_detections': [],
            'coordinate_system': {'projection': 'equirectangular_mono', 'origin': 'top_left',
                                  'coordinates': 'normalized_pixel_edges', 'pixel_center': '(i+0.5)/size',
                                  'yaw': '360*u-180, wrapped [-180,180)', 'pitch': '90-180*v',
                                  'rotation_order': 'ypr', 'output_aspect': 'per_camera'},
            'export_settings': {'crf': 20, 'preset': 'veryfast', 'audio_bitrate': '192k'},
            'source': None, 'references': [], 'cameras': [
                {'id': sid, 'label': label, 'annotation_origin': 'manual', 'ai_detection': None,
                 'yaw': None, 'pitch': None, 'center_uv': None, 'h_fov': fov, 'fov_origin': 'preset_to_validate',
                 'roll': 0, 'projection': {'mode': 'Linear'}, 'output': output_format(),
                 'saved_framings': [], 'validated': False, 'annotations': [], 'reviews': []}
                for sid, label, fov in SUBJECTS]}


def signature(camera):
    output = camera.get('output', output_format('16:9', 1280, 720))
    return json.dumps([camera['yaw'], camera['pitch'], camera['h_fov'], camera.get('roll', 0),
                       camera.get('projection', {}).get('mode', 'Linear'), output['format']], separators=(',', ':'))


def migrate_document(document):
    """Copy-on-load migration; the file is never changed until explicit save."""
    doc = copy.deepcopy(document)
    if doc.get('schema_version') != 1:
        return doc
    for cam in doc['cameras']:
        old_signature = json.dumps([cam['yaw'], cam['pitch'], cam['h_fov']], separators=(',', ':'))
        cam.update(roll=0, projection={'mode': 'Linear'},
                   output=output_format('16:9', 1280, 720), saved_framings=[])
        for review in cam['reviews']:
            if review.get('framing_signature') == old_signature:
                review['framing_signature'] = signature(cam)
    doc.update(schema_version=2, app_version='0.3.0', migrated_from=1,
               export_settings={'crf': 20, 'preset': 'veryfast', 'audio_bitrate': '192k'})
    doc['coordinate_system']['output_aspect'] = 'per_camera'
    doc['coordinate_system'].pop('roll', None)
    return doc


def review_complete(camera, references):
    sig = signature(camera)
    return bool(references) and all(any(r['reference_id'] == ref['id'] and r['framing_signature'] == sig
                                       for r in camera['reviews']) for ref in references)


def validate_document(doc):
    if doc.get('schema_version') != 2 or doc.get('artifact_type') != 'manual_musician_mapping':
        raise ValueError('Format musiciens.json inconnu.')
    settings = doc['export_settings']
    if type(settings['crf']) is not int or not 0 <= settings['crf'] <= 51:
        raise ValueError('CRF entier entre 0 et 51 requis.')
    if settings['preset'] not in ('ultrafast', 'veryfast', 'fast', 'medium', 'slow') or settings['audio_bitrate'] not in ('128k', '192k', '256k', '320k'):
        raise ValueError('Paramètres d’encodage inconnus.')
    cameras = doc.get('cameras', [])
    if [c.get('id') for c in cameras] != [s[0] for s in SUBJECTS]:
        raise ValueError('Les cinq identifiants stables sont requis dans leur ordre initial.')
    refs = doc.get('references', [])
    if len(refs) > 200 or len({r['id'] for r in refs}) != len(refs):
        raise ValueError('Références invalides ou trop nombreuses (maximum 200).')
    ref_ids = {r['id'] for r in refs}
    for r in refs:
        if finite(r['requested_time_seconds']) < 0:
            raise ValueError('Temps négatif.')
    for c in cameras:
        if c.get('annotation_origin') != 'manual' or c.get('ai_detection') is not None:
            raise ValueError('Cette version accepte uniquement des annotations manuelles.')
        if (c['yaw'] is None) != (c['pitch'] is None):
            raise ValueError('Orientation incomplète.')
        if c['yaw'] is not None:
            angles_to_uv(c['yaw'], c['pitch'])
            if not -180 <= finite(c['yaw']) <= 180:
                raise ValueError('Yaw hors limites.')
        output = output_format(c['output']['format'], c['output']['width'], c['output']['height'])
        vertical_fov(c['projection']['mode'], c['h_fov'], output['width'] / output['height'])
        if not -180 <= finite(c['roll']) <= 180:
            raise ValueError('Roll hors limites.')
        if type(c['validated']) is not bool:
            raise ValueError('Validation booléenne requise.')
        for annotation in c['annotations']:
            if annotation['reference_id'] not in ref_ids:
                raise ValueError('Référence d’annotation inconnue.')
            uv_to_angles(annotation['point']['u'], annotation['point']['v'])
        for review in c['reviews']:
            if review['reference_id'] not in ref_ids or review['visibility'] not in VISIBILITY:
                raise ValueError('Observation manuelle invalide.')
        if c['validated'] and (c['yaw'] is None or not review_complete(c, refs)):
            raise ValueError('Une caméra validée doit avoir une orientation et toutes ses observations à jour.')
    return doc


class Project:
    def __init__(self, root, document):
        self.root = Path(root).resolve()
        self.doc = validate_document(migrate_document(document))
        self.dirty = False

    @classmethod
    def create(cls, parent):
        root = Path(parent).expanduser().resolve() / ('mapping_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
        root.mkdir(parents=True, exist_ok=False)
        (root / 'references').mkdir()
        project = cls(root, new_document())
        project.save()
        return project

    @classmethod
    def load(cls, path):
        path = Path(path).expanduser().resolve()
        if path.is_dir():
            path = path / 'musiciens.json'
        project = cls(path.parent, read_json(path))
        for ref in project.doc['references']:
            actual = hashlib.sha256(project.reference_path(ref).read_bytes()).hexdigest()
            if actual != ref['sha256']:
                raise ValueError('Panorama modifié depuis sa sauvegarde : ' + ref['panorama'])
        return project

    def reference_path(self, ref):
        path = (self.root / ref['panorama']).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Une référence doit rester dans le dossier de cartographie.')
        return path

    def save(self):
        validate_document(self.doc)
        self.doc['updated_at'] = now()
        # Une sauvegarde précédente reste disponible ; aucune écriture dans la source ni dans A.
        dest = self.root / 'musiciens.json'
        if dest.exists():
            if read_json(dest).get('schema_version') == 1:
                backup = self.root / 'musiciens.v1.original.json'
                if not backup.exists():
                    shutil.copy2(dest, backup)
            shutil.copy2(dest, self.root / 'musiciens.previous.json')
        atomic_json(dest, self.doc)
        self.dirty = False
        LOG.info('Annotations sauvegardées : %s', dest)
        return dest

    def add_panorama(self, path, time, origin='manual_import'):
        time = finite(time)
        if time < 0:
            raise ValueError('Temps négatif.')
        if len(self.doc['references']) >= 200:
            raise ValueError('Maximum 200 références.')
        with Image.open(path) as im:
            w, h = im.size
            if abs(w / h - 2) > .02:
                raise ValueError('Panorama 2:1 requis.')
            im.verify()
        ident = 'ref_' + uuid.uuid4().hex[:12]
        dest = self.root / 'references' / (ident + '.png')
        dest.parent.mkdir(exist_ok=True)
        # Normalisation PNG locale; le fichier fourni reste inchangé.
        with Image.open(path) as im:
            im.convert('RGB').save(dest)
        ref = {'id': ident, 'panorama': dest.relative_to(self.root).as_posix(),
               'requested_time_seconds': time, 'time_semantics': 'requested_seek_not_measured_pts',
               'width': w, 'height': h, 'origin': origin,
               'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()}
        self.doc['references'].append(ref)
        for c in self.doc['cameras']:
            c['validated'] = False
        self.dirty = True
        return ref

    def import_stage_a(self, run):
        run = Path(run).expanduser().resolve()
        report = read_json(run / 'report.json')
        refs = read_json(run / 'references.json')
        if report.get('status') != 'success':
            raise ValueError('Le dossier A ne signale pas une exécution réussie.')
        self.doc['source'] = copy.deepcopy(report['source'])
        self.doc['stage_a'] = {'run_directory': str(run), 'schema_version': report['schema_version']}
        if (run / 'probe.json').exists():
            probe = read_json(run / 'probe.json')
            self.doc['source']['original_probe'] = probe
        for sample in refs['samples']:
            path = (run / sample['panorama']).resolve()
            if not path.is_relative_to(run):
                raise ValueError('Référence A située hors de son dossier.')
            self.add_panorama(path, sample['requested_time_seconds'], 'stage_a')
        self.save()

    def change_camera(self, camera, yaw, pitch, fov, fov_origin='manual_adjustment', roll=None):
        angles_to_uv(yaw, pitch)
        output = camera['output']
        vertical_fov(camera['projection']['mode'], fov, output['width'] / output['height'])
        if roll is not None and not -180 <= finite(roll) <= 180:
            raise ValueError('Roll hors limites.')
        u, v = angles_to_uv(yaw, pitch)
        camera.update(yaw=float(yaw), pitch=float(pitch), center_uv={'u': u, 'v': v}, h_fov=float(fov), fov_origin=fov_origin, validated=False)
        if roll is not None:
            camera['roll'] = float(roll)
        self.dirty = True

    def set_output(self, camera, name, width=None, height=None):
        output = output_format(name, width, height)
        old = camera['output']
        old_aspect, aspect = old['width'] / old['height'], output['width'] / output['height']
        mode = camera['projection']['mode']
        # Expand coverage on the changing axis, never silently crop a portrait.
        fov = scale_fov(mode, lens_scale(mode, camera['h_fov']) * max(1, aspect / old_aspect))
        limited = fov > max_fov(mode, aspect)
        camera.update(output=output, h_fov=min(fov, max_fov(mode, aspect)))
        if name != old['format']:
            camera['validated'] = False
        self.dirty = True
        return 'Limite de projection atteinte : vérifier la zone du sujet.' if limited else ''

    def set_projection(self, camera, mode):
        if mode not in MODES:
            raise ValueError('Projection inconnue.')
        if mode == camera['projection']['mode']:
            return
        output = camera['output']
        camera.update(projection={'mode': mode},
                      h_fov=min(MODES[mode]['default_fov'], max_fov(mode, output['width']/output['height'])),
                      fov_origin='projection_preset', validated=False)
        self.dirty = True

    def remember_framing(self, camera, label=''):
        if camera['yaw'] is None:
            raise ValueError('Positionner la caméra avant de mémoriser son cadrage.')
        keys = ('yaw', 'pitch', 'roll', 'h_fov', 'projection', 'output', 'fov_origin')
        entry = {key: copy.deepcopy(camera[key]) for key in keys}
        entry.update(label=label or now(), saved_at=now())
        camera['saved_framings'].append(entry)
        self.dirty = True
        return entry

    def restore_framing(self, camera, index=-1):
        entry = camera['saved_framings'][index]
        candidate = copy.deepcopy(camera)
        for key in ('yaw', 'pitch', 'roll', 'h_fov', 'projection', 'output', 'fov_origin'):
            candidate[key] = copy.deepcopy(entry[key])
        u, v = angles_to_uv(candidate['yaw'], candidate['pitch'])
        candidate.update(center_uv={'u': u, 'v': v}, validated=False)
        doc = copy.deepcopy(self.doc)
        doc['cameras'][[c['id'] for c in doc['cameras']].index(camera['id'])] = candidate
        validate_document(doc)
        camera.update(candidate)
        self.dirty = True

    def annotate(self, camera, ref, u, v, bbox=None):
        record = {'reference_id': ref['id'], 'origin': 'manual', 'created_at': now(),
                  'point': {'u': u, 'v': v, 'x': u * ref['width'], 'y': v * ref['height']},
                  'bbox': bbox}
        camera['annotations'] = [r for r in camera['annotations'] if r['reference_id'] != ref['id']] + [record]
        camera['validated'] = False
        self.dirty = True

    def review(self, camera, ref, visibility):
        if camera['yaw'] is None:
            raise ValueError('Positionner cette caméra avant de vérifier sa visibilité.')
        if visibility not in VISIBILITY:
            raise ValueError('Visibilité inconnue.')
        entry = {'reference_id': ref['id'], 'visibility': visibility, 'origin': 'manual',
                 'framing_signature': signature(camera), 'reviewed_at': now()}
        camera['reviews'] = [r for r in camera['reviews'] if r['reference_id'] != ref['id']] + [entry]
        camera['validated'] = False
        self.dirty = True

    def validate_camera(self, camera):
        if camera['yaw'] is None or not review_complete(camera, self.doc['references']):
            raise ValueError('Renseigner la visibilité sur chaque référence avec le cadrage actuel.')
        camera['validated'] = True
        self.dirty = True

    def stage_a_views(self):
        if any(c['yaw'] is None for c in self.doc['cameras']):
            raise ValueError('Positionner les cinq caméras avant cet export.')
        if any(c['projection']['mode'] != 'Linear' or c['roll'] != 0 or c['output']['format'] != '16:9' for c in self.doc['cameras']):
            raise ValueError('A accepte uniquement Linear, roll nul et 16:9. Les cadrages B.1 sont conservés.')
        return {'views': [{'id': c['id'], 'subject': c['label'], 'yaw': c['yaw'],
                           'pitch': c['pitch'], 'h_fov': c['h_fov']} for c in self.doc['cameras']]}
