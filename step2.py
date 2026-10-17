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
    p.add_argument('--start',type=float,default=0)
    p.add_argument('--duration',type=float,default=5)
    p.add_argument('--width',type=int,default=1280)
    p.add_argument('--height',type=int,default=720)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    if sys.version_info<(3,12):
        print('Python 3.12 ou supérieur requis pour B. A conserve ses prérequis.',file=sys.stderr)
        return 1
    try:
        from mapping360.project import Project
        from mapping360.render import attach_source,check_conventions,export_clips
    except ImportError as e:
        print(f'Dépendance absente : {e}. Installer requirements-step2.txt.',file=sys.stderr)
        return 1
    try:
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
            project.save()
        if args.export_clips:
            if not args.project:
                raise ValueError('--export-clips requiert --project (cinq caméras validées).')
            out=export_clips(project.doc,project.root,args.start,args.duration,args.ffmpeg,args.ffprobe,args.width,args.height,print)
            print(out)
            return 0
        import tkinter as tk
        from mapping360.ui import MappingApp
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
