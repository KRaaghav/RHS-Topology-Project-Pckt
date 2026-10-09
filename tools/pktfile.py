#!/usr/bin/env python3
"""
pktfile.py - open and save Packet Tracer .pkt files without Packet Tracer

A .pkt file is one big XML document that Packet Tracer compresses and then scrambles:

  XML text  ->  zlib compress  ->  XOR each byte  ->  Twofish (EAX mode)  ->  reverse + XOR

read_pkt() undoes those steps and returns the XML, write_pkt() does them again. The
key and the steps are the same in every Packet Tracer since version 7 (they were worked
out by the open source pka2xml project). Python has no Twofish built in, so the cipher
is written out below. It is checked against the official test value every time the
program starts.

Used by pktconfig.py. Can also be run by itself:

  python3 pktfile.py unpack "../RHS School Network.pkt" lab.xml
  python3 pktfile.py pack lab.xml "../RHS School Network.pkt"

Only uses the Python standard library, nothing to install.
"""

import struct
import sys
import zlib

KEY = bytes([137]) * 16         # the same in every .pkt file
NONCE = bytes([16]) * 16


# ---------------------------------------------------------------- Twofish
# Only encrypting one block is needed. EAX mode never uses the decrypt direction.

def _make_q(t0, t1, t2, t3):
    """Build one of the two fixed 8 bit lookup tables from its four 4 bit tables."""
    def ror4(x):
        return (x >> 1) | ((x & 1) << 3)
    table = []
    for x in range(256):
        a, b = x >> 4, x & 15
        a, b = a ^ b, a ^ ror4(b) ^ ((8 * a) & 15)
        a, b = t0[a], t1[b]
        a, b = a ^ b, a ^ ror4(b) ^ ((8 * a) & 15)
        table.append(16 * t3[b] + t2[a])
    return table


Q0 = _make_q([8, 1, 7, 13, 6, 15, 3, 2, 0, 11, 5, 9, 14, 12, 10, 4],
             [14, 12, 11, 8, 1, 2, 3, 5, 15, 4, 10, 6, 7, 0, 9, 13],
             [11, 10, 5, 14, 6, 13, 9, 0, 12, 8, 15, 3, 2, 4, 7, 1],
             [13, 7, 15, 4, 1, 2, 6, 14, 9, 11, 3, 0, 8, 5, 12, 10])
Q1 = _make_q([2, 8, 11, 13, 15, 7, 6, 14, 3, 1, 9, 4, 0, 10, 12, 5],
             [1, 14, 2, 11, 4, 12, 3, 7, 6, 13, 10, 5, 15, 9, 0, 8],
             [4, 12, 7, 5, 1, 6, 9, 10, 0, 14, 13, 8, 2, 11, 3, 15],
             [11, 9, 5, 1, 12, 3, 13, 14, 6, 4, 7, 15, 2, 0, 8, 10])

MDS = [[0x01, 0xEF, 0x5B, 0x5B], [0x5B, 0xEF, 0xEF, 0x01], [0xEF, 0x5B, 0x01, 0xEF], [0xEF, 0x01, 0xEF, 0x5B]]
RS = [[0x01, 0xA4, 0x55, 0x87, 0x5A, 0x58, 0xDB, 0x9E], [0xA4, 0x56, 0x82, 0xF3, 0x1E, 0xC6, 0x68, 0xE5],
      [0x02, 0xA1, 0xFC, 0xC1, 0x47, 0xAE, 0x3D, 0x19], [0xA4, 0x55, 0x87, 0x5A, 0x58, 0xDB, 0x9E, 0x03]]
MASK = 0xFFFFFFFF


def _gf_mul(a, b, poly):
    """Multiply two bytes the way Twofish does (in a finite field)."""
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        if a & 0x100:
            a ^= poly
        b >>= 1
    return result


def _rol(x, n):
    return ((x << n) | (x >> (32 - n))) & MASK


def _ror(x, n):
    return ((x >> n) | (x << (32 - n))) & MASK


class Twofish:
    """Twofish with a 128 bit key."""

    def __init__(self, key):
        if len(key) != 16:
            raise ValueError("the key has to be 16 bytes")
        # the three key halves the cipher works with, 4 bytes each
        even = [key[0:4], key[8:12]]
        odd = [key[4:8], key[12:16]]
        s = []
        for half in (key[0:8], key[8:16]):
            s.append(bytes(self._xor_all(_gf_mul(RS[row][i], half[i], 0x14D) for i in range(8))
                           for row in range(4)))
        s.reverse()

        # g() is used twice in every round, so it is turned into four lookup tables
        self.tables = [[self._h_column(col, x, s) for x in range(256)] for col in range(4)]

        self.subkeys = []
        for i in range(20):
            a = self._h(bytes([2 * i]) * 4, even)
            b = _rol(self._h(bytes([2 * i + 1]) * 4, odd), 8)
            self.subkeys.append((a + b) & MASK)
            self.subkeys.append(_rol((a + 2 * b) & MASK, 9))

    @staticmethod
    def _xor_all(values):
        result = 0
        for value in values:
            result ^= value
        return result

    @staticmethod
    def _h_column(col, x, l):
        """One input byte through the key dependent S-box and one MDS column."""
        first, second, third = ((Q0, Q0, Q1), (Q1, Q0, Q0), (Q0, Q1, Q1), (Q1, Q1, Q0))[col]
        y = third[second[first[x] ^ l[1][col]] ^ l[0][col]]
        return (_gf_mul(MDS[0][col], y, 0x169) | _gf_mul(MDS[1][col], y, 0x169) << 8 |
                _gf_mul(MDS[2][col], y, 0x169) << 16 | _gf_mul(MDS[3][col], y, 0x169) << 24)

    def _h(self, x, l):
        return self._xor_all(self._h_column(col, x[col], l) for col in range(4))

    def encrypt(self, block):
        t0, t1, t2, t3 = self.tables
        k = self.subkeys
        r0, r1, r2, r3 = struct.unpack("<4I", block)
        r0 ^= k[0]
        r1 ^= k[1]
        r2 ^= k[2]
        r3 ^= k[3]
        for i in range(8, 40, 2):
            a = t0[r0 & 255] ^ t1[(r0 >> 8) & 255] ^ t2[(r0 >> 16) & 255] ^ t3[r0 >> 24]
            b = t0[r1 >> 24] ^ t1[r1 & 255] ^ t2[(r1 >> 8) & 255] ^ t3[(r1 >> 16) & 255]
            r2 ^= (a + b + k[i]) & MASK
            r2 = _ror(r2, 1)
            r3 = _rol(r3, 1) ^ ((a + 2 * b + k[i + 1]) & MASK)
            r0, r1, r2, r3 = r2, r3, r0, r1
        return struct.pack("<4I", r2 ^ k[4], r3 ^ k[5], r0 ^ k[6], r1 ^ k[7])


