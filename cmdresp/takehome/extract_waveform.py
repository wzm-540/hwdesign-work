"""Waveflow XSIM replay solely to export VCD; no cosim_design invocation.

It uses the already compiled snapshot and the exact same activation suite.
Raw RTL replay outputs are preserved for independent comparison by analyze.py.
"""
import gzip
from pathlib import Path
import re
import shutil
from waveflow.scripts.xsim_vcd import modify_tcl, create_vcd_batch, run_batch

ROOT=Path(__file__).resolve().parent


def main():
    sim=ROOT/'maxaffine_proj/solution1/sim/verilog'
    tcl=sim/'maxaffine_vcd.tcl'
    # A wildcard over all internal objects includes unsupported array objects
    # in 2026.1. Use Waveflow's port selection plus specific scalar control nets.
    modify_tcl(sim/'maxaffine.tcl',tcl,'port')
    content=tcl.read_text()
    extra=''.join(f'log_vcd [get_objects /apatb_maxaffine_top/AESL_inst_maxaffine/{name}]\n'
                  for name in ['ap_start','ap_done','ap_idle','ap_ready'])
    tcl.write_text(content.replace('run all\n',extra+'run all\n'))
    launcher=sim/'run_xsim_vcd.sh'
    create_vcd_batch('maxaffine',sim/'run_xsim.sh',launcher)
    run_batch(launcher)
    preserve_capture()


def preserve_capture():
    """Validate/copy an existing completed capture without replaying RTL."""
    sim=ROOT/'maxaffine_proj/solution1/sim/verilog'
    path=sim/'dump.vcd'
    with path.open('rb') as f:
        f.seek(max(0,path.stat().st_size-131072))
        times=re.findall(rb'(?m)^#(\d+)',f.read())
    if not times or int(times[-1])<=0:
        raise RuntimeError('XSIM did not run: VCD contains no elapsed time')
    with path.open('rb') as src, gzip.open(ROOT/'evidence/rtl_trace.vcd.gz','wb') as dst:
        shutil.copyfileobj(src,dst)
    rawdir=ROOT/'maxaffine_proj/solution1/sim/tv/rtldatafile'
    for p in rawdir.glob('rtl.maxaffine.autotvout_*.dat'):
        shutil.copyfile(p,ROOT/'evidence'/('replay_'+p.name+'.txt'))
    (ROOT/'evidence/trace_complete.txt').write_text('PASS: compiled XSIM snapshot replayed and VCD exported\n')
    print('Waveform extraction completed: evidence/rtl_trace.vcd.gz')


if __name__=='__main__':
    main()
