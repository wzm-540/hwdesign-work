# Reference: Waveflow examples/stream_inband/run.tcl (FPGA and clock).
set root [file dirname [file normalize [info script]]]
set stage $::env(MAXAFFINE_STAGE)
if {$stage ni {csim csynth cosim}} { error "Invalid stage" }
if {$stage eq "csim"} { open_project -reset maxaffine_proj } else { open_project maxaffine_proj }
set_top maxaffine
add_files maxaffine.cpp -cflags "-I."
add_files -tb tb_maxaffine.cpp -cflags "-I."
if {$stage eq "csim"} { open_solution -reset solution1 } else { open_solution solution1 }
set_part {xc7z020clg484-1}
create_clock -period 10
set args "[file join $root vectors] [file join $root evidence] $stage"
switch $stage {
    csim { csim_design -argv $args }
    csynth { csynth_design }
    cosim { cosim_design -argv $args -trace_level port -rtl verilog }
}
puts "MAXAFFINE_SUCCESS $stage"
exit 0
