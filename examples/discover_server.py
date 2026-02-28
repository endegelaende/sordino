#!/usr/bin/env python3
"""
discover_server.py — Find Lyrion/Resonance servers on the local network.

Uses the SlimDiscovery TLV protocol (port 3483) to broadcast discovery
requests and display any servers that respond.  This is the same protocol
that jivelite/SqueezePlay uses to find LMS instances.

Usage:
    python examples/discover_server.py [--timeout 5] [--address 255.255.255.255] [--port 3483]

Options:
    --timeout SEC       How long to listen for responses (default: 5)
    --address ADDR      Broadcast/unicast address to probe (default: 255.255.255.255)
    --port PORT         UDP port to send to (default: 3483)
    --repeat N          Send N discovery bursts, 1 second apart (default: 3)
    --json              Output results as JSON
    --start-resonance   Start the Resonance server in background first

The script can also optionally start the Resonance server (if available
on the system) before probing, to demonstrate the full discovery flow.

Protocol reference:
    Request:  'e' + TLV entries (IPAD, NAME, JSON, VERS, UUID, JVID)
    Response: 'E' + TLV entries with values filled in
"""

from __future__ import annotations

import argparse
import json as json_mod
import os
import socket
import struct
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISCOVERY_PORT = 3483
RECV_BUFFER = 4096


# ---------------------------------------------------------------------------
# TLV packet construction (matches SlimDiscoveryApplet._slim_discovery_source)
# ---------------------------------------------------------------------------


def build_discovery_request() -> bytes:
    """
    Build a TLV discovery request packet.

    Format: 'e' + TLV entries where each entry is:
        4-byte tag + 1-byte length + value bytes

    Tags with length 0 are requests for the server to fill in.
    JVID is our device ID (6 bytes, placeholder MAC).
    """
    parts: list[bytes] = [
        b"e",
        b"IPAD\x00",  # Request: IP address
        b"NAME\x00",  # Request: server name
        b"JSON\x00",  # Request: JSON-RPC port
        b"VERS\x00",  # Request: version string
        b"UUID\x00",  # Request: server UUID
        # JVID: our device ID (6-byte placeholder MAC)
        b"JVID\x06\x12\x34\x56\x78\x9a\xbc",
    ]
    return b"".join(parts)


def parse_tlv_response(data: bytes) -> Dict[str, str]:
    """
    Parse a TLV discovery response.

    The response starts with 'E' followed by TLV entries.
    Returns a dict mapping 4-char tag names to decoded string values.
    """
    result: Dict[str, str] = {}

    if not data or data[0:1] != b"E":
        return result

    ptr = 1  # skip leading 'E'
    data_len = len(data)

    while ptr <= data_len - 5:
        tag = data[ptr : ptr + 4].decode("ascii", errors="replace")
        length = data[ptr + 4]
        value_bytes = data[ptr + 5 : ptr + 5 + length]
        ptr += 5 + length

        if tag:
            try:
                result[tag] = value_bytes.decode("utf-8", errors="replace")
            except Exception:
                result[tag] = value_bytes.hex()

    return result


# ---------------------------------------------------------------------------
# Discovery engine
# ---------------------------------------------------------------------------


class DiscoveryResult:
    """Represents a discovered server."""

    def __init__(
        self,
        address: str,
        port: int,
        tlv: Dict[str, str],
        response_time_ms: float,
    ) -> None:
        self.address = address
        self.port = port
        self.tlv = tlv
        self.response_time_ms = response_time_ms

    @property
    def name(self) -> str:
        return self.tlv.get("NAME", "Unknown")

    @property
    def ip(self) -> str:
        return self.tlv.get("IPAD", self.address)

    @property
    def json_port(self) -> str:
        return self.tlv.get("JSON", "9000")

    @property
    def version(self) -> str:
        return self.tlv.get("VERS", "?")

    @property
    def uuid(self) -> str:
        return self.tlv.get("UUID", "?")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ip": self.ip,
            "address": self.address,
            "udp_port": self.port,
            "json_port": self.json_port,
            "version": self.version,
            "uuid": self.uuid,
            "response_time_ms": round(self.response_time_ms, 2),
            "tlv": self.tlv,
        }

    def __repr__(self) -> str:
        return (
            f"DiscoveryResult(name={self.name!r}, ip={self.ip}, "
            f"json={self.json_port}, version={self.version})"
        )


