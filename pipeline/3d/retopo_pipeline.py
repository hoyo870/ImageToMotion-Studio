"""Instant Meshes + Blender postprocess; also reusable without ComfyUI."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parent


def preflight_tools():
    for path in (ROOT/'tools/InstantMeshes/Instant Meshes.exe',
                 ROOT/'Blender/blender-4.5.9-windows-x64/blender.exe',
                 ROOT/'retopo_bake.py', ROOT/'prepare_retopology.py', ROOT/'cleanup_mesh.py'):
        if not path.is_file(): raise FileNotFoundError(path)


def obj_vertices(path):
    with path.open(encoding='utf-8',errors='strict') as handle:
        return sum(line.startswith('v ') for line in handle)


def blender_failure(path):
    lines=Path(path).read_text(encoding='utf-8',errors='replace').splitlines()
    return next((line[:600] for line in reversed(lines)
                 if line.startswith(('ValueError:','RuntimeError:','FileNotFoundError:','MemoryError:'))),
                'Blender 실행 로그 확인 필요')


def run_retopology(directory,mode):
    preflight_tools()
    directory=Path(directory)
    exe=ROOT/'tools/InstantMeshes/Instant Meshes.exe'
    blender=ROOT/'Blender/blender-4.5.9-windows-x64/blender.exe'
    source=directory/'model_textured.glb'
    geometry=directory/'cleanup/geometry_for_retopology.obj'
    for path in (exe,blender,source,geometry):
        if not path.is_file(): raise FileNotFoundError(path)
    if mode not in ('single','multi'): raise ValueError('Unknown view mode')
    lower,upper=(1000,1500) if mode=='single' else (2000,3000)
    desired=(lower+upper)//2; request_count=desired*2
    output=directory/'retopology'; output.mkdir(exist_ok=True)
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    attempts=[]; selected=None; instant_failure=None; started=time.monotonic()
    flags=dict(stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,cwd=ROOT)
    cleanup_report=json.loads((directory/'cleanup/cleanup_report.json').read_text(encoding='utf-8'))
    repair_needed=any(item['after']['multi_face_edges' if 'multi_face_edges' in item['after'] else 'edges_with_more_than_two_faces'] for item in cleanup_report['objects'])
    if repair_needed:
        with (output/'input_repair.log').open('wb') as log:
            process=subprocess.run([str(blender),'--background','--factory-startup','--python-exit-code','1',
                '--python',str(ROOT/'prepare_retopology.py'),'--','--source',str(directory/'cleanup/model_cleaned.glb'),
                '--output',str(output)],stdout=log,stderr=subprocess.STDOUT,**flags)
        if process.returncode: raise RuntimeError('Retopology input repair failed: '+str(output/'input_repair.log'))
        geometry=output/'retopo_input.obj'
    for index in range(6):
        candidate=output/f'candidate_{index+1}_{request_count}.obj'
        command=[str(exe),str(geometry),'-o',str(candidate),'-v',str(request_count),
                 '-r','4','-p','4','-D','-b','-S','2','-t','1','-d']
        with (output/f'instant_meshes_{index+1}.log').open('wb') as log:
            try:
                process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=120,**flags)
            except subprocess.TimeoutExpired:
                instant_failure='Instant Meshes timed out after 120 seconds'
                selected=geometry
                attempts.append(dict(requested=request_count,error=instant_failure,command=command))
                break
        if process.returncode or not candidate.is_file():
            raise RuntimeError('Instant Meshes failed; see '+str(output/f'instant_meshes_{index+1}.log'))
        count=obj_vertices(candidate)
        attempts.append(dict(requested=request_count,actual=count,file=candidate.name,command=command))
        # Preserve thin geometry with a denser field first. Blender then reduces
        # the extracted surface to the final budget (quad-dominant, not all quads).
        if count>=lower:
            selected=candidate; break
        if not count: raise RuntimeError('Empty retopology result')
        new_count=max(50,round(request_count*desired/count))
        if new_count==request_count: new_count+=10 if count<lower else -10
        request_count=new_count
    (output/'attempts.json').write_text(json.dumps(attempts,indent=2),encoding='utf-8')
    if selected is None: raise RuntimeError('Vertex budget not reached in 6 attempts: '+str(attempts))
    # Clear prior rejection markers before deciding whether this run needs fallback.
    rejection=output/'shape_rejected.json'
    rejection.unlink(missing_ok=True)
    (output/'retopo_report.json').unlink(missing_ok=True)
    with (output/'blender_bake.log').open('wb') as log:
        process=subprocess.run([str(blender),'--background','--factory-startup','--python-exit-code','1',
            '--python',str(ROOT/'retopo_bake.py'),'--','--source',str(source),'--retopo',str(selected),
            '--output',str(output),'--minimum',str(lower),'--maximum',str(upper),
            '--method','surface_fallback' if instant_failure else 'instant_meshes'],
            stdout=log,stderr=subprocess.STDOUT,**flags)
    fallback=None; original_surface_retry=None
    if process.returncode and rejection.is_file() and not instant_failure:
        fallback=json.loads(rejection.read_text(encoding='utf-8'))
        # Instant Meshes can lose thin parts/components. Reduce its source surface
        # directly (conditioned when needed), under the same shape gate.
        with (output/'blender_surface_fallback.log').open('wb') as log:
            process=subprocess.run([str(blender),'--background','--factory-startup','--python-exit-code','1',
                '--python',str(ROOT/'retopo_bake.py'),'--','--source',str(source),
                '--retopo',str(geometry),
                '--output',str(output),'--minimum',str(lower),'--maximum',str(upper),
                '--method','surface_fallback'],stdout=log,stderr=subprocess.STDOUT,**flags)
    failure_log=output/'blender_surface_fallback.log' if fallback else output/'blender_bake.log'
    if process.returncode and repair_needed:
        reason=blender_failure(failure_log)
        if 'Final geometric vertex budget exceeded' in reason or 'Shape preservation failed' in reason:
            original_surface_retry=reason
            failure_log=output/'blender_original_surface.log'
            with failure_log.open('wb') as log:
                process=subprocess.run([str(blender),'--background','--factory-startup','--python-exit-code','1',
                    '--python',str(ROOT/'retopo_bake.py'),'--','--source',str(source),
                    '--retopo',str(directory/'cleanup/geometry_for_retopology.obj'),
                    '--output',str(output),'--minimum',str(lower),'--maximum',str(upper),
                    '--method','surface_fallback'],stdout=log,stderr=subprocess.STDOUT,**flags)
    if process.returncode or not (output/'retopo_report.json').is_file():
        raise RuntimeError('후처리 실패: '+blender_failure(failure_log)+'; 원본 보존. 로그: '+str(failure_log))
    import trimesh
    import numpy as np
    scene=trimesh.load(output/'model_final.glb',force='scene',process=False)
    exported=0
    for mesh in scene.geometry.values():
        if not np.isfinite(mesh.vertices).all() or not np.isfinite(mesh.visual.uv).all():
            raise RuntimeError('Invalid final coordinates/UV')
        for texture in (mesh.visual.material.baseColorTexture,mesh.visual.material.metallicRoughnessTexture):
            if texture is None or texture.size!=(2048,2048): raise RuntimeError('Missing final 2048 map')
        exported+=len(mesh.vertices)
    if not scene.geometry or source_hash!=hashlib.sha256(source.read_bytes()).hexdigest():
        raise RuntimeError('Missing output or source changed')
    report=json.loads((output/'retopo_report.json').read_text(encoding='utf-8'))
    report.update(mode=mode,exported_glb_vertices=exported,source_sha256=source_hash,
                  seconds=time.monotonic()-started,attempts=attempts)
    report['instant_meshes_shape_rejection']=fallback
    report['instant_meshes_failure']=instant_failure
    report['original_surface_retry']=original_surface_retry
    report['input_repair']=json.loads((output/'input_repair.json').read_text(encoding='utf-8')) if repair_needed else None
    (output/'retopo_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (output/'REVIEW.txt').write_text(
        '리토폴로지·2048 텍스처 재베이킹 완료 (수동 보수 검토 필요)\n'
        f'Blender 정점 {report["geometry"]["vertices"]}, 내보낸 GLB 정점 {exported}\n'
        f'보수 검토: 경계 에지 {report["geometry"]["boundary_edges"]}, 비정상 연결 에지 {report["geometry"]["multi_face_edges"]}\n'
        'model_final.blend: LOW_Final은 최종 모델. HIGH_Source는 숨겨진 원본 참조.\n'
        f'사용 방식: {report["method"]}\n'
        '관절 변형, 손가락, 옷의 개구부, 교차 면, 텍스처 이음새를 검토할 것.\n'
        '연결 결함이 있으면 형상 복사본에 Voxel 보수를 적용하며, 좁은 틈/개구부가 닫힐 수 있음.\n'
        '원본 고밀도 GLB는 변경하지 않음. 편집 후 토폴로지 변경 시 다시 UV/베이킹 필요.\n',encoding='utf-8')
    return report


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('directory'); p.add_argument('--mode',choices=['single','multi'],required=True)
    a=p.parse_args(); print(json.dumps(run_retopology(a.directory,a.mode),indent=2))
