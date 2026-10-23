"""Independent arithmetic reference and intent-based protocol scenarios.

Run from any directory: /path/to/.venv/bin/python verify_model.py
"""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
import model as m

ROOT = Path(__file__).resolve().parent


def reference(coeffs, samples):
    c = np.asarray(coeffs, dtype=np.int64)
    x = np.asarray(samples, dtype=np.int64)
    p = np.max(c[:, 0, None] * x[None, :] + 256 * c[:, 1, None], axis=0)
    q, r = np.divmod(p, 256)
    q += ((r > 128) | ((r == 128) & ((q & 1) != 0)))
    return np.clip(q, -32768, 32767).tolist()


def build_scenarios():
    scenarios = []

    def add(name, words, output, status=(0, 0, 0), consumed=None, timing=None):
        scenarios.append(dict(name=name, words=words, output=output, status=list(status),
                              consumed=len(words) if consumed is None else consumed, timing=timing))

    def successful(name, commands):
        words, output, coeffs, timing = [], [], None, None
        for op, tx, value in commands:
            if op == m.CONFIG:
                coeffs = value
                words += m.config(tx, value)
                output += m.response(m.CONFIG, tx)
            elif op == m.DATA:
                # Independent expected values: NumPy reference, never model.evaluate.
                if name == 'maximum_size':
                    timing = dict(input_start=len(words)+3, output_start=len(output)+2, nsamp=len(value))
                words += m.data(tx, value, padding=0xa55a)
                output += m.response(m.DATA, tx, reference(coeffs, value))
        words += m.header(m.END, 0xffff)
        add(name, words, output, timing=timing)

    hand = [([ (256,0), (-256,256)], [-512,0,128,512], [768,256,128,512]),
            ([(1,0)], [128,384,-128,-384], [0,2,0,-2]),
            ([(32767,32767)], [32767], [32767]),
            ([(32767,-32768)], [-32768], [-32768])]
    for i, (c, x, y) in enumerate(hand):
        assert m.evaluate(c,x) == y == reference(c,x)
        successful(f'hand_{i}', [(m.CONFIG,1,c),(m.DATA,2,x)])
    successful('reconfigure', [(m.CONFIG,10,[(256,0),(-256,256)]),
                              (m.DATA,11,[-512,0,128,512]),
                              (m.DATA,12,[256,-256]),
                              (m.CONFIG,13,[(0,-512)]), (m.DATA,14,[-32768,0,32767])])
    successful('crossing_negative_equal', [(m.CONFIG,20,[(1,-256),(-1,-256),(1,-256)]),
                                            (m.DATA,21,[-32768,-385,-384,-383,-129,-128,-127,0,127,128,129,383,384,385,32767])])
    successful('rounding_neighbors', [(m.CONFIG,22,[(1,0)]),
                                      (m.DATA,23,[-385,-384,-383,-129,-128,-127,0,127,128,129,383,384,385])])
    successful('saturation_neighbors', [(m.CONFIG,24,[(512,0)]),
                                        (m.DATA,25,[-32768,-16385,-16384,-16383,16382,16383,16384,32767])])
    successful('zero_slopes_extrema', [(m.CONFIG,26,[(0,-32768),(0,0),(0,32767)]),
                                       (m.DATA,27,[-32768,0,32767])])
    rng = np.random.default_rng(20261022)
    for k in range(1,17):
        c = [tuple(map(int,row)) for row in rng.integers(-32768,32768,(k,2))]
        x = rng.integers(-32768,32768,1024).tolist()
        assert m.evaluate(c,x) == reference(c,x)
        successful(f'random_k{k:02d}',[(m.CONFIG,30,c),(m.DATA,31,x)])
    # Large reduction with low amplitudes avoids hiding all results behind saturation.
    c = [(k-8, -k) for k in range(16)]
    x = rng.integers(-32768,32768,1024).tolist()
    successful('maximum_size', [(m.CONFIG,40,c),(m.DATA,41,x)])
    add('end_only', m.header(m.END,50), [])
    # One bounded hardware implementation must also tolerate many commands.
    successful('many_commands', [(m.CONFIG,60,[(256,0)])] + [(m.DATA,100+i,[i-20]) for i in range(40)])

    base_in = m.config(70,[(256,0)]) + m.data(71,[-256,0,256])
    base_out = m.response(m.CONFIG,70) + m.response(m.DATA,71,[-256,0,256])
    sentinel = [(0xdeadbeef,0),(0x12345678,0),(0xfedcba98,1)]

    def bad(name, fault, error, consumed, prefix=False, tx=80):
        start = base_in if prefix else []
        out = base_out if prefix else []
        add(name, start+fault+sentinel, out, (1,error,tx),len(start)+consumed)
        # The immediately following call has fresh streams and must succeed.
        successful(name+'_recovery', [(m.CONFIG,90,[(256,256)]),(m.DATA,91,[-256,0,256])])

    bad('unconfigured_after_end',m.data(80,[1]),m.UNCONFIGURED,3)
    bad('unknown',m.header(99,80),m.UNKNOWN,3,True)
    for op, n, name in [(m.CONFIG,0,'k0'),(m.CONFIG,17,'k17'),(m.DATA,0,'n0'),(m.DATA,1025,'n1025'),(m.END,1,'end_count')]:
        bad(name,m.header(op,80,n),m.PARAMETERS,3)
    for j,mask in [(0,0x100),(1,0x10000),(2,1)]:
        h=m.header(m.DATA,80,1); h[j]=(h[j][0]|mask,h[j][1])
        bad(f'reserved_word{j}',h,m.PARAMETERS,3)
    for j in (0,1):
        h=m.header(m.CONFIG,80,2); h[j]=(h[j][0],1)
        bad(f'header_early_word{j}',h,m.HEADER_EARLY,j+1,True)
    h=m.header(m.CONFIG,80,2); h[2]=(0,0)
    bad('header_missing',h,m.HEADER_MISSING,3,True)
    for op in (m.CONFIG,m.DATA):
        prefix=op==m.DATA
        payload = m.config(80,[(256,0)]*3) if op==m.CONFIG else m.data(80,[1,2,3])
        for idx in (0,1):
            h=list(payload); h[3+idx]=(h[3+idx][0],1)
            bad(f'payload_early_{op}_{idx}',h,m.PAYLOAD_EARLY,4+idx,prefix)
        h=list(payload); h[-1]=(h[-1][0],0)
        bad(f'payload_missing_{op}',h,m.PAYLOAD_MISSING,len(h),prefix)
        h=m.config(80,[(256,0)]) if op==m.CONFIG else m.data(80,[0])
        h[-1]=(h[-1][0],0)
        bad(f'single_word_missing_{op}',h,m.PAYLOAD_MISSING,len(h),prefix)
    h=m.header(99,80,0); h[0]=(h[0][0]|0x100,1)
    bad('priority_framing_unknown_reserved',h,m.HEADER_EARLY,1)
    h=m.header(99,80,0); h[2]=(1,1)
    bad('priority_unknown_reserved',h,m.UNKNOWN,3)
    bad('priority_parameters_unconfigured',m.header(m.DATA,80,0),m.PARAMETERS,3)
    return scenarios