def discover_servers(
    target_address: str = "255.255.255.255",
    port: int = DISCOVERY_PORT,
    timeout: float = 5.0,
    repeat: int = 3,
    verbose: bool = True,
) -> List[DiscoveryResult]:
    """
    Send UDP discovery broadcasts and collect server responses.

    Parameters
    ----------
    target_address:
        Broadcast or unicast address to probe.
    port:
        UDP port to send to (default 3483).
    timeout:
        Total time to listen for responses (seconds).
    repeat:
        Number of discovery bursts to send.
    verbose:
        Print progress messages.

    Returns
    -------
    list of DiscoveryResult
        All unique servers that responded.
    """
    results: Dict[str, DiscoveryResult] = {}  # keyed by address:port
    packet = build_discovery_request()

    # Create UDP socket with broadcast enabled
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)

    # Bind to any available port
    try:
        sock.bind(("", 0))
    except OSError:
        sock.bind(("0.0.0.0", 0))

    local_port = sock.getsockname()[1]

    if verbose:
        print(f"[discovery] Bound to local port {local_port}")
        print(f"[discovery] Target: {target_address}:{port}")
        print(f"[discovery] Timeout: {timeout}s, bursts: {repeat}")
        print(f"[discovery] Packet: {len(packet)} bytes")
        print(f"[discovery] Packet hex: {packet.hex()}")
        print()

    start_time = time.monotonic()
    burst_count = 0
    next_burst = start_time

    try:
        while True:
            now = time.monotonic()
            elapsed = now - start_time

            if elapsed >= timeout:
                break

            # Send burst
            if burst_count < repeat and now >= next_burst:
                burst_count += 1
                if verbose:
                    print(
                        f"[discovery] Sending discovery burst "
                        f"{burst_count}/{repeat} to {target_address}:{port}"
                    )
                try:
                    sock.sendto(packet, (target_address, port))
                except OSError as e:
                    if verbose:
                        print(f"[discovery] Send failed: {e}")
                next_burst = now + 1.0

            # Receive responses
            try:
                data, addr = sock.recvfrom(RECV_BUFFER)
                recv_time = time.monotonic()
                response_ms = (recv_time - start_time) * 1000

                if data and data[0:1] == b"E":
                    tlv = parse_tlv_response(data)
                    key = f"{addr[0]}:{addr[1]}"

                    if key not in results:
                        result = DiscoveryResult(
                            address=addr[0],
                            port=addr[1],
                            tlv=tlv,
                            response_time_ms=response_ms,
                        )
                        results[key] = result

                        if verbose:
                            print(f"\n[discovery] ✓ Server found!")
                            print(f"  Response from: {addr[0]}:{addr[1]}")
                            print(f"  Response time: {response_ms:.1f}ms")
                            for tag, value in sorted(tlv.items()):
                                print(f"  {tag}: {value}")
                            print()
                    else:
                        if verbose:
                            print(
                                f"[discovery] (duplicate response from {addr[0]}:{addr[1]})"
                            )

                elif data and data[0:1] == b"D":
                    # Old-style discovery response
                    hostname = (
                        data[1:18]
                        .split(b"\x00")[0]
                        .decode("iso-8859-1", errors="replace")
                    )
                    if verbose:
                        print(
                            f"\n[discovery] ✓ Old-style server found: "
                            f"{hostname} at {addr[0]}:{addr[1]}"
                        )
                    key = f"{addr[0]}:{addr[1]}"
                    if key not in results:
                        results[key] = DiscoveryResult(
                            address=addr[0],
                            port=addr[1],
                            tlv={"NAME": hostname},
                            response_time_ms=response_ms,
                        )

            except socket.timeout:
                continue
            except OSError:
                continue

    finally:
        sock.close()

    return list(results.values())


# ---------------------------------------------------------------------------
# Resonance server launcher
# ---------------------------------------------------------------------------


