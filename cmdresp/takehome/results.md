# Max-affine accelerator results

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
| Estimated clock | <10 ns | 6.674 ns | PASS | [HLS report](evidence/maxaffine_csynth.rpt.txt) |
| DATA cycles/result, K=16, nsamp=1024 | <=16 | 26.001953125 | FAIL | [RTL timing](evidence/timing_measurements.txt), [handshakes](evidence/rtl_handshakes.csv) |
| DATA throughput | No separate target | 0.038458649 samples/cycle | no target | [RTL timing](evidence/timing_measurements.txt) |
| DATA span, first input to last result inclusive | No target | 26626 cycles | no target | [RTL timing](evidence/timing_measurements.txt) |
| First-result latency from first input | No target | 1050 cycles | no target | [RTL timing](evidence/timing_measurements.txt) |
| Activation latency, min/average/max | No target | 8 / 4404 / 26673 cycles | no target | [Co-simulation report](evidence/cosim_report.txt) |
| Inner candidate-line loop II | No target | 1 cycle | no target | [Loop report](evidence/maxaffine_Pipeline_line_loop_csynth.rpt.txt) |
| BRAM_18K | No target | 1 | no target | [HLS report](evidence/maxaffine_csynth.rpt.txt) |
| DSP | No target | 1 | no target | [HLS report](evidence/maxaffine_csynth.rpt.txt) |
| FF | No target | 732 | no target | [HLS report](evidence/maxaffine_csynth.rpt.txt) |
| LUT | No target | 1335 | no target | [HLS report](evidence/maxaffine_csynth.rpt.txt) |
| URAM | No target | 0 | no target | [HLS report](evidence/maxaffine_csynth.rpt.txt) |

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
| hand_0 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| hand_1 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| hand_2 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| hand_3 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| reconfigure | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| crossing_negative_equal | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| rounding_neighbors | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| saturation_neighbors | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| zero_slopes_extrema | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k01 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k02 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k03 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k04 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k05 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k06 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k07 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k08 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k09 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k10 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k11 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k12 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k13 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k14 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k15 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| random_k16 | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| maximum_size | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| end_only | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| many_commands | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| unconfigured_after_end | PASS | PASS | PASS | PASS | 1/5/80 | PASS: unconfigured_after_end_recovery | M / C / R / T above |
| unconfigured_after_end_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| unknown | PASS | PASS | PASS | PASS | 1/3/80 | PASS: unknown_recovery | M / C / R / T above |
| unknown_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| k0 | PASS | PASS | PASS | PASS | 1/4/80 | PASS: k0_recovery | M / C / R / T above |
| k0_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| k17 | PASS | PASS | PASS | PASS | 1/4/80 | PASS: k17_recovery | M / C / R / T above |
| k17_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| n0 | PASS | PASS | PASS | PASS | 1/4/80 | PASS: n0_recovery | M / C / R / T above |
| n0_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| n1025 | PASS | PASS | PASS | PASS | 1/4/80 | PASS: n1025_recovery | M / C / R / T above |
| n1025_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| end_count | PASS | PASS | PASS | PASS | 1/4/80 | PASS: end_count_recovery | M / C / R / T above |
| end_count_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| reserved_word0 | PASS | PASS | PASS | PASS | 1/4/80 | PASS: reserved_word0_recovery | M / C / R / T above |
| reserved_word0_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| reserved_word1 | PASS | PASS | PASS | PASS | 1/4/80 | PASS: reserved_word1_recovery | M / C / R / T above |
| reserved_word1_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| reserved_word2 | PASS | PASS | PASS | PASS | 1/4/80 | PASS: reserved_word2_recovery | M / C / R / T above |
| reserved_word2_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| header_early_word0 | PASS | PASS | PASS | PASS | 1/1/80 | PASS: header_early_word0_recovery | M / C / R / T above |
| header_early_word0_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| header_early_word1 | PASS | PASS | PASS | PASS | 1/1/80 | PASS: header_early_word1_recovery | M / C / R / T above |
| header_early_word1_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| header_missing | PASS | PASS | PASS | PASS | 1/2/80 | PASS: header_missing_recovery | M / C / R / T above |
| header_missing_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| payload_early_1_0 | PASS | PASS | PASS | PASS | 1/6/80 | PASS: payload_early_1_0_recovery | M / C / R / T above |
| payload_early_1_0_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| payload_early_1_1 | PASS | PASS | PASS | PASS | 1/6/80 | PASS: payload_early_1_1_recovery | M / C / R / T above |
| payload_early_1_1_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| payload_missing_1 | PASS | PASS | PASS | PASS | 1/7/80 | PASS: payload_missing_1_recovery | M / C / R / T above |
| payload_missing_1_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| single_word_missing_1 | PASS | PASS | PASS | PASS | 1/7/80 | PASS: single_word_missing_1_recovery | M / C / R / T above |
| single_word_missing_1_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| payload_early_2_0 | PASS | PASS | PASS | PASS | 1/6/80 | PASS: payload_early_2_0_recovery | M / C / R / T above |
| payload_early_2_0_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| payload_early_2_1 | PASS | PASS | PASS | PASS | 1/6/80 | PASS: payload_early_2_1_recovery | M / C / R / T above |
| payload_early_2_1_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| payload_missing_2 | PASS | PASS | PASS | PASS | 1/7/80 | PASS: payload_missing_2_recovery | M / C / R / T above |
| payload_missing_2_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| single_word_missing_2 | PASS | PASS | PASS | PASS | 1/7/80 | PASS: single_word_missing_2_recovery | M / C / R / T above |
| single_word_missing_2_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| priority_framing_unknown_reserved | PASS | PASS | PASS | PASS | 1/1/80 | PASS: priority_framing_unknown_reserved_recovery | M / C / R / T above |
| priority_framing_unknown_reserved_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| priority_unknown_reserved | PASS | PASS | PASS | PASS | 1/3/80 | PASS: priority_unknown_reserved_recovery | M / C / R / T above |
| priority_unknown_reserved_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |
| priority_parameters_unconfigured | PASS | PASS | PASS | PASS | 1/4/80 | PASS: priority_parameters_unconfigured_recovery | M / C / R / T above |
| priority_parameters_unconfigured_recovery | PASS | PASS | PASS | PASS | 0/0/0 | n/a | M / C / R / T above |

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
