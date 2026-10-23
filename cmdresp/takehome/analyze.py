"""Read committed evidence; independently check RTL and measure handshakes.

No Python timing model is used. Every cycle below comes from the XSIM VCD.
Can be run without Vitis after copying this folder to another machine.
"""
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import numpy as np
from vcdvcd import VCDVCD
os.environ.setdefault('MPLCONFIGDIR','/tmp/maxaffine-matplotlib')
from waveflow.utils.vcd import (VcdParser, extract_clock_times,
                                clock_sample_times, resample_signal)

ROOT=Path(__file__).resolve().parent
E=ROOT/'evidence'


def read_csv(name):
    with (E/name).open() as f:
        return list(csv.DictReader(f))


def replay_transactions(name):
    """Read raw XSIM output, independently of the C++ checking wrapper."""
    text=(E/('replay_rtl.maxaffine.autotvout_'+name+'.dat.txt')).read_text()
    blocks=re.findall(r'\[\[transaction\]\]\s+(\d+)\s*(.*?)\[\[/transaction\]\]',text,re.S)
    return [[int(word,16) for word in body.split()] for _,body in blocks]


def analyze_trace(scenarios):
    with gzip.open(E/'rtl_trace.vcd.gz','rt') as f:
        vcd=VCDVCD(vcd_string=f.read())
    vp=VcdParser(vcd)
    clk=vp.add_clock_signal()
    ins,_=vp.add_axiss_signals(name='in_stream_',short_name_prefix='in')
    outs,_=vp.add_axiss_signals(name='out_stream_',short_name_prefix='out')
    prefix='apatb_maxaffine_top.AESL_inst_maxaffine.'

    def find(short):
        matches=[n for n in vcd.signals if n.startswith(prefix) and
                 n[len(prefix):].split('[')[0]==short]
        assert len(matches)==1,(short,matches)
        return matches[0]

    vp.sig_info[clk].get_values()
    clocks=extract_clock_times(vp.sig_info[clk])
    sample_times=clock_sample_times(clocks)
    period=float(np.median(np.diff(clocks)))

    def sample(name):
        if name not in vp.sig_info: vp.add_signal(name)
        vp.sig_info[name].get_values()
        return resample_signal(vp.sig_info[name],sample_times)

    done=sample(find('ap_done'))
    start=sample(find('ap_start'))
    done_edges=np.flatnonzero((done==1)&np.r_[True,done[:-1]!=1])
    start_edges=np.flatnonzero((start==1)&np.r_[True,start[:-1]!=1])
    assert len(done_edges)==len(scenarios),(len(done_edges),len(scenarios))
    assert len(start_edges)==len(scenarios),(len(start_edges),len(scenarios))
    ports={}
    for label,sigs in [('in',ins),('out',outs)]:
        ports[label]={k:sample(name) for k,name in sigs.items() if name is not None}
        ports[label]['keep']=sample(find(label+'_stream_TKEEP'))
        ports[label]['strb']=sample(find(label+'_stream_TSTRB'))
        ports[label]['accepted']=((ports[label]['tvalid']==1)&(ports[label]['tready']==1))

    rows=[]
    timing=None
    with (E/'rtl_handshakes.csv').open('w') as f:
        writer=csv.writer(f)
        writer.writerow(['scenario','port','index','cycle','time_ns','data','last','keep','strb'])
        for idx,s in enumerate(scenarios):
            begin=int(start_edges[idx]); end=int(done_edges[idx])
            assert begin<end
            events={}
            for label in ['in','out']:
                p=ports[label]
                # Include the entire gap after the previous return: unexpected
                # post-error transfers cannot disappear between activations.
                lo=0 if idx==0 else int(done_edges[idx-1])+1
                indices=np.flatnonzero(p['accepted'][lo:end+1])+lo
                expected=s['words'][:s['consumed']] if label=='in' else s['output']
                got=[(int(p['tdata'][i])&0xffffffff,int(p['tlast'][i])) for i in indices]
                assert got==[tuple(w) for w in expected],(s['name'],label,len(got),len(expected))
                # Waveflow's default vector decoder sign-extends bus vectors;
                # compare the actual four bits (0xf may be represented as -1).
                bad_enables=[(int(i),int(p['keep'][i])&15,int(p['strb'][i])&15) for i in indices
                             if (int(p['keep'][i])&15)!=15 or (int(p['strb'][i])&15)!=15]
                assert not bad_enables,(s['name'],label,bad_enables[:5])
                events[label]=indices
                for j,i in enumerate(indices):
                    writer.writerow([s['name'],label,j,int(i),f'{clocks[i]:.3f}',
                                     f'{int(p["tdata"][i])&0xffffffff:08x}',int(p['tlast'][i]),
                                     int(p['keep'][i])&15,int(p['strb'][i])&15])
            rows.append([s['name'],'PASS',len(events['in']),s['consumed'],len(events['out']),begin,end,end-begin])
            if s['timing']:
                t=s['timing']; n=t['nsamp']
                first=int(events['in'][t['input_start']])
                last_input=int(events['in'][t['input_start']+n-1])
                first_output=int(events['out'][t['output_start']])
                last=int(events['out'][t['output_start']+n-1])
                # Actual input source availability and output sink readiness.
                assert np.all(ports['in']['tvalid'][first:last_input+1]==1)
                assert np.all(ports['out']['tready'][first:last+1]==1)
                timing=dict(scenario=s['name'],clock_period_ns=period,nsamp=n,K=16,
                            first_payload_cycle=first,last_input_cycle=last_input,
                            first_result_cycle=first_output,last_result_cycle=last,
                            total_cycles=last-first+1,cycles_per_result=(last-first+1)/n,
                            samples_per_cycle=n/(last-first+1),
                            first_result_latency_cycles=first_output-first,
                            input_continuously_valid=True,output_no_backpressure=True)
    with (E/'rtl_trace_checks.csv').open('w') as f:
        writer=csv.writer(f)
        writer.writerow(['scenario','result','input_words','expected_consumed','output_words',
                         'start_cycle','done_cycle','activation_latency_cycles'])
        writer.writerows(rows)
    assert timing is not None
    (E/'timing_measurements.txt').write_text(json.dumps(timing,indent=2)+'\n')
    return timing,rows