def start_resonance_server() -> Optional[subprocess.Popen]:
    """
    Attempt to start the Resonance server in the background.

    Returns the Popen handle, or None if it couldn't be started.
    """
    resonance_dir = os.path.join(os.path.dirname(_PROJECT_ROOT), "resonance-server")

    if not os.path.isdir(resonance_dir):
        print(f"[resonance] Server directory not found: {resonance_dir}")
        return None

    print(f"[resonance] Starting Resonance server from {resonance_dir}")

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "resonance"],
            cwd=resonance_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            ),
        )
        # Give it a moment to start
        print("[resonance] Waiting 3 seconds for server to start...")
        time.sleep(3)

        if proc.poll() is not None:
            # Process already exited
            output = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            print(f"[resonance] Server exited immediately (code {proc.returncode})")
            if output:
                print(f"[resonance] Output:\n{output[:500]}")
            return None

        print("[resonance] Server started (PID {})".format(proc.pid))
        return proc

    except Exception as e:
        print(f"[resonance] Failed to start server: {e}")
        return None


def stop_resonance_server(proc: subprocess.Popen) -> None:
    """Stop a Resonance server process."""
    print(f"[resonance] Stopping server (PID {proc.pid})...")
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        print("[resonance] Server stopped.")
    except Exception as e:
        print(f"[resonance] Error stopping server: {e}")


# ---------------------------------------------------------------------------
# Integration with jivelite-py's SlimDiscovery
# ---------------------------------------------------------------------------


def try_jivelite_discovery() -> None:
    """
    Demonstrate using jivelite-py's own SlimDiscovery module to parse
    discovery responses — proving the ported code is compatible.
    """
    print("\n" + "=" * 60)
    print("Verifying jivelite-py SlimDiscovery compatibility")
    print("=" * 60)

    try:
        from jive.applets.SlimDiscovery.SlimDiscoveryApplet import (
            _parse_tlv_response,
            _slim_discovery_source,
        )

        # Build request using jivelite-py's own function
        request = _slim_discovery_source()
        print(f"\n[compat] jivelite-py discovery request: {len(request)} bytes")
        print(f"[compat] Starts with 'e': {request[0:1] == b'e'}")

        # Parse TLV tags from our request
        ptr = 1
        tags = []
        while ptr <= len(request) - 5:
            tag = request[ptr : ptr + 4].decode("ascii", errors="replace")
            length = request[ptr + 4]
            tags.append(tag)
            ptr += 5 + length

        print(f"[compat] Requested tags: {', '.join(tags)}")

        # Build a synthetic response to verify parsing
        response = b"E"
        test_data = {
            "NAME": "Test Resonance",
            "IPAD": "192.168.1.100",
            "JSON": "9000",
            "VERS": "7.999.999",
            "UUID": "test-uuid-1234",
        }
        for tag, value in test_data.items():
            encoded = value.encode("utf-8")
            response += tag.encode("ascii") + struct.pack("B", len(encoded)) + encoded

        parsed = _parse_tlv_response(response)
        print(f"\n[compat] Synthetic response parsed successfully:")
        for tag, value in sorted(parsed.items()):
            expected = test_data.get(tag, "?")
            match = "✓" if value == expected else "✗"
            print(f"  {match} {tag}: {value}")

        all_ok = all(parsed.get(t) == v for t, v in test_data.items())
        print(f"\n[compat] All tags match: {'✓ YES' if all_ok else '✗ NO'}")

    except ImportError as e:
        print(f"[compat] Could not import SlimDiscovery: {e}")

    # Also verify ChooseMusicSource is importable
    try:
        from jive.applets.ChooseMusicSource.ChooseMusicSourceApplet import (
            ChooseMusicSourceApplet,
        )
        from jive.applets.ChooseMusicSource.ChooseMusicSourceMeta import (
            ChooseMusicSourceMeta,
        )

        meta = ChooseMusicSourceMeta()
        print(f"\n[compat] ChooseMusicSourceMeta: jive_version={meta.jive_version()}")
        print(f"[compat] Default poll list: {meta.default_settings()['poll']}")

        applet = ChooseMusicSourceApplet()
        print(f"[compat] ChooseMusicSourceApplet: {applet}")
        print(f"[compat] Free returns True: {applet.free()}")

    except ImportError as e:
        print(f"[compat] Could not import ChooseMusicSource: {e}")


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

