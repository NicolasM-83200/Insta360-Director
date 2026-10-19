"""Reproducible CPU preview benchmark; no GUI, FFmpeg or user media required."""
import argparse
import json
import platform
import time
import numpy as np
from .profiles import FORMATS, MODES, output_format, preview_size, max_fov
from .project import new_document, atomic_json
from .preview import render_preview


def benchmark(repeats=7):
    if repeats < 2:
        raise ValueError('Au moins deux répétitions requises.')
    u,v=np.meshgrid(np.linspace(0,1,1920),np.linspace(0,1,960))
    pano=np.stack([u*255,v*255,(.5+.5*np.sin(u*20))*255],axis=-1).astype(np.uint8)
    camera=new_document()['cameras'][0]
    camera.update(yaw=35,pitch=15,roll=7)
    records=[]
    for edge in (480,720,960):
        for name in FORMATS:
            output=output_format(name)
            w,h=preview_size(output,edge)
            for mode in MODES:
                camera.update(output=output,projection={'mode':mode},h_fov=min(100,max_fov(mode,w/h)))
                render_preview(pano,camera,w,h)  # warm-up, includes cached coordinate grid
                times=[]
                for _ in range(repeats):
                    start=time.perf_counter()
                    render_preview(pano,camera,w,h)
                    times.append((time.perf_counter()-start)*1000)
                records.append({'mode':mode,'format':name,'size':[w,h],'edge':edge,
                                'median_ms':round(float(np.median(times)),2),
                                'p95_ms':round(float(np.percentile(times,95)),2)})
    return {'python':platform.python_version(),'platform':platform.platform(),
            'processor':platform.processor(),'numpy':np.__version__,'repeats':repeats,
            'input_size':[1920,960],'measurement':'CPU projection + sampling; excludes Tk display and video decoding',
            'cases':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    parser.add_argument('--repeats',type=int,default=7)
    args=parser.parse_args()
    result=benchmark(args.repeats)
    if args.output:
        atomic_json(args.output,result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
