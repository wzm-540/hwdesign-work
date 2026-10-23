# Maximum of programmable affine functions: max_k(a_k x + b_k)

Build a Vitis HLS kernel in this folder following the Waveflow stream_inband
example (https://sdrangan.github.io/waveflow/docs/examples/stream_inband/) and
the command-response pattern.

## Operation
For each input x[i], return y[i] = max_{0 <= k < K}(a[k]*x[i] + b[k])
using the latest CONFIG. This is a maximum over programmable lines for each
sample, with exactly one result per input in order. There are no windows,
padding or cross-sample state. Equal maxima return their common value,
without an index. CONFIG replaces K and all coefficients. Configuration
persists between DATA commands, but every activation starts unconfigured.

## Requirements
Inputs, coefficients and outputs are signed 16-bit two's-complement values
with 8 fractional bits: raw integer r means r/256. All raw patterns are valid.
For each line compute the exact signed integer p[k] = A[k]*X + 256*B[k],
without intermediate rounding, saturation or overflow. Use a signed
intermediate at least 33 bits wide. Take P = max p[k], round P/256 to the
nearest integer (ties to even, also for negatives), then saturate to
[-32768,32767] to obtain the output raw integer.

Support 1 <= K <= 16 and 1 <= nsamp <= 1024 per DATA command; command count
per activation is not bounded. Target at most 16 cycles per scalar result
for K=16, nsamp=1024 with continuously available input and no output
backpressure. Measure (last result handshake cycle - first DATA payload
handshake cycle + 1)/1024 from RTL co-simulation, including buffering,
computation, response header and output costs. A sample is one scalar,
regardless of word packing. Use the reference example's FPGA part and
10 ns requested clock; the estimated clock must be under 10 ns. Report a
missed target honestly rather than redesigning to close timing; a clock
uncertainty warning alone is not a failure. Do not build a Python timing model.

## Commands and parameters
Choose command codes, header layouts, word packing and file formats, and
document them consistently in the model, kernel and testbench.
- CONFIG: header carries K; one following payload burst carries exactly K
  (a[k],b[k]) pairs in increasing k order. After validation, replace the
  configuration and send a header-only acknowledgement echoing tx_id.
- DATA: header carries nsamp; one following payload burst carries exactly
  nsamp samples. Validate and buffer the whole input before any response.
  On success, send a response header echoing tx_id and nsamp, followed by
  one burst of nsamp results.
- END: no payload or response; return normally. END alone is valid.

Each command has a fixed-length header burst with opcode and tx_id. Each
header and each payload is a separate TLAST-terminated burst. Reject K
outside [1,16] and nsamp outside [1,1024], including zero. Check header
framing, opcode, parameters and configuration availability before reading
payload. Parameters travel only on the stream; AXI-Lite carries control
and status. Treat unused header fields as reserved zero; reject nonzero
reserved fields. Payload padding bits are ignored. Use valid byte enables
for all transferred words; malformed byte enables are outside this protocol.

## Errors
Errors go in AXI-Lite status registers (halted, error code, tx_id).  On an
error the kernel closes any output burst it started with TLAST and returns
without reading more input.  Nothing persists between activations: the status
registers are cleared at the start of each one.

Provide distinct nonzero codes for early header TLAST, missing header TLAST,
unknown command, invalid parameters, DATA before CONFIG, early payload TLAST
and missing payload TLAST. Error priority is header framing, unknown opcode,
invalid parameters, then missing configuration. Check framing word by word:
TLAST before the expected final word is early; TLAST=0 on the expected final
word is missing. Stop at the first detectable error; never read ahead or
drain. These rules apply to both coefficient and sample bursts. A missing
word blocks awaiting input, not a timeout error.

Set halted=1 and error to its code. Status tx_id is the offending id if its
complete field was read, otherwise zero. Successful completion leaves all
status registers zero. An erroneous command sends nothing, since its input
is validated before output; earlier responses remain complete. The host
resets the stream path and uses fresh streams for the next activation.

## Verification
Write a bit-exact Python model, Vitis HLS kernel and testbench. Independently
check the model with these hand-computed examples:
- K=2, (a,b)=[(1,0),(-1,1)], x=[-2,0,0.5,2] gives y=[3,1,0.5,2].
- K=1, raw A=1, B=0, X=[128,384,-128,-384] gives raw y=[0,2,0,-2].
- K=1, raw A=32767, B=32767, X=32767 gives raw y=32767;
  raw A=32767, B=-32768, X=-32768 gives raw y=-32768.
- After CONFIG changes to K=1, (a,b)=(0,-2), every output is -2.

Also use an independent NumPy int64 broadcast of A*X+256*B, max over lines,
and quotient/remainder rounding with clipping, without calling model helpers.
Compare reproducible random full-range cases against this reference.

Cover K=1/16, nsamp=1/1024, repeated DATA, CONFIG changing K and coefficients
within an activation, crossing lines, ties, all-negative maxima, zero,
raw extrema, both saturation limits and rounding on either side of a tie.
Check input/output order and word padding at partial final words if packing
allows them. Include END-only, and DATA before CONFIG in a new activation
following normal END to catch retained configuration.

Use a separate activation for each error condition, including invalid K=0/17,
nsamp=0/1025, reserved fields, and early/missing TLAST for headers and both
payload types. Test competing errors for priority. In some cases precede
the error with valid DATA and append sentinel input words; verify earlier
responses end with TLAST and no input after the error is consumed. Check
exact output words, TLAST and status. Follow every error activation with a
fresh CONFIG/DATA/END activation that must pass. RTL tests must supply every
expected word even for missing-TLAST cases, with TLAST=0 on the final word.

Compare the model, C simulation and co-simulation bit for bit.  Run
co-simulation once: one testbench run that walks through every scenario in
order, calling the kernel once per activation with fresh streams, including
each error activation and the fresh activation after it.

If Vitis records only WDB, Waveflow's replay of the existing compiled XSIM
snapshot is permitted solely to export VCD for those same scenarios. Keep
one cosim_design invocation, record the waveform replay separately in Run
History, and check the replay against the same expected words and status.

## results.md
Write results.md with these sections:
- Interface: the command and response layouts, how values pack into words,
  the status registers and the error codes.
- Design: the loop structure, where state is kept, and how the throughput
  target is reached.
- Targets: each target above with the required value, the measured value,
  PASS/FAIL and the file it came from (co-simulation for timing; synthesis
  for clock, II and resources).  Always report the latency and throughput
  from co-simulation and the estimated clock and resources from synthesis,
  writing "no target" where this prompt sets none.
- Verification: the model's check against the hand-computed examples and the
  reference; then one row per scenario saying whether the model, C simulation
  and co-simulation agree, and for each error scenario the status it set and
  whether the fresh activation after it passed. Name the source file of each.
- Assumptions: every place this prompt was silent or ambiguous and what you
  chose, apart from interface details already given under Interface.
- Open Items: questions you could not settle, and anything that failed or was
  not done, or "None".
- Run History: one row per run, with the prompt version, what was built or
  changed, and what passed, so that a later run can continue from here.

Every number and PASS/FAIL in Targets and Verification names the file it came
from (a log, a comparison output or a synthesis report), and that file stays in
this folder to be committed: a reviewer opens them to check results.md.

## Revision history
| Version | Change | Why |
| --- | --- | --- |
| 1 | First version | Initial max-affine specification |
| 2 | Clarify the timing measurement, framing errors and restart checks; shorten the design sections | Review against the Part 3 rubric before implementation; no implementation run yet |
| 3 | Permit Waveflow's compiled XSIM replay solely for VCD export, without another cosim_design invocation | Run 1 generated WDB rather than VCD: evidence/waveform_observation.txt; arithmetic, hardware and scenarios are unchanged |
