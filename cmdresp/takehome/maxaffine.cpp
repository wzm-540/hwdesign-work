#include "maxaffine.hpp"

static void emit(hls::stream<axis_t>& s, ap_uint<32> value, bool last) {
#pragma HLS INLINE
    streamutils::write_axi4_word<32>(s, value, last);
}

static ap_uint<8> body(hls::stream<axis_t>& in_stream,
                       hls::stream<axis_t>& out_stream, ap_uint<16>& bad_id) {
#pragma HLS INLINE
    ap_int<16> a[16], b[16], x[1024];
    bool configured = false;
    unsigned K = 0;
command_loop:
    while (true) {
        ap_uint<32> h[3];
        ap_uint<16> current_id = 0;
header_loop:
        for (int j=0; j<3; ++j) {
#pragma HLS PIPELINE off
            axis_t w = in_stream.read();
            h[j] = w.data;
            if (j==0) current_id = h[0].range(31,16);
            bad_id = current_id;
            if (w.last && j!=2) return HEADER_EARLY;
            if (!w.last && j==2) return HEADER_MISSING;
        }
        unsigned op = h[0].range(7,0);
        unsigned n = h[1].range(15,0);
        if (op<1 || op>3) return UNKNOWN;
        if (h[0].range(15,8)!=0 || h[1].range(31,16)!=0 || h[2]!=0)
            return PARAMETERS;
        if ((op==1 && (n<1 || n>16)) || (op==2 && (n<1 || n>1024)) ||
            (op==3 && n!=0)) return PARAMETERS;
        if (op==3) return OK;
        if (op==2 && !configured) return UNCONFIGURED;
payload_loop:
        for (unsigned i=0; i<n; ++i) {
#pragma HLS PIPELINE off
#pragma HLS LOOP_TRIPCOUNT min=1 max=1024
            axis_t w = in_stream.read();
            if (w.last && i!=n-1) return PAYLOAD_EARLY;
            if (!w.last && i==n-1) return PAYLOAD_MISSING;
            if (op==1) {
                a[i] = w.data.range(15,0);
                b[i] = w.data.range(31,16);
            } else {
                x[i] = w.data.range(15,0);
            }
        }
        if (op==1) { K=n; configured=true; }
        ap_uint<32> r = 0;
        r.range(7,0)=op;
        r.range(31,16)=current_id;
        emit(out_stream, r, false);
        emit(out_stream, op==1 ? 0 : n, true);
        if (op==1) continue;
sample_loop:
        for (unsigned i=0; i<n; ++i) {
#pragma HLS PIPELINE off
#pragma HLS LOOP_TRIPCOUNT min=1 max=1024
            ap_int<33> best = -(ap_int<33>(1)<<32);
line_loop:
            for (unsigned k=0; k<K; ++k) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=16
                ap_int<32> product = a[k]*x[i];
                ap_int<33> p = ap_int<33>(product) + ap_int<33>(b[k])*256;
                if (p>best) best=p;
            }
            // Arithmetic shift gives floor division, including negative ties.
            ap_int<33> q = best >> 8;
            ap_uint<8> rem = best.range(7,0);
            if (rem>128 || (rem==128 && q[0])) ++q;
            ap_int<16> y;
            if (q>32767) y=32767;
            else if (q<-32768) y=-32768;
            else y=q;
            ap_uint<32> packed = 0;
            packed.range(15,0)=y.range(15,0);
            emit(out_stream, packed, i==n-1);
        }
    }
}

void maxaffine(hls::stream<axis_t>& in_stream, hls::stream<axis_t>& out_stream,
               ap_uint<1>& halted, ap_uint<8>& error, ap_uint<16>& tx_id) {
#pragma HLS INTERFACE axis port=in_stream register_mode=off
#pragma HLS INTERFACE axis port=out_stream register_mode=off
#pragma HLS INTERFACE s_axilite port=halted bundle=control
#pragma HLS INTERFACE s_axilite port=error bundle=control
#pragma HLS INTERFACE s_axilite port=tx_id bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    halted=0; error=0; tx_id=0;
    ap_uint<16> bad_id=0;
    ap_uint<8> code=body(in_stream,out_stream,bad_id);
    if (code!=OK) { halted=1; error=code; tx_id=bad_id; }
}
