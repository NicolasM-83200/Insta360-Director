"""Tk interaction smoke tests on synthetic data; no video or user project modified."""
import copy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tkinter as tk
from PIL import Image
from mapping360.project import Project
from mapping360.ui_studio import MappingApp


class StudioUITests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError as e:
            self.skipTest(f'Affichage Tk indisponible : {e}')
        self.root.withdraw()
        self.tmp=tempfile.TemporaryDirectory(prefix='B1 interface é ')
        root=Path(self.tmp.name)
        Image.new('RGB',(640,320),'navy').save(root/'pano.png')
        self.project=Project.create(root)
        self.ref=self.project.add_panorama(root/'pano.png',0)
        self.app=MappingApp(self.root,self.project)
        self.app.say_error=lambda e: self.fail(str(e))
        self.root.update()

    def tearDown(self):
        if not hasattr(self,'app'):
            return
        self.project.dirty=False
        self.app.close()
        self.app.preview_executor.shutdown(wait=True)
        self.tmp.cleanup()

    def test_point_drag_zoom_ratio_roll_history_and_preview(self):
        app=self.app
        app.canvas_size=(400,200)
        app.press(SimpleNamespace(x=200,y=100))
        app.release(SimpleNamespace(x=200,y=100))
        self.assertEqual(app.camera['yaw'],0)
        annotation=copy.deepcopy(app.camera['annotations'])
        app.preview_display_size=(400,225)
        app.orbit_press(SimpleNamespace(x=200,y=100))
        app.orbit_drag(SimpleNamespace(x=230,y=110))
        self.assertNotEqual(app.camera['yaw'],0)
        self.assertEqual(app.camera['annotations'],annotation)
        fov=app.camera['h_fov']
        app.wheel_zoom(SimpleNamespace(delta=120))
        self.assertLess(app.camera['h_fov'],fov)
        app.params['roll'].set(12)
        app.parameters_changed()
        self.assertEqual(app.camera['roll'],12)
        app.remember()
        saved=copy.deepcopy(app.camera)
        app.format_choice.set('9:16')
        app.change_format()
        self.assertEqual(app.camera['output']['height'],1920)
        app.projection_choice.set('Mega')
        app.change_projection()
        app.restore()
        self.assertEqual(app.camera['output'],saved['output'])
        self.assertEqual(app.camera['projection'],saved['projection'])
        app.toggle_advanced()
        self.assertTrue(app.advanced_open)
        app.render_preview()
        deadline=time.monotonic()+3
        while not app.preview_times and time.monotonic()<deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(app.preview_times)
        app.choose_camera(2)
        self.assertEqual(app.camera['id'],'bassiste')
        self.assertEqual(app.visible.get(),'')

    def test_box_and_all_format_mode_controls(self):
        app=self.app
        app.canvas_size=(400,200)
        app.mode.set('box')
        app.press(SimpleNamespace(x=180,y=80))
        app.release(SimpleNamespace(x=220,y=120))
        self.assertIsNotNone(app.camera['annotations'][0]['bbox'])
        for name in ('16:9','9:16','4:3','3:4','1:1','2.35:1'):
            app.format_choice.set(name)
            app.change_format()
            for mode in ('Mega','Ultra','Dewarp','Linear'):
                app.projection_choice.set(mode)
                app.change_projection()
                self.assertEqual(app.camera['output']['format'],name)
                self.assertEqual(app.camera['projection']['mode'],mode)
        app.visible.set('partiel')
        app.review()
        app.validate()
        self.assertTrue(app.camera['validated'])
        self.assertEqual(Project.load(self.project.root).doc,self.project.doc)