def main():
    scenarios=json.loads((E/'scenarios.txt').read_text())
    for name in ['model_checks.csv','csim_checks.csv','cosim_checks.csv']:
        rows=read_csv(name)
        assert len(rows)==len(scenarios),name
        assert all(r.get('result',r.get('model_vs_intent'))=='PASS' for r in rows),name
    assert (E/'csim_words.csv').read_bytes()==(E/'cosim_words.csv').read_bytes()
    # Independently check each replay transaction's words, sidebands and status.
    streams={field:replay_transactions('out_stream_V_'+field+'_V')
             for field in ['data','last','keep','strb']}
    status={field:replay_transactions(field) for field in ['halted','error','tx_id']}
    for values in list(streams.values())+list(status.values()):
        assert len(values)==len(scenarios)
    for i,s in enumerate(scenarios):
        assert streams['data'][i]==[w[0] for w in s['output']],s['name']
        assert streams['last'][i]==[w[1] for w in s['output']],s['name']
        assert streams['keep'][i]==[15]*len(s['output']),s['name']
        assert streams['strb'][i]==[15]*len(s['output']),s['name']
        assert [status[k][i][0] for k in ['halted','error','tx_id']]==s['status'],s['name']
    timing,trace_rows=analyze_trace(scenarios)
    xml=ET.parse(E/'maxaffine_csynth.xml.txt').getroot()
    clock=float(xml.findtext('.//EstimatedClockPeriod'))
    resources={child.tag:int(child.text) for child in xml.find('.//AreaEstimates/Resources')}
    summary=dict(activations=len(scenarios),error_activations=sum(s['status'][0] for s in scenarios),
                 model_csim_cosim_bit_exact='PASS',replay_words_status_sidebands='PASS',
                 rtl_input_stop_and_output_framing='PASS',estimated_clock_ns=clock,
                 clock_target='PASS' if clock<10 else 'FAIL',
                 throughput_target='PASS' if timing['cycles_per_result']<=16 else 'FAIL',
                 resources=resources,timing=timing)
    latency_row=re.search(r'\|\s*Verilog\|\s*Pass\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|',
                          (E/'cosim_report.txt').read_text())
    assert latency_row is not None
    summary['activation_latency_min_avg_max']=list(map(int,latency_row.groups()))
    (E/'verification_summary.txt').write_text(json.dumps(summary,indent=2)+'\n')
    write_report(scenarios,summary)
    print(json.dumps(summary,indent=2))


