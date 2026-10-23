#ifndef MAXAFFINE_HPP
#define MAXAFFINE_HPP
#include "include/streamutils_hls.h"
using axis_t = streamutils::axi4s_word<32>;
enum Error { OK=0, HEADER_EARLY=1, HEADER_MISSING=2, UNKNOWN=3,
             PARAMETERS=4, UNCONFIGURED=5, PAYLOAD_EARLY=6, PAYLOAD_MISSING=7 };
void maxaffine(hls::stream<axis_t>& in_stream, hls::stream<axis_t>& out_stream,
               ap_uint<1>& halted, ap_uint<8>& error, ap_uint<16>& tx_id);
#endif
