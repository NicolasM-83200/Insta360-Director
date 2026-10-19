"""B.1 workspace; reuses B's import, review, persistence and job handling."""
import copy
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import time
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog
import numpy as np
from PIL import Image, ImageTk
from .ui import MappingApp as BaseMappingApp
from .geometry import uv_to_angles, angles_to_uv, normalized_box, wrap_yaw
from .profiles import (FORMATS, MODES, PREVIEW_EDGES, preview_size, output_format,
                       max_fov, vertical_fov, lens_scale, scale_fov)
from .preview import render_preview, projected_points, framing_warning
from .project import SUBJECTS, VISIBILITY, Project
from .render import export_images, export_clips, extract_reference


class MappingApp(BaseMappingApp):
    def __init__(self, root, project, ffmpeg='ffmpeg', ffprobe='ffprobe'):
        self.preview_executor = ThreadPoolExecutor(max_workers=1)
        self.preview_future = None
        self.preview_pending = None
        self.preview_generation = 0
        self.preview_times = deque(maxlen=60)
        self.orbit_start = None
        self.preview_display_size = (1, 1)
        super().__init__(root, project, ffmpeg, ffprobe)
        root.title('Insta360 Director · B.1 — Cadrage')
        root.minsize(960, 680)
        self.preview_poll_id = root.after(25, self.poll_preview)

    def _build(self):
        self.params['roll'] = tk.DoubleVar(value=0)
        self.format_choice = tk.StringVar(value='16:9')
        self.projection_choice = tk.StringVar(value='Linear')
        self.preview_quality = tk.StringVar(value='Rapide')
        self.res_width = tk.StringVar(value='1920')
        self.res_height = tk.StringVar(value='1080')
        self.history_choice = tk.StringVar()
        self.performance = tk.StringVar(value='Aperçu basse résolution')
        self.coverage = tk.StringVar()
        self.advanced_open = False
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill='both', expand=True)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x')
        for label, command in [('Ouvrir / lier vidéo', self.link_source),
                               ('Importer panorama', self.import_panorama),
                               ('Importer A', self.import_a), ('Enregistrer', self.save)]:
            ttk.Button(toolbar, text=label, command=command).pack(side='left', padx=3)
        subjects = ttk.Frame(outer)
        subjects.pack(fill='x', pady=8)
        self.subject_buttons = []
        for i, (_, label, _) in enumerate(SUBJECTS):
            button = ttk.Button(subjects, text=label, command=lambda n=i:self.choose_camera(n))
            button.pack(side='left', fill='x', expand=True, padx=2)
            self.subject_buttons.append(button)
        body = ttk.Frame(outer)
        body.pack(fill='both', expand=True)
        side = ttk.Frame(body, width=310)
        side.pack(side='right', fill='y', padx=(12,0))
        side.pack_propagate(False)
        scroll_canvas = tk.Canvas(side, width=286, highlightthickness=0)
        scrollbar = ttk.Scrollbar(side, command=scroll_canvas.yview)
        scrollbar.pack(side='right', fill='y')
        scroll_canvas.pack(side='left', fill='both', expand=True)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        panel = ttk.Frame(scroll_canvas, padding=4)
        win = scroll_canvas.create_window((0,0), window=panel, anchor='nw')
        panel.bind('<Configure>', lambda e:scroll_canvas.configure(scrollregion=scroll_canvas.bbox('all')))
        scroll_canvas.bind('<Configure>', lambda e:scroll_canvas.itemconfigure(win, width=e.width))
        self.root.bind('<MouseWheel>', lambda e:scroll_canvas.yview_scroll(-int(e.delta/120), 'units')
                       if str(e.widget).startswith(str(panel)) and not isinstance(e.widget,ttk.Combobox) else None, add='+')
        centre = ttk.Frame(body)
        centre.pack(side='left', fill='both', expand=True)
        self.viewer = tk.Canvas(centre, bg='#101923', highlightthickness=0, height=350)
        self.viewer.pack(fill='both', expand=True)
        self.viewer.bind('<Configure>', lambda e:self.render_preview())
        self.viewer.bind('<ButtonPress-1>', self.orbit_press)
        self.viewer.bind('<B1-Motion>', self.orbit_drag)
        self.viewer.bind('<ButtonRelease-1>', lambda e:setattr(self, 'orbit_start', None))
        self.viewer.bind('<MouseWheel>', self.wheel_zoom)
        self.viewer.bind('<Button-4>', lambda e:self.wheel_zoom(e, 1))
        self.viewer.bind('<Button-5>', lambda e:self.wheel_zoom(e, -1))
        ttk.Label(centre, text='Glisser pour orienter • Molette pour zoomer • Cliquer le panorama pour annoter').pack(anchor='w')
        ttk.Label(centre, textvariable=self.performance).pack(anchor='w')
        row = ttk.Frame(centre)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text='Référence').pack(side='left')
        self.ref_combo = ttk.Combobox(row, textvariable=self.reference_choice, state='readonly', width=23)
        self.ref_combo.pack(side='left', padx=4)
        self.ref_combo.bind('<<ComboboxSelected>>', self.select_reference)
        ttk.Entry(row, textvariable=self.new_time, width=7).pack(side='left')
        ttk.Button(row, text='+ instant (s)', command=self.add_time).pack(side='left', padx=3)
        self.canvas = tk.Canvas(centre, bg='#101923', height=150, highlightthickness=0)
        self.canvas.pack(fill='x')
        self.canvas.bind('<Configure>', lambda e:self.draw_panorama())
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        row = ttk.Frame(centre)
        row.pack(fill='x')
        ttk.Radiobutton(row,text='Point',variable=self.mode,value='point').pack(side='left')
        ttk.Radiobutton(row,text='Zone',variable=self.mode,value='box').pack(side='left')
        ttk.Label(row,text='Jonction').pack(side='left',padx=6)
        ttk.Scale(row,variable=self.offset,from_=0,to=360,command=lambda _:self.draw_panorama()).pack(side='left',fill='x',expand=True)

        def combo(label, variable, values, callback):
            ttk.Label(panel, text=label).pack(anchor='w', pady=(6,2))
            widget = ttk.Combobox(panel,textvariable=variable,values=values,state='readonly')
            widget.pack(fill='x')
            widget.bind('<<ComboboxSelected>>',callback)
            return widget
        combo('Format de sortie',self.format_choice,list(FORMATS),self.change_format)
        row = ttk.Frame(panel)
        row.pack(fill='x',pady=4)
        ttk.Entry(row,textvariable=self.res_width,width=7).pack(side='left')
        ttk.Label(row,text=' × ').pack(side='left')
        ttk.Entry(row,textvariable=self.res_height,width=7).pack(side='left')
        ttk.Button(row,text='Appliquer',command=self.change_resolution).pack(side='right')
        combo('Projection · approximation Studio',self.projection_choice,list(MODES),self.change_projection)
        ttk.Label(panel,text='Linear : lignes droites · Dewarp : cylindre\nUltra : stéréographique · Mega : fisheye',wraplength=270).pack(anchor='w',pady=4)
        ttk.Label(panel,text='Champ de vision / zoom').pack(anchor='w')
        self.zoom_scale = ttk.Scale(panel,variable=self.params['h_fov'],from_=10,to=160,command=lambda _:self.parameters_changed())
        self.zoom_scale.pack(fill='x')
        combo('Qualité de l’aperçu',self.preview_quality,list(PREVIEW_EDGES),lambda e:self.render_preview())
        ttk.Label(panel,textvariable=self.coverage,wraplength=270,foreground='#986000').pack(anchor='w',pady=6)
        row = ttk.Frame(panel)
        row.pack(fill='x',pady=3)
        ttk.Button(row,text='Mémoriser',command=self.remember).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Restaurer',command=self.restore).pack(side='left',fill='x',expand=True)
        self.history_combo = combo('Cadrages mémorisés',self.history_choice,[],lambda e:None)
        ttk.Label(panel,textvariable=self.detail,wraplength=270).pack(anchor='w',pady=5)
        combo('Visibilité à cette référence',self.visible,VISIBILITY,lambda e:None)
        ttk.Button(panel,text='Enregistrer observation',command=self.review).pack(fill='x',pady=3)
        ttk.Button(panel,text='Valider cette caméra',command=self.validate).pack(fill='x')
        export = ttk.LabelFrame(panel,text='Exports de validation',padding=5)
        export.pack(fill='x',pady=8)
        ttk.Button(export,text='PNG du sujet · résolution finale',command=self.render_image).pack(fill='x')
        row = ttk.Frame(export)
        row.pack(fill='x',pady=5)
        ttk.Label(row,text='Début / durée (s)').pack(side='left')
        ttk.Entry(row,textvariable=self.export_start,width=6).pack(side='left',padx=2)
        ttk.Entry(row,textvariable=self.export_duration,width=6).pack(side='left')
        ttk.Button(export,text='MP4 du sujet',command=lambda:self.render_clips(single=True)).pack(fill='x')
        ttk.Button(export,text='5 MP4 · caméras validées',command=self.render_clips).pack(fill='x',pady=3)
        ttk.Button(export,text='Aperçus PNG · toutes les références',command=self.save_previews).pack(fill='x')
        self.advanced_button = ttk.Button(panel,text='▸ Réglages avancés',command=self.toggle_advanced)
        self.advanced_button.pack(fill='x',pady=4)
        self.advanced = ttk.Frame(panel)
        for name,lo,hi in [('yaw',-180,180),('pitch',-90,90),('roll',-180,180),('h_fov',10,240)]:
            row=ttk.Frame(self.advanced)
            row.pack(fill='x',pady=2)
            ttk.Label(row,text=name,width=10).pack(side='left')
            spin=ttk.Spinbox(row,textvariable=self.params[name],from_=lo,to=hi,increment=.5,width=10,command=self.parameters_changed)
            spin.pack(side='right')
            spin.bind('<Return>',lambda e:self.parameters_changed())
            spin.bind('<FocusOut>',lambda e:self.parameters_changed())
        ttk.Button(self.advanced,text='Exporter views compatible A',command=self.save_views).pack(fill='x',pady=4)
        ttk.Separator(outer).pack(fill='x',pady=5)
        ttk.Label(outer,textvariable=self.status,wraplength=1100).pack(anchor='w')
        ttk.Label(outer,text=str(self.project.root),wraplength=1100).pack(anchor='w')

    def choose_camera(self, index):
        self.orbit_start = None
        self.camera_index = index
        self.sync_camera()

    def sync_camera(self):
        self.updating=True
        c=self.camera
        for key,var in self.params.items():
            var.set(c[key] if c[key] is not None else 0)
        self.format_choice.set(c['output']['format'])
        self.res_width.set(str(c['output']['width']))
        self.res_height.set(str(c['output']['height']))
        self.projection_choice.set(c['projection']['mode'])
        self.zoom_scale.configure(to=max_fov(c['projection']['mode'],c['output']['width']/c['output']['height']))
        self.history_combo['values']=[f"{i+1} · {h['label']}" for i,h in enumerate(c['saved_framings'])]
        if c['saved_framings']:
            self.history_combo.current(len(c['saved_framings'])-1)
        else:
            self.history_choice.set('')
        for i,button in enumerate(self.subject_buttons):
            button.state(['pressed'] if i==self.camera_index else ['!pressed'])
        self.updating=False
        self.draw_panorama()
        self.render_preview()
        self.update_detail()

    def update_detail(self):
        self.visible.set('')
        super().update_detail()
        self.detail.set(self.detail.get().split(' FOV :')[0])
        self.coverage.set(framing_warning(self.camera,self.reference['id']) if self.reference else 'Importer une référence pour commencer.')

    def toggle_advanced(self):
        self.advanced_open = not self.advanced_open
        if self.advanced_open:
            self.advanced.pack(fill='x')
        else:
            self.advanced.pack_forget()
        self.advanced_button.configure(text=('▾' if self.advanced_open else '▸')+' Réglages avancés')

    def change_format(self,event=None):
        if self.busy:
            self.sync_camera()
            return
        try:
            warning=self.project.set_output(self.camera,self.format_choice.get())
            self.sync_camera()
            self.status.set(warning or 'Ratio modifié : orientation conservée, couverture élargie. Vérifier le sujet.')
        except Exception as e:
            self.say_error(e)

    def change_resolution(self):
        if self.busy:
            return
        try:
            self.project.set_output(self.camera,self.format_choice.get(),int(self.res_width.get()),int(self.res_height.get()))
            self.sync_camera()
        except Exception as e:
            self.say_error(e)

    def change_projection(self,event=None):
        if self.busy:
            self.sync_camera()
            return
        try:
            self.project.set_projection(self.camera,self.projection_choice.get())
            self.sync_camera()
            self.status.set('Projection modifiée. Vérifier le cadrage et ses observations.')
        except Exception as e:
            self.say_error(e)

    def parameters_changed(self):
        if self.updating or self.pano is None or self.busy:
            return
        try:
            values={k:v.get() for k,v in self.params.items()}
            if all(values[k]==self.camera[k] for k in values):
                return
            self.project.change_camera(self.camera,values['yaw'],values['pitch'],values['h_fov'],roll=values['roll'])
            self.draw_panorama()
            self.render_preview()
            self.update_detail()
        except (ValueError,tk.TclError):
            self.status.set('Valeur incomplète ou hors limites ; le cadrage reste inchangé.')

    def orbit_press(self,event):
        if not self.busy and self.pano is not None and self.camera['yaw'] is not None:
            self.orbit_start=(event.x,event.y,self.camera['yaw'],self.camera['pitch'])

    def orbit_drag(self,event):
        if self.busy or self.orbit_start is None:
            return
        x,y,yaw,pitch=self.orbit_start
        w,h=self.preview_display_size
        vfov=vertical_fov(self.camera['projection']['mode'],self.camera['h_fov'],self.camera['output']['width']/self.camera['output']['height'])
        self.params['yaw'].set(wrap_yaw(yaw-(event.x-x)*self.camera['h_fov']/max(1,w)))
        self.params['pitch'].set(max(-90,min(90,pitch+(event.y-y)*vfov/max(1,h))))
        self.parameters_changed()

    def wheel_zoom(self,event,direction=None):
        if self.busy or self.pano is None or self.camera['yaw'] is None:
            return 'break'
        amount=direction if direction is not None else event.delta/120
        aspect=self.camera['output']['width']/self.camera['output']['height']
        self.params['h_fov'].set(max(10,min(max_fov(self.camera['projection']['mode'],aspect),self.camera['h_fov']*1.08**(-amount))))
        self.parameters_changed()
        return 'break'

    def draw_panorama(self):
        if self.pano is None:
            return
        # Reference strip remains a true 2:1 panorama with letterboxing.
        available=max(2,self.canvas.winfo_width())
        w=min(available,400)
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
        for c in self.project.doc['cameras']:
            if c['yaw'] is None:
                continue
            u,v=angles_to_uv(c['yaw'],c['pitch'])
            x,y=((u-offset)%1)*w,v*h
            colour='#00ffe0' if c is self.camera else '#ffff80'
            self.canvas.create_line(x-5,y,x+5,y,fill=colour,width=2)
            self.canvas.create_line(x,y-5,x,y+5,fill=colour,width=2)
        if self.reference:
            a=next((a for a in self.camera['annotations'] if a['reference_id']==self.reference['id']),None)
            if a:
                point=a['point']
                x,y=((point['u']-offset)%1)*w,point['v']*h
                self.canvas.create_oval(x-4,y-4,x+4,y+4,outline='#ffffff',width=2)
                if a.get('bbox'):
                    b=a['bbox']; start=(b['u_start']-offset)%1; end=start+b['u_span']
                    for lo,hi in [(start,min(end,1)),(0,max(0,end-1))]:
                        if hi>lo:
                            self.canvas.create_rectangle(lo*w,b['v_top']*h,hi*w,b['v_bottom']*h,outline='#ffffff')
        if available>w+70:
            self.canvas.create_text(w+12,15,anchor='nw',width=available-w-20,fill='#d9e4ef',
                                    text='Panorama de référence\n+ : direction caméra\n○ : annotation du sujet\n\nGlisser une zone pour\nproposer un cadrage.')

    def press(self,event):
        if event.x>self.canvas_size[0] or event.y>self.canvas_size[1]:
            return
        super().press(event)

    def release(self,event):
        if self.drag_start is None or self.pano is None or self.busy:
            return
        start=self.drag_start
        self.drag_start=None
        try:
            u,v=self.uv_event(event)
            box=None
            if self.mode.get()=='box' and abs(event.x-start[1])+abs(event.y-start[2])>5:
                box=normalized_box(start[0],(u,v))
                u=(box['u_start']+box['u_span']/2)%1
                v=(box['v_top']+box['v_bottom'])/2
            yaw,pitch=uv_to_angles(u,v)
            self.project.change_camera(self.camera,yaw,pitch,self.camera['h_fov'])
            if box:
                us,vs=np.meshgrid(np.linspace(box['u_start'],box['u_start']+box['u_span'],33),np.linspace(box['v_top'],box['v_bottom'],33))
                nx,ny,_=projected_points(self.camera,us,vs)
                mode=self.camera['projection']['mode']
                desired=scale_fov(mode,lens_scale(mode,self.camera['h_fov'])*max(np.abs(nx).max(),np.abs(ny).max())*1.12)
                aspect=self.camera['output']['width']/self.camera['output']['height']
                self.project.change_camera(self.camera,yaw,pitch,max(10,min(max_fov(mode,aspect),desired)),'manual_bbox_geometric_suggestion')
            self.project.annotate(self.camera,self.reference,u,v,box)
            self.sync_camera()
            self.status.set('Cadrage ajusté. Vérifier la zone du sujet, puis mémoriser ou enregistrer.')
        except Exception as e:
            self.say_error(e)

    @staticmethod
    def compute_preview(pano,camera,w,h):
        start=time.perf_counter()
        rgb=render_preview(pano,camera,w,h)
        return rgb,(time.perf_counter()-start)*1000

    def render_preview(self):
        if not hasattr(self,'viewer'):
            return
        self.preview_generation+=1
        if self.pano is None or self.camera['yaw'] is None:
            self.preview_pending=None
            self.viewer.delete('all')
            self.viewer.create_text(max(1,self.viewer.winfo_width())//2,max(1,self.viewer.winfo_height())//2,
                                    text='Sélectionner un sujet, puis cliquer sa position dans le panorama.',
                                    fill='#e2edf7',width=450)
            return
        output=self.camera['output']
        cw,ch=max(1,self.viewer.winfo_width()-12),max(1,self.viewer.winfo_height()-12)
        aspect=output['width']/output['height']
        w,h=(int(ch*aspect),ch) if cw/ch>aspect else (cw,int(cw/aspect))
        self.preview_display_size=(max(1,w),max(1,h))
        edge=min(PREVIEW_EDGES[self.preview_quality.get()],max(w,h))
        rw,rh=preview_size(output,max(64,edge))
        key=(self.reference['id'] if self.reference else None,self.camera['id'],
             output['format'],self.camera['projection']['mode'])
        self.preview_view_key=key
        self.preview_pending=(self.preview_generation,key,self.pano,copy.deepcopy(self.camera),rw,rh)

    def poll_preview(self):
        if self.preview_future and self.preview_future.done():
            try:
                rgb,ms=self.preview_future.result()
                if (self.camera['yaw'] is not None and self.preview_running_key==getattr(self,'preview_view_key',None)):
                    w,h=self.preview_display_size
                    self.images['main']=ImageTk.PhotoImage(Image.fromarray(rgb).resize((w,h),Image.Resampling.BILINEAR))
                    self.viewer.delete('all')
                    self.viewer.create_image(self.viewer.winfo_width()//2,self.viewer.winfo_height()//2,image=self.images['main'])
                    self.preview_times.append(ms)
                    self.performance.set(f'Aperçu {rgb.shape[1]}×{rgb.shape[0]} · calcul {ms:.0f} ms · médiane {np.median(self.preview_times):.0f} ms')
            except Exception as e:
                self.status.set(f'Aperçu : {e}')
            self.preview_future=None
        if self.preview_future is None and self.preview_pending is not None:
            generation,key,pano,camera,w,h=self.preview_pending
            self.preview_pending=None
            self.preview_running_generation=generation
            self.preview_running_key=key
            self.preview_future=self.preview_executor.submit(self.compute_preview,pano,camera,w,h)
        self.preview_poll_id=self.root.after(25,self.poll_preview)

    def remember(self):
        if self.busy:
            return
        try:
            self.project.remember_framing(self.camera)
            self.project.save()
            self.sync_camera()
            self.status.set('Cadrage mémorisé et sauvegardé. Les annotations restent distinctes.')
        except Exception as e:
            self.say_error(e)

    def restore(self):
        if self.busy:
            return
        try:
            if self.history_combo.current()<0:
                raise ValueError('Aucun cadrage mémorisé pour ce sujet.')
            self.project.restore_framing(self.camera,self.history_combo.current())
            self.sync_camera()
            self.status.set('Cadrage restauré en mémoire. Vérifier puis enregistrer.')
        except Exception as e:
            self.say_error(e)

    def import_panorama(self):
        if self.busy:
            return
        path=filedialog.askopenfilename(title='Panorama équirectangulaire 2:1',filetypes=[('Images','*.png *.jpg *.jpeg'),('Tous','*.*')],parent=self.root)
        if not path:
            return
        seconds=simpledialog.askfloat('Instant','Instant de cette image dans la vidéo (secondes) :',minvalue=0,parent=self.root)
        if seconds is None:
            return
        try:
            source=self.project.doc.get('source')
            if source and seconds>=source['duration_seconds']:
                raise ValueError('Instant en dehors de la vidéo liée.')
            self.project.add_panorama(path,seconds)
            self.project.save()
            self.ref_index=len(self.project.doc['references'])-1
            self.refresh_references()
        except Exception as e:
            self.say_error(e)

    def link_source(self):
        # B's linking workflow checks identity and explicitly confirms projection.
        super().link_source()
        self.load_first_when_linked = self.busy and not self.project.doc['references']

    def poll(self):
        super().poll()
        if getattr(self,'load_first_when_linked',False) and not self.busy:
            self.load_first_when_linked=False
            if self.project.doc.get('source') and not self.project.doc['references']:
                self.new_time.set('0')
                self.add_time()

    def render_image(self):
        if self.busy or self.reference is None:
            return
        try:
            self.project.save()
            snapshot=Project(self.project.root,self.project.doc)
            reference_id=self.reference['id']
            camera_id=self.camera['id']
            self.background(lambda:export_images(snapshot,reference_id,[camera_id],self.ffmpeg,self.ffprobe),
                            lambda p:self.status.set(f'PNG final : {p}'))
        except Exception as e:
            self.say_error(e)

    def render_clips(self,single=False):
        if self.busy:
            return
        try:
            start=float(self.export_start.get().replace(',','.'))
            duration=float(self.export_duration.get().replace(',','.'))
            self.project.save()
            doc=copy.deepcopy(self.project.doc)
            ids=[self.camera['id']] if single else None
            self.background(lambda:export_clips(doc,self.project.root,start,duration,self.ffmpeg,self.ffprobe,
                            camera_ids=ids,progress=lambda s:self.messages.put(('progress',s))),
                            lambda p:self.status.set(f'Export terminé : {p}'))
        except Exception as e:
            self.say_error(e)

    def close(self):
        super().close()
        try:
            alive=self.root.winfo_exists()
        except tk.TclError:
            alive=False
        if not alive:
            self.preview_executor.shutdown(wait=False,cancel_futures=True)
