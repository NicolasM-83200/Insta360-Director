#!/usr/bin/env python3
"""Étape B : cartographie manuelle locale, GUI Tk ou commandes de validation."""
import argparse
import logging
from pathlib import Path
import sys
import uuid


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group()
    group.add_argument('--run',type=Path,help='Dossier run_... de A ; crée un projet B distinct.')
    group.add_argument('--project',type=Path,help='Dossier B ou son fichier musiciens.json à reprendre.')
    group.add_argument('--panorama',type=Path,help='Importer un panorama isolé, avec --time obligatoire.')
    p.add_argument('--time',type=float,help='Instant demandé pour un panorama isolé.')
    p.add_argument('--source',type=Path,help='Chemin actuel de la source vidéo (facultatif pour annoter).')
    p.add_argument('--confirm-equirectangular',action='store_true')
    p.add_argument('--output',type=Path,default=Path('mappings'))
    p.add_argument('--ffmpeg',default='ffmpeg')
    p.add_argument('--ffprobe',default='ffprobe')
    p.add_argument('--check-conventions',action='store_true',help='Mire réelle FFmpeg, sans interface.')
    p.add_argument('--export-clips',action='store_true',help='Rendre cinq extraits depuis un projet validé, sans interface.')
    p.add_argument('--export-image',action='store_true',help='PNG final à --time (référence existante).')
    p.add_argument('--camera', choices=['chanteur','guitariste','bassiste','batteur','groupe'],
                   help='Exporter seulement cette caméra, même en brouillon, pour validation.')
    p.add_argument('--format', choices=['16:9','9:16','4:3','3:4','1:1','2.35:1'])
    p.add_argument('--projection', choices=['Mega','Ultra','Dewarp','Linear'])
    p.add_argument('--start',type=float,default=0)
    p.add_argument('--duration',type=float,default=5)
    p.add_argument('--width',type=int)
    p.add_argument('--height',type=int)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    if sys.version_info<(3,12):
        print('Python 3.12 ou supérieur requis pour B. A conserve ses prérequis.',file=sys.stderr)
        return 1
    try:
        from mapping360.project import Project
        from mapping360.render import attach_source,check_conventions,export_clips,export_images,extract_reference
    except ImportError as e:
        print(f'Dépendance absente : {e}. Installer requirements-step2.txt.',file=sys.stderr)
        return 1
    try:
        if args.export_clips and args.export_image:
            raise ValueError('Choisir --export-clips ou --export-image.')
        if (args.export_clips or args.export_image) and not args.project:
            raise ValueError('Les exports requièrent --project.')
        if (args.width is None) != (args.height is None):
            raise ValueError('Fournir --width et --height ensemble.')
        if args.check_conventions:
            folder=args.output.resolve()/('conventions_'+uuid.uuid4().hex[:8])
            folder.mkdir(parents=True)
            logging.basicConfig(level=logging.INFO,handlers=[logging.FileHandler(folder/'step2.log',encoding='utf-8'),logging.StreamHandler()])
            check_conventions(folder,args.ffmpeg)
            print(f'Conventions validées : {folder}')
            return 0
        project=Project.load(args.project) if args.project else Project.create(args.output)
        logging.basicConfig(level=logging.INFO,handlers=[logging.FileHandler(project.root/'step2.log',encoding='utf-8'),logging.StreamHandler()])
        if args.run:
            project.import_stage_a(args.run)
        elif args.panorama:
            if args.time is None:
                raise ValueError('--time est requis pour un panorama isolé ; ne pas inventer son instant.')
            project.add_panorama(args.panorama,args.time)
            project.save()
        if args.source:
            if not args.confirm_equirectangular:
                raise ValueError('Ajouter --confirm-equirectangular pour confirmer la projection source.')
            project.doc['source']=attach_source(project.doc,args.source,args.ffprobe)
            if not project.doc['references']:
                time = args.time if args.time is not None else 0
                path = extract_reference(project.doc,project.root/'cache',time,args.ffmpeg,args.ffprobe)
                project.add_panorama(path,time,'source_seek_ffmpeg')
            project.save()
        selected = [c for c in project.doc['cameras'] if args.camera is None or c['id'] == args.camera]
        for camera in selected:
            if args.projection:
                project.set_projection(camera, args.projection)
            if args.format or args.width is not None:
                project.set_output(camera, args.format or camera['output']['format'], args.width, args.height)
        if args.export_image:
            ref = next((r for r in project.doc['references'] if args.time is not None and abs(r['requested_time_seconds']-args.time)<1e-6),None)
            if ref is None:
                raise ValueError('--time doit désigner une référence existante pour le PNG.')
            print(export_images(project,ref['id'],[args.camera] if args.camera else None,args.ffmpeg,args.ffprobe))
            return 0
        if args.export_clips:
            if not args.project:
                raise ValueError('--export-clips requiert --project (cinq caméras validées).')
            out=export_clips(project.doc,project.root,args.start,args.duration,args.ffmpeg,args.ffprobe,
                             progress=print,camera_ids=[args.camera] if args.camera else None)
            print(out)
            return 0
        import tkinter as tk
        from mapping360.ui_studio import MappingApp
        root=tk.Tk()
        MappingApp(root,project,args.ffmpeg,args.ffprobe)
        root.mainloop()
        return 0
    except Exception as e:
        logging.exception('Étape B interrompue')
        print(f'Erreur : {e}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
