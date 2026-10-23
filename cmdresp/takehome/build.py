"""Reproduce the complete flow; use --through model/csim/csynth/cosim/trace/report.

Invoke with the course virtual environment's Python. Vitis must be on PATH.
Existing expensive Vitis stages are not repeated unless --rerun is supplied.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def generate():
    from waveflow.build.build import BuildConfig
    from waveflow.build.streamutils import StreamUtilsStep
    result=StreamUtilsStep(output_dir='include').run(BuildConfig(root_dir=ROOT,vitis_version='2026.1'))
    if not result.success:
        raise RuntimeError(result.message)
    (ROOT/'evidence').mkdir(exist_ok=True)
    info={'python':sys.version,'python_executable':sys.executable,
          'waveflow':importlib.metadata.version('waveflow'),
          'numpy':importlib.metadata.version('numpy'),
          'fpga':'xc7z020clg484-1','requested_clock_ns':10,
          'reference':'https://github.com/sdrangan/waveflow/blob/main/examples/stream_inband/run.tcl',
          'mcp':'Not connected; read public upstream reference source and local installed Waveflow instead.'}
    (ROOT/'evidence/environment.txt').write_text(json.dumps(info,indent=2)+'\n')
    version=subprocess.run(['vitis-run','--version'],cwd=ROOT,capture_output=True,text=True,check=True)
    (ROOT/'evidence/tool_version.txt').write_text(version.stdout+version.stderr)
    subprocess.run([sys.executable,str(ROOT/'verify_model.py')],cwd=ROOT,check=True)


def run_stage(stage,rerun=False):
    marker=ROOT/'evidence'/f'{stage}_complete.txt'
    if marker.exists() and not rerun:
        print(f'{stage}: completed earlier, skipping (use --rerun to repeat)',flush=True)
        return
    env=os.environ.copy(); env['MAXAFFINE_STAGE']=stage
    log=ROOT/'evidence'/f'{stage}_vitis.txt'
    print(f'Running {stage}; full log: {log}',flush=True)
    with log.open('w') as f:
        proc=subprocess.run(['vitis-run','--mode','hls','--tcl','run.tcl'],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
    if proc.returncode or f'MAXAFFINE_SUCCESS {stage}' not in log.read_text():
        raise RuntimeError(f'{stage} failed: inspect {log}')
    marker.write_text(f'PASS: Vitis stage {stage} completed; see {log.name}\n')
    if stage=='csynth':
        for name in ['maxaffine_csynth.rpt','maxaffine_csynth.xml',
                     'maxaffine_Pipeline_line_loop_csynth.rpt']:
            source=ROOT/'maxaffine_proj/solution1/syn/report'/name
            shutil.copyfile(source,ROOT/'evidence'/(name+'.txt'))
        shutil.copyfile(ROOT/'maxaffine_proj/solution1/syn/verilog/maxaffine_control_s_axi.v',
                        ROOT/'evidence/control_registers.v.txt')
    if stage=='cosim':
        source=ROOT/'maxaffine_proj/solution1/sim/report/maxaffine_cosim.rpt'
        shutil.copyfile(source,ROOT/'evidence/cosim_report.txt')
    print(f'{stage}: PASS',flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--through',choices=['model','csim','csynth','cosim','trace','report'],default='report')
    p.add_argument('--rerun',action='store_true')
    args=p.parse_args()
    generate()
    for stage in ['model','csim','csynth','cosim','trace','report']:
        if stage in ['csim','csynth','cosim']:
            run_stage(stage,args.rerun)
        if stage=='report':
            subprocess.run([sys.executable,str(ROOT/'analyze.py')],cwd=ROOT,check=True)
        if stage=='trace' and (args.rerun or not (ROOT/'evidence/trace_complete.txt').exists()):
            with (ROOT/'evidence/waveform_replay.txt').open('w') as log:
                subprocess.run([sys.executable,str(ROOT/'extract_waveform.py')],cwd=ROOT,check=True,
                               stdout=log,stderr=subprocess.STDOUT)
        if args.through==stage: break


if __name__=='__main__':
    main()