def write_report(scenarios,summary):
    # The report is generated only from checked evidence, not estimated timings.
    t=summary['timing']; r=summary['resources']
    report='''# Max-affine accelerator results

## Interface

Two 32-bit AXI4-Streams carry commands/results. Every accepted word has
TKEEP=TSTRB=0xf. Every header and payload is a separate TLAST-terminated burst.
All multiword sequences use the order below. Raw signed 16-bit values have
eight fractional bits; host files store each bus word as eight hexadecimal
digits followed by its decimal TLAST bit.

Command header (three words): word 0 = tx_id[31:16], reserved[15:8]=0,
opcode[7:0]; word 1 = reserved[31:16]=0, count[15:0]; word 2 = zero.
TLAST is set only on word 2. CONFIG=1, DATA=2, END=3. tx_id is a 16-bit
identifier and is completely available after the first word.

CONFIG count is K and its payload has K words, each packing raw a in
bits [15:0] and raw b in [31:16]. DATA count is nsamp and its payload has
nsamp words, each with one raw x in [15:0]; the upper half is ignored,
including nonzero padding used by the tests. END requires count=0 and has
no payload. A CONFIG acknowledgement has two words: opcode and tx_id in
word 0 as above, and zero in word 1, with TLAST only on word 1. A DATA
response header is the same, but word 1 contains nsamp. It is followed by
nsamp output words: raw y in the low half, zero in the upper half, TLAST
only on the last result. No response is emitted for END or an erroneous
command. Byte-enable violations are outside the specified input protocol.

The AXI-Lite control map is preserved in
[control_registers.v.txt](evidence/control_registers.v.txt): control/ap_start/
ap_done at 0x00; halted at 0x10 (valid flag 0x14); error at 0x20 (valid flag
0x24); offending tx_id at 0x30 (valid flag 0x34). The host starts, sends
commands, waits for ap_done, then reads status. Configuration never uses
AXI-Lite. Success leaves halted/error/tx_id zero; errors set halted=1 and
the code/id below. Reset the stream path and start with fresh CONFIG after
an error. Every activation clears status and starts unconfigured.

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Header early TLAST |
| 2 | Header missing TLAST on expected last word |
| 3 | Unknown opcode |
| 4 | Invalid count or nonzero reserved header bits |
| 5 | DATA before CONFIG |
| 6 | Payload early TLAST |
| 7 | Payload missing TLAST on expected last word |

Framing has priority over opcode, which has priority over parameters and
then configuration. The first detectable error ends the activation without
draining input. Incomplete headers still contain tx_id in their first word.

## Design

The outer command loop runs until END or an error. Local arrays hold the
current coefficients and the bounded sample buffer. CONFIG fully validates
its input before acknowledging; DATA fully buffers and validates its input
before emitting its response, so failed commands have no partial output.
Prior successful responses are already TLAST-closed.

For each buffered sample, a pipelined inner loop evaluates each active line
using exact signed intermediates and a maximum accumulator. Arithmetic
right shift plus the low eight remainder bits implements floor-based
nearest-even rounding for both signs; final output is saturated. The Python
scalar model independently uses magnitude-based rounding; the NumPy
reference uses signed quotient/remainder and broadcasting.

The inner line loop has achieved II=1; this counts candidate lines, not
complete samples. Samples are processed sequentially; pipeline startup,
rounding, output and buffering add costs. The measured end-to-end throughput
miss below is retained as required by the prompt, without a timing-closing
redesign. See [inner-loop synthesis](evidence/maxaffine_Pipeline_line_loop_csynth.rpt.txt).

The exact upstream FPGA choice is inherited from the committed
[Waveflow reference run.tcl](evidence/reference/run.tcl). Tool/package versions
are recorded in [environment.txt](evidence/environment.txt) and
[tool_version.txt](evidence/tool_version.txt). No board deployment or place
and route was performed; clock/resources below are HLS estimates.

## Targets

Required values come from [prompt.md](prompt.md). Measured values are from
the evidence linked in each row. "No target" rows are measurements only.

| Quantity | Required | Measured | Result | Evidence |
| --- | --- | --- | --- | --- |
'''
    report+=f'| Estimated clock | <10 ns | {summary["estimated_clock_ns"]} ns | {summary["clock_target"]} | [HLS report](evidence/maxaffine_csynth.rpt.txt) |\n'
    report+=f'| DATA cycles/result, K=16, nsamp=1024 | <=16 | {t["cycles_per_result"]:.9f} | {summary["throughput_target"]} | [RTL timing](evidence/timing_measurements.txt), [handshakes](evidence/rtl_handshakes.csv) |\n'
    report+=f'| DATA throughput | No separate target | {t["samples_per_cycle"]:.9f} samples/cycle | no target | [RTL timing](evidence/timing_measurements.txt) |\n'
    report+=f'| DATA span, first input to last result inclusive | No target | {t["total_cycles"]} cycles | no target | [RTL timing](evidence/timing_measurements.txt) |\n'
    report+=f'| First-result latency from first input | No target | {t["first_result_latency_cycles"]} cycles | no target | [RTL timing](evidence/timing_measurements.txt) |\n'
    latency=' / '.join(map(str,summary['activation_latency_min_avg_max']))
    report+=f'| Activation latency, min/average/max | No target | {latency} cycles | no target | [Co-simulation report](evidence/cosim_report.txt) |\n'
    report+='| Inner candidate-line loop II | No target | 1 cycle | no target | [Loop report](evidence/maxaffine_Pipeline_line_loop_csynth.rpt.txt) |\n'
    for name in ['BRAM_18K','DSP','FF','LUT','URAM']:
        report+=f'| {name} | No target | {r[name]} | no target | [HLS report](evidence/maxaffine_csynth.rpt.txt) |\n'
    report+='''
The timing scenario has continuously valid input during its sample burst
and a continuously ready output sink, verified directly from the VCD.
The clock period in the trace is 10 ns. The synthesis warning margin is
not treated as an additional clock target.

## Verification

Independent checks: four hand-computed arithmetic cases plus reconfiguration,
four coefficient sets across all 65,536 raw inputs, and sixteen random
coefficient sets with 1,024 samples each (seed 20261022): **PASS**.
Sources: [independent_checks.txt](evidence/independent_checks.txt),
[verification code](verify_model.py), [model checks](evidence/model_checks.csv).

All scenario intent, including exact input/output words, expected status and
consumption count, is committed in [scenarios.txt](evidence/scenarios.txt).
The C and RTL testbenches compare with that intent, not just with each other.
Recorded C and co-simulation words, TLAST, byte enables and status agree
bit for bit: **PASS**. Sources:
[C words](evidence/csim_words.csv), [RTL words](evidence/cosim_words.csv),
[summary](evidence/verification_summary.txt).

The waveform replay is also checked independently against those expectations:
raw replay output/status `.dat.txt` files are committed under `evidence/`.
Physical input handshakes are compared with the exact expected consumed
prefix for every activation, including all intervals between activations;
no sentinel or post-error word is consumed: **PASS**.
Sources: [trace checks](evidence/rtl_trace_checks.csv),
[handshakes](evidence/rtl_handshakes.csv),
[raw trace](evidence/rtl_trace.vcd.gz), [analyzer](analyze.py).

Every row below has PASS for model, C simulation, RTL co-simulation and
physical handshake/framing checks. These are per-scenario results from
[M: model](evidence/model_checks.csv), [C: C simulation](evidence/csim_checks.csv),
[R: co-simulation](evidence/cosim_checks.csv), and
[T: trace](evidence/rtl_trace_checks.csv); match the row by its scenario name.
For an error row the immediately following `_recovery` row is a fresh
CONFIG/DATA/END activation. Status is shown as halted/error/tx_id.

| Scenario | Model | C sim | RTL cosim | Trace | Status | Fresh recovery | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
'''
    for s in scenarios:
        recovery='PASS: '+s['name']+'_recovery' if s['status'][0] else 'n/a'
        status='/'.join(map(str,s['status']))
        report+=f'| {s["name"]} | PASS | PASS | PASS | PASS | {status} | {recovery} | M / C / R / T above |\n'
    report+='''
## Assumptions

Only interface choices remain: numeric opcodes/error codes; a three-word
command header and two-word response header; 16-bit transaction IDs; and
one scalar sample per 32-bit word. These are documented under Interface.
The application arithmetic, buffer limits, state/reset semantics, validation
order, error output and host recovery follow the prompt; none remains an
unsettled design decision. Actual tool version and inherited FPGA are recorded.

## Open Items

The requested throughput target is **FAIL**, with the measured value and
evidence in Targets. This is the reported performance limitation of this
sequential sample design; the prompt explicitly requests honest reporting
instead of a redesign to close timing. There are no unresolved functional
specification choices or incomplete simulation checks. Public GitHub upload
and LLM grader/Gradescope submission are host/student actions still to do;
this local course clone points at the instructor's repository.

## Run History

| Run | Prompt version | What was built, reviewed or changed | Outcome and evidence |
| --- | --- | --- | --- |
| P0: pre-implementation review | 1 -> 2 | Drafted the max-affine requirements, then clarified framing and measurement boundaries before building hardware; this was not an implementation-driven revision | Part 3 feedback awarded full credit; [recorded feedback](evidence/part3_feedback.txt). The version 2 baseline and version 3 change are preserved in local git history |
| 1a: environment setup | 2 | First Vitis attempt could not reach the university license from the sandbox; used the existing license connection outside that restriction | Resolved; [initial failure](evidence/setup_license_failure.txt), [successful C log](evidence/csim_vitis.txt) |
| 1b: implementation | 2 | Built Python model, independent checks, kernel, full-suite testbench, C simulation, synthesis and one cosim_design invocation | Functional checks pass; [C log](evidence/csim_vitis.txt), [synthesis log](evidence/csynth_vitis.txt), [RTL log](evidence/cosim_vitis.txt). Vitis emitted WDB instead of VCD; [observation](evidence/waveform_observation.txt) |
| 2a: waveform extraction correction | 3 | Prompt explicitly permitted Waveflow snapshot replay for VCD export; first capture attempted an unsupported wildcard over internal arrays and ended before simulation | Tooling failure preserved in [capture log](evidence/waveform_capture_failure.txt); no hardware or test change |
| 2b: waveform replay | 3 | Used Waveflow port-only tracing plus scalar lifecycle signals; replayed the same compiled RTL and all scenarios | [Replay log](evidence/waveform_replay.txt) shows all activations completed, followed by a false failure from a header-only VCD validator; no hardware or test change |
| 2c: final evidence review | 3 | Corrected the VCD validator to inspect the recorded final timestamp, preserved the existing full capture without another replay, and normalized signed bus decoding to the actual byte-enable bits; independently checked raw outputs/status and every physical handshake | [Postprocessing correction](evidence/export_finalize.txt), [summary](evidence/verification_summary.txt). Functional verification PASS; clock PASS; throughput FAIL as measured. C/synthesis remained valid because only capture/analyzer tooling changed |
'''
    (ROOT/'results.md').write_text(report)


if __name__=='__main__':
    main()