def _self_test():
    """The test value from the Twofish paper: all zero key, all zero block."""
    expected = bytes.fromhex("9F589F5CF6122C32B6BFEC2F2AE8C35A")
    if Twofish(bytes(16)).encrypt(bytes(16)) != expected:
        raise RuntimeError("the Twofish code in pktfile.py is broken")


_self_test()


# ---------------------------------------------------------------- EAX mode
# EAX = counter mode for the secrecy + a checksum (OMAC) that proves nothing was changed.

def _xor(a, b):
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")


def _double(block):
    number = int.from_bytes(block, "big") << 1
    if number >> 128:
        number = (number & ((1 << 128) - 1)) ^ 0x87
    return number.to_bytes(16, "big")


def _omac(cipher, tag, data):
    """Checksum of data. tag is 0, 1 or 2 so the three checksums EAX needs come out different."""
    data = bytes(15) + bytes([tag]) + data
    k1 = _double(cipher.encrypt(bytes(16)))
    whole = len(data) // 16 * 16
    if whole == len(data):
        whole -= 16
        last = _xor(data[whole:], k1)
    else:
        last = _xor((data[whole:] + b"\x80").ljust(16, b"\x00"), _double(k1))
    state = bytes(16)
    for i in range(0, whole, 16):
        state = cipher.encrypt(_xor(state, data[i:i + 16]))
    return cipher.encrypt(_xor(state, last))


def _ctr(cipher, start, data):
    """Counter mode. The same function encrypts and decrypts."""
    counter = int.from_bytes(start, "big")
    stream = bytearray()
    for _ in range(0, len(data), 16):
        stream += cipher.encrypt(counter.to_bytes(16, "big"))
        counter = (counter + 1) % (1 << 128)
    return _xor(data, bytes(stream[:len(data)])) if data else b""


def eax_encrypt(data):
    cipher = Twofish(KEY)
    n = _omac(cipher, 0, NONCE)
    body = _ctr(cipher, n, data)
    check = _xor(_xor(n, _omac(cipher, 1, b"")), _omac(cipher, 2, body))
    return body + check


def eax_decrypt(data):
    if len(data) < 16:
        raise ValueError("file is too short to be a .pkt")
    cipher = Twofish(KEY)
    body, check = data[:-16], data[-16:]
    n = _omac(cipher, 0, NONCE)
    if check != _xor(_xor(n, _omac(cipher, 1, b"")), _omac(cipher, 2, body)):
        raise ValueError("this is not a Packet Tracer 7 or newer file, or it is damaged")
    return _ctr(cipher, n, body)


# ---------------------------------------------------------------- the .pkt format

def decode(raw):
    """Bytes of a .pkt file -> XML bytes."""
    size = len(raw)
    step1 = bytes(raw[size - 1 - i] ^ ((size - i * size) & 255) for i in range(size))
    step2 = eax_decrypt(step1)
    size = len(step2)
    step3 = bytes(step2[i] ^ ((size - i) & 255) for i in range(size))
    return zlib.decompress(step3[4:])              # the first 4 bytes are the unpacked length


def encode(xml):
    """XML bytes -> bytes of a .pkt file."""
    step3 = struct.pack(">I", len(xml)) + zlib.compress(xml)
    size = len(step3)
    step2 = bytes(step3[i] ^ ((size - i) & 255) for i in range(size))
    step1 = eax_encrypt(step2)
    size = len(step1)
    return bytes(step1[size - 1 - i] ^ ((size - (size - 1 - i) * size) & 255) for i in range(size))


def read_pkt(path):
    with open(path, "rb") as f:
        return decode(f.read())


def write_pkt(path, xml):
    data = encode(xml)
    if decode(data) != xml:                        # never leave a file behind that cannot be opened
        raise RuntimeError("packing failed, the file was not written")
    with open(path, "wb") as f:
        f.write(data)


def main(args):
    if len(args) == 3 and args[0] == "unpack":
        xml = read_pkt(args[1])
        with open(args[2], "wb") as f:
            f.write(xml)
        print(f"{args[1]} -> {args[2]} ({len(xml)} bytes of XML)")
        return 0
    if len(args) == 3 and args[0] == "pack":
        with open(args[1], "rb") as f:
            write_pkt(args[2], f.read())
        print(f"{args[1]} -> {args[2]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
