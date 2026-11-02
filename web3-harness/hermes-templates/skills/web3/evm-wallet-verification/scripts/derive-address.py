#!/usr/bin/env python3
"""Derive the EVM address for a key in an env file, printing ONLY the address.

Dependency-free lane for when the JS harness (viem/ethers) is not usable in the
current directory: pure-python secp256k1 + keccak, no web3/eth-account needed.
The key is never printed, logged or written anywhere.

    python3 derive-address.py --selftest          # prove the math first
    python3 derive-address.py /path/to/.env [VAR] # default VAR=WALLET_PRIVATE_KEY

Always run --selftest before trusting an address: it checks the implementation
against the public private-key-1 vector, so a broken derive fails loudly here
instead of quietly handing back the wrong address to quote to the user.
"""
import re
import sys

try:
    from Crypto.Hash import keccak
except ImportError:
    sys.exit("pip install pycryptodome (or use the viem probe instead)")

P = 2 ** 256 - 2 ** 32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0]) * pow(2 * p[1], P - 2, P) % P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], P - 2, P) % P
    x = (lam * lam - p[0] - q[0]) % P
    return (x, (lam * (p[0] - x) - p[1]) % P)


def _mul(k, point=(Gx, Gy)):
    r = None
    while k:
        if k & 1:
            r = _add(r, point)
        point = _add(point, point)
        k >>= 1
    return r


def address_of(key_hex):
    key_hex = key_hex.strip()
    if not key_hex.startswith("0x"):
        key_hex = "0x" + key_hex
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", key_hex):
        raise ValueError("key is not 32 bytes of hex")
    k = int(key_hex, 16)
    if not 0 < k < N:
        raise ValueError("key out of secp256k1 range")
    x, y = _mul(k)
    h = keccak.new(digest_bits=256)
    h.update(x.to_bytes(32, "big") + y.to_bytes(32, "big"))
    return "0x" + h.hexdigest()[-40:]


def selftest():
    # private key 1 is a public constant; its address is a checksummed standard
    want = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf".lower()
    got = address_of("0x" + "0" * 63 + "1").lower()
    ok = got == want
    print("selftest", "OK" if ok else f"FAILED (got {got})")
    return ok


def main(argv):
    if "--selftest" in argv:
        sys.exit(0 if selftest() else 1)
    if len(argv) < 2:
        sys.exit(__doc__)
    path = argv[1]
    var = argv[2] if len(argv) > 2 else "WALLET_PRIVATE_KEY"
    text = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(rf"^\s*{re.escape(var)}\s*=\s*(.+)$", text, re.M)
    if not m:
        sys.exit(f"{var} not found in {path}")
    value = m.group(1).strip().strip('"').strip("'")
    if not value:
        sys.exit(f"{var} is present but empty")
    try:
        print(address_of(value))
    except ValueError as exc:
        sys.exit(f"{var} does not parse: {exc}")


if __name__ == "__main__":
    main(sys.argv)
