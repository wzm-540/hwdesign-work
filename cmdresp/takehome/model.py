"""Pure Python integer golden model and the 32-bit on-wire protocol.

No floating point is used for the accelerator arithmetic. Model framing is
checked independently against scenario intent in verify_model.py.
"""
from dataclasses import dataclass

CONFIG, DATA, END = 1, 2, 3
OK, HEADER_EARLY, HEADER_MISSING, UNKNOWN, PARAMETERS, UNCONFIGURED, PAYLOAD_EARLY, PAYLOAD_MISSING = range(8)


def signed16(raw):
    raw &= 65535
    return raw - 65536 if raw & 32768 else raw


def evaluate(coeffs, samples):
    """Exact scalar model; rounding uses magnitude (unlike NumPy reference)."""
    result = []
    for x in samples:
        p = max(a * x + 256 * b for a, b in coeffs)
        magnitude = abs(p)
        rounded, remainder = divmod(magnitude, 256)
        if remainder > 128 or (remainder == 128 and rounded % 2):
            rounded += 1
        if p < 0:
            rounded = -rounded
        result.append(min(32767, max(-32768, rounded)))
    return result


def header(op, tx_id, n=0):
    return [(op | (tx_id << 16), 0), (n, 0), (0, 1)]


def burst(values):
    return [(v & 0xffffffff, int(i == len(values) - 1)) for i, v in enumerate(values)]


def config(tx_id, coeffs):
    return header(CONFIG, tx_id, len(coeffs)) + burst([(a & 65535) | ((b & 65535) << 16) for a, b in coeffs])


def data(tx_id, samples, padding=0):
    return header(DATA, tx_id, len(samples)) + burst([(x & 65535) | (padding << 16) for x in samples])


def response(op, tx_id, values=None):
    if values is None:
        return [(op | tx_id << 16, 0), (0, 1)]
    return [(op | tx_id << 16, 0), (len(values), 1)] + burst([v & 65535 for v in values])


@dataclass
class Result:
    words: list
    status: tuple
    consumed: int


def activate(words):
    """One activation, ending immediately at END or the first error."""
    pos, coeffs, output = 0, None, []
    tx_id = 0

    def failure(code):
        return Result(output, (1, code, tx_id), pos)

    while True:
        h = []
        tx_id = 0
        for j in range(3):
            if pos == len(words):
                raise ValueError("Input would block; scenarios must provide required words")
            word, last = words[pos]
            pos += 1
            h.append(word)
            if j == 0:
                tx_id = word >> 16
            if last and j != 2:
                return failure(HEADER_EARLY)
            if not last and j == 2:
                return failure(HEADER_MISSING)
        op, n = h[0] & 255, h[1] & 65535
        if op not in (CONFIG, DATA, END):
            return failure(UNKNOWN)
        if (h[0] & 0xff00) or (h[1] >> 16) or h[2]:
            return failure(PARAMETERS)
        if ((op == CONFIG and not 1 <= n <= 16) or
            (op == DATA and not 1 <= n <= 1024) or (op == END and n != 0)):
            return failure(PARAMETERS)
        if op == END:
            return Result(output, (0, 0, 0), pos)
        if op == DATA and coeffs is None:
            return failure(UNCONFIGURED)
        payload = []
        for i in range(n):
            if pos == len(words):
                raise ValueError("Input payload would block")
            word, last = words[pos]
            pos += 1
            if last and i != n - 1:
                return failure(PAYLOAD_EARLY)
            if not last and i == n - 1:
                return failure(PAYLOAD_MISSING)
            payload.append(word)
        if op == CONFIG:
            coeffs = [(signed16(v), signed16(v >> 16)) for v in payload]
            output += response(CONFIG, tx_id)
        else:
            y = evaluate(coeffs, [signed16(v) for v in payload])
            output += response(DATA, tx_id, y)
