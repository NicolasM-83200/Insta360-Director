"""Interface Tk locale : sélection sur panorama et aperçus réactifs en mémoire."""
import copy
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from PIL import Image, ImageTk
from .geometry import uv_to_angles, angles_to_uv, normalized_box, box_framing, preview_rgb
from .project import Project, SUBJECTS, VISIBILITY, signature, atomic_json
from .render import attach_source, extract_reference, export_clips, export_previews

LOG = logging.getLogger('step2')


class MappingApp:
    def __init__(self, root, project, ffmpeg='ffmpeg', ffprobe='ffprobe'):
        self.root, self.project = root, project
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.messages = queue.Queue()
        self.busy = False
        self.images = {}
        self.camera_index = 0
        self.ref_index = 0
        self.pano = None
        self.photo = None
        self.preview_job = None
        self.updating = False
        self.drag_start = None
        self.offset_pixels = 0
        self.canvas_size = (700, 350)
        self.root.title('Insta360 · B — Cartographie manuelle')
        self.root.geometry(f'{min(1280,root.winfo_screenwidth()-60)}x{min(850,root.winfo_screenheight()-80)}')
        self.root.minsize(1000, 660)
        self.status = tk.StringVar(value='Choisir un sujet puis cliquer ou tracer sa zone. Aucune IA.')
        self.reference_choice = tk.StringVar()
        self.mode = tk.StringVar(value='point')
        self.offset = tk.DoubleVar(value=0)
        self.visible = tk.StringVar(value=VISIBILITY[0])
        self.export_start = tk.StringVar(value='10')
        self.export_duration = tk.StringVar(value='5')
        self.new_time = tk.StringVar(value='30')
        self.detail = tk.StringVar()
        self.params = {name: tk.DoubleVar(value=val) for name, val in [('yaw',0),('pitch',0),('h_fov',65)]}
        self._build()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_references()
        self.sync_camera()
        self.root.after(100, self.poll)

    @property
    def camera(self):
        return self.project.doc['cameras'][self.camera_index]

    @property
    def reference(self):
        refs = self.project.doc['references']
        return refs[self.ref_index] if refs else None

    def _build(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill='both', expand=True)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='Importer dossier A', command=self.import_a).pack(side='left', padx=2)
        ttk.Button(toolbar, text='Lier / déplacer la source vidéo', command=self.link_source).pack(side='left', padx=2)
        ttk.Button(toolbar, text='Enregistrer musiciens.json', command=self.save).pack(side='left', padx=2)
        ttk.Button(toolbar, text='Exporter views pour A', command=self.save_views).pack(side='left', padx=2)
        ttk.Label(outer, text='B — Annotations manuelles • Caméras fixes • Originaux en lecture seule', font=('Segoe UI',11,'bold')).pack(anchor='w', pady=(8,3))
        main = ttk.Frame(outer)
        main.pack(fill='both', expand=True)
        left = ttk.Frame(main)
        right_holder = ttk.Frame(main, width=420)
        right_holder.pack(side='right', fill='y')
        left.pack(side='left', fill='both', expand=True, padx=(0,12))
        right_holder.pack_propagate(False)
        right_canvas = tk.Canvas(right_holder, width=398, highlightthickness=0)
        right_scroll = ttk.Scrollbar(right_holder, orient='vertical', command=right_canvas.yview)
        right_scroll.pack(side='right', fill='y')
        right_canvas.pack(side='left', fill='both', expand=True)
        right_canvas.configure(yscrollcommand=right_scroll.set)
        right = ttk.Frame(right_canvas)
        right_window = right_canvas.create_window((0,0), window=right, anchor='nw', width=398)
        right.bind('<Configure>', lambda e:right_canvas.configure(scrollregion=right_canvas.bbox('all')))
        right_canvas.bind('<Configure>', lambda e:right_canvas.itemconfigure(right_window, width=e.width))
        row = ttk.Frame(left)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text='Référence :').pack(side='left')
        self.ref_combo = ttk.Combobox(row, textvariable=self.reference_choice, state='readonly', width=31)
        self.ref_combo.pack(side='left', padx=4)
        self.ref_combo.bind('<<ComboboxSelected>>', self.select_reference)
        ttk.Label(row, text='Ajouter (s)').pack(side='left')
        ttk.Entry(row, textvariable=self.new_time, width=7).pack(side='left', padx=3)
        ttk.Button(row, text='+', command=self.add_time).pack(side='left')
        modebar = ttk.Frame(left)
        modebar.pack(fill='x')
        ttk.Radiobutton(modebar, text='Point', variable=self.mode, value='point').pack(side='left')
        ttk.Radiobutton(modebar, text='Zone du corps / groupe (glisser)', variable=self.mode, value='box').pack(side='left')
        self.canvas = tk.Canvas(left, width=700, height=350, bg='#101923', highlightthickness=0)
        self.canvas.pack(fill='x', pady=5)
        self.canvas.bind('<Configure>', lambda e:self.draw_panorama())
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        seamrow = ttk.Frame(left)
        seamrow.pack(fill='x')
        ttk.Label(seamrow, text='Déplacer la jonction :').pack(side='left')
        ttk.Scale(seamrow, variable=self.offset, from_=0, to=360, command=lambda _:self.draw_panorama()).pack(side='left', fill='x', expand=True)
        ttk.Label(left, text='Le déplacement ne change pas les coordonnées enregistrées.\nZone : arc horizontal le plus court (≤180°). Déplacer la jonction pour faciliter le tracé.', wraplength=650).pack(anchor='w', pady=3)
        self.thumb_frame = ttk.Frame(left)
        self.thumb_frame.pack(fill='x', pady=5)
        self.thumbs = []
        for i,(sid,label,_) in enumerate(SUBJECTS):
            block = ttk.Frame(self.thumb_frame)
            block.grid(row=0, column=i, sticky='nsew', padx=3, pady=3)
            photo = ttk.Label(block, text='Non renseigné', anchor='center')
            photo.pack()
            photo.bind('<Button-1>', lambda e,n=i:self.choose_camera(n))
            ttk.Button(block, text=label, command=lambda n=i:self.choose_camera(n)).pack(fill='x')
            self.thumbs.append(photo)
        for i in range(5):
            self.thumb_frame.columnconfigure(i,weight=1)
        ttk.Button(left, text='Enregistrer les aperçus PNG', command=self.save_previews).pack(anchor='w', pady=3)
        self.subject_combo = ttk.Combobox(right, values=[x[1] for x in SUBJECTS], state='readonly', width=35)
        self.subject_combo.pack(fill='x', pady=4)
        self.subject_combo.current(0)
        self.subject_combo.bind('<<ComboboxSelected>>', lambda e:self.choose_camera(self.subject_combo.current()))
        self.preview = ttk.Label(right, text='Cliquer dans le panorama pour positionner ce sujet.', anchor='center')
        self.preview.pack(pady=4)
        for name,lo,hi,label in [('yaw',-180,180,'Yaw (°)'),('pitch',-90,90,'Pitch (°)'),('h_fov',10,160,'FOV horizontal (°)')]:
            row = ttk.Frame(right)
            row.pack(fill='x',pady=2)
            ttk.Label(row,text=label,width=19).pack(side='left')
            spin = ttk.Spinbox(row,textvariable=self.params[name],from_=lo,to=hi,increment=.5,width=9,
                               command=self.parameters_changed)
            spin.pack(side='right')
            spin.bind('<Return>',lambda e:self.parameters_changed())
            spin.bind('<FocusOut>',lambda e:self.parameters_changed())
            ttk.Scale(right,variable=self.params[name],from_=lo,to=hi,command=lambda _:self.parameters_changed()).pack(fill='x')
        ttk.Label(right, textvariable=self.detail, wraplength=390).pack(anchor='w', pady=5)
        review = ttk.LabelFrame(right, text='Observation humaine à cet instant', padding=5)
        review.pack(fill='x', pady=5)
        ttk.Combobox(review, textvariable=self.visible, values=VISIBILITY, state='readonly', width=13).pack(side='left')
        ttk.Button(review,text='Enregistrer observation',command=self.review).pack(side='left',padx=4)
        ttk.Button(right, text='Valider cette caméra (toutes les références)', command=self.validate).pack(fill='x')
        export = ttk.LabelFrame(right, text='Cinq extraits depuis la source — 1280×720', padding=5)
        export.pack(fill='x', pady=7)
        ttk.Label(export,text='Début (s)').grid(row=0,column=0)
        ttk.Entry(export,textvariable=self.export_start,width=8).grid(row=0,column=1)
        ttk.Label(export,text='Durée (s)').grid(row=0,column=2)
        ttk.Entry(export,textvariable=self.export_duration,width=8).grid(row=0,column=3)
        ttk.Button(export,text='Exporter les 5 MP4',command=self.render_clips).grid(row=1,column=0,columnspan=4,sticky='ew',pady=4)
        ttk.Label(right, text='Les rôles sont choisis par vous.\nAucun score IA ni suivi automatique.',wraplength=390).pack(anchor='w')
        ttk.Separator(outer).pack(fill='x',pady=5)
        ttk.Label(outer,textvariable=self.status,wraplength=1150).pack(anchor='w')
        ttk.Label(outer,text=str(self.project.root),foreground='#536274',wraplength=1150).pack(anchor='w')

    def say_error(self, error):
        LOG.error('%s', error)
        self.status.set(str(error))
        messagebox.showerror('Cartographie',str(error),parent=self.root)

    def background(self, function, success):
        if self.busy:
            self.status.set('Une opération est déjà en cours.')
            return
        self.busy = True
        self.status.set('Traitement en cours… L’interface reste consultable.')
        future = self.executor.submit(function)
        future.add_done_callback(lambda f:self.messages.put(('done',f,success)))

    def poll(self):
        while not self.messages.empty():
            item = self.messages.get()
            if item[0] == 'progress':
                self.status.set(item[1])
                continue
            _,future,success = item
            self.busy = False
            try:
                success(future.result())
            except Exception as error:
                LOG.exception('Opération interrompue')
                self.say_error(error)
        self.root.after(100,self.poll)

    def import_a(self):
        if self.project.doc['references']:
            messagebox.showinfo('Projet déjà initialisé','Pour un autre morceau, relancer step2.py avec un autre dossier A.',parent=self.root)
            return
        if self.busy:
            return
        path=filedialog.askdirectory(title='Dossier run_... de l’étape A',parent=self.root)
        if path:
            def done(_):
                self.refresh_references()
                self.status.set('Références A importées. Sélectionner les sujets.')
            self.background(lambda:self.project.import_stage_a(path),done)

    def refresh_references(self):
        refs=self.project.doc['references']
        self.ref_combo['values']=[f"{i+1} · {r['requested_time_seconds']:.3f} s" for i,r in enumerate(refs)]
        if refs:
            self.ref_index=min(self.ref_index,len(refs)-1)
            self.ref_combo.current(self.ref_index)
            self.load_reference()

    def select_reference(self,event=None):
        self.ref_index=self.ref_combo.current()
        self.load_reference()

    def load_reference(self):
        try:
            with Image.open(self.project.reference_path(self.reference)) as im:
                self.pano=np.array(im.convert('RGB'))
            self.export_start.set(f"{self.reference['requested_time_seconds']:g}")
            self.draw_panorama()
            self.render_preview()
            self.update_detail()
        except Exception as error:
            self.say_error(error)

    def choose_camera(self,index):
        self.camera_index=index
        self.subject_combo.current(index)
        self.sync_camera()

    def sync_camera(self):
        self.updating=True
        for key,var in self.params.items():
            var.set(self.camera[key] if self.camera[key] is not None else 0)
        self.updating=False
        self.draw_panorama()
        self.render_preview()
        self.update_detail()

    def update_detail(self):
        cam=self.camera
        sig=signature(cam)
        count=sum(1 for ref in self.project.doc['references'] if any(r['reference_id']==ref['id'] and r['framing_signature']==sig for r in cam['reviews']))
        label='Validée' if cam['validated'] else 'À valider'
        if cam['yaw'] is None:
            label='Non positionnée'
        current=next((r for r in cam['reviews'] if self.reference and r['reference_id']==self.reference['id'] and r['framing_signature']==sig),None)
        if current:
            self.visible.set(current['visibility'])
        self.detail.set(f"{label} · {count}/{len(self.project.doc['references'])} observations à jour.\nÀ cet instant : {current['visibility'] if current else 'non vérifié'}. FOV : {cam['fov_origin']}.")

    def draw_panorama(self):
        if self.pano is None:
            return
        w=max(300,self.canvas.winfo_width())
        h=w//2
        self.canvas.configure(height=h)
        self.canvas_size=(w,h)
        pw=self.pano.shape[1]
        self.offset_pixels=round(self.offset.get()/360*pw)%pw
        rolled=np.roll(self.pano,-self.offset_pixels,axis=1)
        self.photo=ImageTk.PhotoImage(Image.fromarray(rolled).resize((w,h),Image.Resampling.BILINEAR))
        self.canvas.delete('all')
        self.canvas.create_image(0,0,image=self.photo,anchor='nw')
        offset=self.offset_pixels/pw
        for cam in self.project.doc['cameras']:
            if cam['yaw'] is None:
                continue
            u,v=angles_to_uv(cam['yaw'],cam['pitch'])
            x,y=((u-offset)%1)*w,v*h
            color='#00ffe0' if cam['id']==self.camera['id'] else '#ffff80'
            self.canvas.create_line(x-7,y,x+7,y,fill=color,width=2)
            self.canvas.create_line(x,y-7,x,y+7,fill=color,width=2)
            self.canvas.create_text(x+8,y-12,text=cam['label'],anchor='w',fill=color,font=('Segoe UI',10,'bold'))
        annotation=next((a for a in self.camera['annotations'] if self.reference and a['reference_id']==self.reference['id']),None)
        if annotation and annotation.get('bbox'):
            b=annotation['bbox']
            start=(b['u_start']-offset)%1
            end=start+b['u_span']
            for lo,hi in [(start,min(end,1)),(0,max(0,end-1))]:
                if hi>lo:
                    self.canvas.create_rectangle(lo*w,b['v_top']*h,hi*w,b['v_bottom']*h,outline='#00ffe0',width=2)

    def uv_event(self,event):
        w,h=self.canvas_size
        x=max(0,min(w,event.x));y=max(0,min(h,event.y))
        return ((x/w+self.offset_pixels/self.pano.shape[1])%1,y/h)

    def press(self,event):
        if self.pano is not None and not self.busy:
            self.drag_start=(self.uv_event(event),event.x,event.y)

    def drag(self,event):
        if self.drag_start and self.mode.get()=='box':
            self.canvas.delete('drag')
            self.canvas.create_rectangle(self.drag_start[1],self.drag_start[2],event.x,event.y,outline='#ffffff',width=2,tags='drag')

    def release(self,event):
        if self.drag_start is None or self.pano is None or self.busy:
            return
        start=self.drag_start
        self.drag_start=None
        try:
            u,v=self.uv_event(event)
            bbox=None
            fov=self.camera['h_fov']
            origin='preset_to_validate' if self.camera['yaw'] is None else self.camera['fov_origin']
            warning=''
            if self.mode.get()=='box' and abs(event.x-start[1])+abs(event.y-start[2])>5:
                bbox=normalized_box(start[0],(u,v))
                yaw,pitch,fov,fits=box_framing(bbox)
                u,v=angles_to_uv(yaw,pitch)
                origin='manual_bbox_geometric_suggestion'
                if not fits:
                    warning=' Zone trop étendue pour un plan rectilinéaire ≤160° : revoir le cadre.'
            else:
                yaw,pitch=uv_to_angles(u,v)
            self.project.change_camera(self.camera,yaw,pitch,fov,origin)
            self.project.annotate(self.camera,self.reference,u,v,bbox)
            self.sync_camera()
            self.status.set('Position manuelle enregistrée en mémoire. Ajuster puis observer les références.'+warning)
        except Exception as error:
            self.say_error(error)

    def parameters_changed(self):
        if self.updating or self.pano is None or self.busy:
            return
        try:
            yaw,pitch,fov=(self.params[k].get() for k in ('yaw','pitch','h_fov'))
            if not (-180<=yaw<=180 and -90<=pitch<=90 and 10<=fov<=160):
                return
            if [yaw,pitch,fov]==[self.camera[k] for k in ('yaw','pitch','h_fov')]:
                return
            # Les contrôles permettent aussi une saisie angulaire directe, explicitement manuelle.
            self.project.change_camera(self.camera,yaw,pitch,fov)
            if self.preview_job:
                self.root.after_cancel(self.preview_job)
            self.preview_job=self.root.after(35,self.deferred_preview)
            self.update_detail()
        except (ValueError,tk.TclError):
            pass  # Entrée numérique temporairement incomplète pendant la saisie.

    def deferred_preview(self):
        self.preview_job=None
        self.draw_panorama()
        self.render_preview()

    def render_preview(self):
        if self.pano is None:
            return
        cam=self.camera
        if cam['yaw'] is None:
            self.preview.configure(image='',text='Sujet non positionné : cliquer dans le panorama.')
        else:
            rgb=preview_rgb(self.pano,cam['yaw'],cam['pitch'],cam['h_fov'],384,216)
            self.images['main']=ImageTk.PhotoImage(Image.fromarray(rgb))
            self.preview.configure(image=self.images['main'],text='')
        for index,c in enumerate(self.project.doc['cameras']):
            if c['yaw'] is None:
                self.thumbs[index].configure(image='',text='Non renseigné')
            else:
                rgb=preview_rgb(self.pano,c['yaw'],c['pitch'],c['h_fov'],96,54)
                self.images[index]=ImageTk.PhotoImage(Image.fromarray(rgb))
                self.thumbs[index].configure(image=self.images[index],text='')

    def review(self):
        if self.busy or self.reference is None:
            return
        try:
            self.project.review(self.camera,self.reference,self.visible.get())
            self.update_detail()
            self.status.set('Observation manuelle mémorisée. Enregistrer pour la conserver.')
        except Exception as error:
            self.say_error(error)

    def validate(self):
        if self.busy:
            return
        try:
            self.project.validate_camera(self.camera)
            self.project.save()
            self.update_detail()
            self.status.set('Caméra validée et projet enregistré. Une visibilité partielle reste documentée comme telle.')
        except Exception as error:
            self.say_error(error)

    def save(self):
        if self.busy:
            return
        try:
            self.project.save()
            self.status.set('musiciens.json enregistré (les caméras non validées restent en brouillon).')
        except Exception as error:
            self.say_error(error)

    def save_views(self):
        if self.busy:
            return
        try:
            data=self.project.stage_a_views()
            path=self.project.root/'views.step1.json'
            atomic_json(path,data)
            self.status.set(f'Export compatible avec A : {path}')
        except Exception as error:
            self.say_error(error)

    def link_source(self):
        if self.busy:
            return
        path=filedialog.askopenfilename(title='Export 360 mono équirectangulaire original',filetypes=[('Vidéos','*.mp4 *.mov *.mkv'),('Tous','*.*')],parent=self.root)
        if not path:
            return
        if not messagebox.askyesno('Projection','Confirmez-vous que ce fichier est un export 360 mono équirectangulaire assemblé ?',parent=self.root):
            return
        doc=copy.deepcopy(self.project.doc)
        def done(info):
            self.project.doc['source']=info
            self.project.dirty=True
            self.project.save()
            self.status.set('Source liée. Le fichier original reste en lecture seule.')
        self.background(lambda:attach_source(doc,path,self.ffprobe),done)

    def add_time(self):
        if self.busy:
            return
        try:
            time=float(self.new_time.get().replace(',','.'))
            for index,ref in enumerate(self.project.doc['references']):
                if abs(ref['requested_time_seconds']-time)<1e-6:
                    self.ref_index=index
                    self.refresh_references()
                    return
            doc=copy.deepcopy(self.project.doc)
            def done(path):
                self.project.add_panorama(path,time,'source_seek_ffmpeg')
                self.project.save()
                self.ref_index=len(self.project.doc['references'])-1
                self.refresh_references()
                self.status.set('Nouvel instant ajouté. Vérifier les cinq caméras à cet instant.')
            self.background(lambda:extract_reference(doc,self.project.root/'cache',time,self.ffmpeg,self.ffprobe),done)
        except Exception as error:
            self.say_error(error)

    def save_previews(self):
        if self.busy:
            return
        if not any(c['yaw'] is not None for c in self.project.doc['cameras']):
            self.say_error(ValueError('Positionner au moins une caméra.'))
            return
        self.save()
        snapshot=Project(self.project.root,copy.deepcopy(self.project.doc))
        self.background(lambda:export_previews(snapshot),lambda p:self.status.set(f'Aperçus enregistrés : {p}'))

    def render_clips(self):
        if self.busy:
            return
        try:
            start=float(self.export_start.get().replace(',','.'))
            duration=float(self.export_duration.get().replace(',','.'))
            self.project.save()
            doc=copy.deepcopy(self.project.doc)
            self.background(lambda:export_clips(doc,self.project.root,start,duration,self.ffmpeg,self.ffprobe,
                            progress=lambda s:self.messages.put(('progress',s))),
                            lambda p:self.status.set(f'Cinq extraits terminés : {p}'))
        except Exception as error:
            self.say_error(error)

    def close(self):
        if self.busy:
            messagebox.showinfo('Opération en cours','Attendre la fin de l’extraction ou du rendu avant de fermer.',parent=self.root)
            return
        if self.project.dirty:
            choice=messagebox.askyesnocancel('Quitter','Enregistrer les modifications avant de fermer ?',parent=self.root)
            if choice is None:
                return
            if choice:
                try:
                    self.project.save()
                except Exception as error:
                    self.say_error(error)
                    return
        self.executor.shutdown(wait=False)
        self.root.destroy()