def main():
    (ROOT/'vectors').mkdir(exist_ok=True)
    (ROOT/'evidence').mkdir(exist_ok=True)
    scenarios=build_scenarios()
    with (ROOT/'evidence/model_checks.csv').open('w') as f:
        writer=csv.writer(f); writer.writerow(['scenario','model_vs_intent','halted','error','tx_id','consumed','output_words'])
        for s in scenarios:
            r=m.activate(s['words'])
            assert r.words==s['output'], s['name']+' output'
            assert list(r.status)==s['status'],s['name']+' status'
            assert r.consumed==s['consumed'],s['name']+' consumed'
            writer.writerow([s['name'],'PASS',*r.status,r.consumed,len(r.words)])
            with (ROOT/'vectors'/f"{s['name']}.txt").open('w') as v:
                v.write(f"{len(s['words'])} {len(s['output'])} {s['consumed']} {' '.join(map(str,s['status']))}\n")
                for value,last in s['words']+s['output']:
                    v.write(f'{value:08x} {last}\n')
    (ROOT/'vectors/scenarios.txt').write_text(''.join(s['name']+'\n' for s in scenarios))
    (ROOT/'evidence/scenarios.txt').write_text(json.dumps(scenarios,indent=2)+'\n')
    # Exhaustive input values at several coefficient sets, independent of protocol cases.
    allx=list(range(-32768,32768))
    exhaustive=[[(1,0)],[(32767,-32768)],[(-32768,32767)],[(256,-256),(-256,128),(0,-1)]]
    for c in exhaustive:
        assert m.evaluate(c,allx)==reference(c,allx)
    text=(f'PASS: 4 hand-computed arithmetic cases and reconfiguration scenario\n'
          f'PASS: {len(exhaustive)} coefficient sets x 65536 raw inputs against independent NumPy\n'
          f'PASS: 16 randomized K cases x 1024 samples; seed 20261022\n'
          f'PASS: {len(scenarios)} protocol activations against independent scenario intent\n')
    (ROOT/'evidence/independent_checks.txt').write_text(text)
    print(text,end='')
    print('scenario SHA256',hashlib.sha256((ROOT/'evidence/scenarios.txt').read_bytes()).hexdigest())


if __name__=='__main__':
    main()