# ANSI color codes
BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner() -> None:
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════════╗
║      Jivelite-py — Server Discovery (UDP TLV)           ║
╚══════════════════════════════════════════════════════════╝{RESET}
""")


def print_results_table(results: List[DiscoveryResult]) -> None:
    if not results:
        print(f"\n{RED}{BOLD}No servers found.{RESET}")
        print(f"{DIM}Make sure a Lyrion Music Server or Resonance server")
        print(f"is running on the network and listening on port 3483.{RESET}")
        print()
        print("Tips:")
        print("  • Try:  python examples/discover_server.py --start-resonance")
        print("  • Or specify a direct IP:  --address 192.168.1.x")
        return

    print(f"\n{GREEN}{BOLD}Found {len(results)} server(s):{RESET}\n")

    # Table header
    print(
        f"  {'Name':<25} {'IP Address':<18} {'JSON Port':<12} {'Version':<15} {'UUID'}"
    )
    print(f"  {'─' * 25} {'─' * 18} {'─' * 12} {'─' * 15} {'─' * 36}")

    for r in results:
        print(
            f"  {BOLD}{r.name:<25}{RESET} "
            f"{r.ip:<18} "
            f"{r.json_port:<12} "
            f"{r.version:<15} "
            f"{DIM}{r.uuid}{RESET}"
        )

    print()

    # Connection info
    for i, r in enumerate(results):
        json_url = f"http://{r.ip}:{r.json_port}/jsonrpc.js"
        print(f"  {CYAN}Server {i + 1} JSON-RPC endpoint:{RESET} {json_url}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover Lyrion/Resonance servers on the local network via UDP TLV protocol.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Broadcast discovery, 5s timeout
  %(prog)s --address 192.168.1.42   # Unicast to specific IP
  %(prog)s --timeout 10 --repeat 5  # Longer scan
  %(prog)s --start-resonance        # Start Resonance, then discover
  %(prog)s --json                   # Machine-readable output
        """,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="How long to listen for responses (seconds, default: 5)",
    )
    parser.add_argument(
        "--address",
        type=str,
        default="255.255.255.255",
        help="Broadcast/unicast address to probe (default: 255.255.255.255)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DISCOVERY_PORT,
        help=f"UDP port to send to (default: {DISCOVERY_PORT})",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Number of discovery bursts to send (default: 3)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--start-resonance",
        action="store_true",
        help="Start the Resonance server in background first",
    )
    parser.add_argument(
        "--no-compat-check",
        action="store_true",
        help="Skip jivelite-py compatibility verification",
    )

    args = parser.parse_args()

    if not args.json:
        print_banner()

    # Optionally start Resonance server
    resonance_proc = None
    if args.start_resonance:
        resonance_proc = start_resonance_server()
        if resonance_proc is None:
            print(
                f"{YELLOW}[warn] Could not start Resonance server, continuing with discovery anyway{RESET}\n"
            )

    try:
        # Run discovery
        results = discover_servers(
            target_address=args.address,
            port=args.port,
            timeout=args.timeout,
            repeat=args.repeat,
            verbose=not args.json,
        )

        if args.json:
            output = {
                "servers": [r.to_dict() for r in results],
                "scan": {
                    "target": args.address,
                    "port": args.port,
                    "timeout": args.timeout,
                    "bursts": args.repeat,
                    "found": len(results),
                },
            }
            print(json_mod.dumps(output, indent=2))
        else:
            print_results_table(results)

        # Compatibility check
        if not args.json and not args.no_compat_check:
            try_jivelite_discovery()

    finally:
        # Stop Resonance if we started it
        if resonance_proc is not None:
            stop_resonance_server(resonance_proc)

    # Exit code
    sys.exit(0 if results else 1)


if __name__ == "__main__":
    main()
