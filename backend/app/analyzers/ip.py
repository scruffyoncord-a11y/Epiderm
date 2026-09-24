"""IP analyzer: reverse DNS (PTR) with forward confirmation.

Reverse DNS names the host behind an IP. That says a little about where a message really came
from: a home broadband line, a cloud or hosting server, or a VPN / Tor exit. It is a heuristic:
many legitimate networks have no PTR record, and attackers can set their own PTR names. So:

- a missing record is "unknown", never suspicious;
- a name that does not resolve back to the same IP (not forward-confirmed) is only a weak signal;
- hosting / anonymiser names are moderate signals that need other evidence to matter;
- private, loopback and link-local addresses are never looked up (no internal DNS leaks).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..models import Category, Direction, Signal

LOOKUP_TIMEOUT = 3.0

ANONYMISER = re.compile(
    r"(^|[.-])(tor-?exit|exit-?node|exitnode|tor|vpn|proxy|anonymi[sz]er|mullvad|nordvpn|expressvpn|"
    r"privateinternetaccess|surfshark|proton)([.-]|\d|$)", re.I)
HOSTING = re.compile(
    r"amazonaws\.com|compute\.internal|googleusercontent\.com|bc\.googleusercontent|cloudapp\.azure\.com|"
    r"digitalocean|linode|vultr|choopa|ovh\.|hetzner|contabo|scaleway|m247|leaseweb|"
    r"(^|[.-])(vps|dedicated|colo|datacenter|datacentre|server|hosting|cloud)([.-]|\d|$)", re.I)
RESIDENTIAL = re.compile(
    r"(^|[.-])(broadband|dsl|adsl|vdsl|cable|dyn|dynamic|pool|cust|customer|ftth|fibre|fiber|home|"
    r"static-\d|mobile|cgnat|bsnl|jio|airtel|hathway|tikona|act-?fibernet)([.-]|\d|$)", re.I)


class Resolver(Protocol):
    def reverse(self, ip: str) -> Optional[str]: ...
    def forward(self, name: str) -> list[str]: ...


class SocketResolver:
    """System resolver with a hard timeout (socket calls have none of their own)."""

    def _run(self, fn, *args):
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fn, *args)
            try:
                return fut.result(timeout=LOOKUP_TIMEOUT)
            except (FutureTimeout, OSError):
                return None

    def reverse(self, ip: str) -> Optional[str]:
        res = self._run(socket.gethostbyaddr, ip)
        return res[0].rstrip(".").lower() if res else None

    def forward(self, name: str) -> list[str]:
        res = self._run(socket.getaddrinfo, name, None)
        return sorted({r[4][0] for r in res}) if res else []


@dataclass
class IpResult:
    ip: str
    ptr: Optional[str] = None
    forward_confirmed: Optional[bool] = None
    kind: str = "unknown"  # anonymiser | hosting | residential | unknown | private | invalid
    signals: list[Signal] = field(default_factory=list)


def _sig(id_, finding, direction, strength, confidence, evidence):
    return Signal(id=id_, category=Category.ip, finding=finding, direction=direction,
                  strength=strength, confidence=confidence, evidence=evidence)


def classify(ptr: str) -> str:
    if ANONYMISER.search(ptr):
        return "anonymiser"
    if HOSTING.search(ptr):
        return "hosting"
    if RESIDENTIAL.search(ptr):
        return "residential"
    return "unknown"


def analyze_ip(ip_text: str, resolver: Optional[Resolver] = None) -> IpResult:
    ip_text = (ip_text or "").strip()
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return IpResult(ip=ip_text, kind="invalid", signals=[_sig(
            "ip.invalid", "That is not a valid IP address", Direction.unknown, 0.0, 1.0, ip_text[:60])])

    if not addr.is_global:
        return IpResult(ip=str(addr), kind="private", signals=[_sig(
            "ip.not_public", "Private or local address, so no reverse DNS lookup was made", Direction.unknown,
            0.0, 1.0, str(addr))])

    resolver = resolver or SocketResolver()
    ptr = resolver.reverse(str(addr))
    if not ptr:
        return IpResult(ip=str(addr), signals=[_sig(
            "ip.rdns_missing", "No reverse DNS record (common, and not suspicious on its own)", Direction.unknown,
            0.0, 1.0, str(addr))])

    confirmed = str(addr) in {str(ipaddress.ip_address(a)) for a in resolver.forward(ptr)}
    kind = classify(ptr)
    signals: list[Signal] = []

    if kind == "anonymiser":
        signals.append(_sig("ip.rdns_anonymiser", "Reverse DNS points to a VPN, proxy or Tor exit",
                            Direction.suspicious, 0.6, 0.7, f"{addr} -> {ptr}"))
    elif kind == "hosting":
        signals.append(_sig("ip.rdns_hosting", "Reverse DNS points to a cloud or hosting server, not a home or office line",
                            Direction.suspicious, 0.4, 0.6, f"{addr} -> {ptr}"))
    elif kind == "residential":
        signals.append(_sig("ip.rdns_residential", "Reverse DNS looks like an ordinary home or mobile connection",
                            Direction.reassuring, 0.3, 0.5, f"{addr} -> {ptr}"))
    else:
        signals.append(_sig("ip.rdns_named", f"Reverse DNS name is {ptr} (no clear category)",
                            Direction.neutral, 0.0, 0.5, f"{addr} -> {ptr}"))

    if not confirmed:
        signals.append(_sig("ip.rdns_unconfirmed",
                            "The reverse DNS name does not resolve back to this IP (names can be set by whoever controls the IP)",
                            Direction.suspicious, 0.3, 0.5, f"{ptr} does not resolve to {addr}"))
    return IpResult(ip=str(addr), ptr=ptr, forward_confirmed=confirmed, kind=kind, signals=signals)
