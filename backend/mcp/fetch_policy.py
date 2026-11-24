from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from typing import Any

from .exceptions import MCPSecurityError

# Allow only standard secure web protocols and ports
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}

# Well-known cloud instance metadata endpoints (IPv4 and IPv6)
METADATA_IPS = {
    "169.254.169.254",         # AWS, GCP, Azure, OpenStack instance metadata
    "::ffff:169.254.169.254",   # IPv4-mapped IPv6 metadata representation
    "fd00:ec2::254",           # AWS IPv6 instance metadata
    "fe80::e5:1c:c:30",        # Azure link-local wire
    "100.100.100.200",         # Alibaba Cloud instance metadata
}

METADATA_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.goog",
    "metadata.internal",
    "instance-data",
    "instance-data.ec2.internal",
    "169.254.169.254",
    "100.100.100.200",
}

# Standard forbidden local host patterns
LOCAL_HOST_NAMES = {
    "localhost",
    "local",
    "broadcasthost",
    "ip6-localhost",
    "ip6-loopback",
}


class PolicyValidationError(str):
    """
    Validation error message string that preserves backward compatibility
    as a `str` while carrying structured `error_type`.
    """
    error_type: str

    def __new__(cls, message: str, error_type: str = "SecurityViolation"):
        obj = super().__new__(cls, message)
        obj.error_type = error_type
        return obj


class FetchSecurityPolicy:
    """
    Security Policy, URL Validation, and SSRF Protection for Web Content Retrieval.

    Enforces:
    1. Protocol allowlist: HTTP and HTTPS only. Rejects file, ftp, javascript, data, gopher, etc.
    2. Host validation: Prohibits localhost, loopback, private RFC-1918, link-local RFC-3927,
       multicast RFC-5771, reserved RFC-1112/6890, and cloud instance metadata services.
    3. DNS Resolution Guard: Resolves hostnames and validates all resolved IP addresses
       against prohibited network boundaries prior to dispatch.
    4. Anti-Obfuscation: Defends against integer IP, octal, hex, and IPv4-mapped IPv6 addresses.
    5. Anti-Credential Leakage: Prohibits URLs with embedded userinfo (e.g. http://user:pass@host).
    6. Response Constraints: Enforces character length and timeout boundaries.
    """

    def __init__(
        self,
        allowed_schemes: set[str] | None = None,
        allowed_ports: set[int] | None = None,
        max_response_length: int = 50_000,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.allowed_schemes = allowed_schemes or ALLOWED_SCHEMES
        self.allowed_ports = allowed_ports or ALLOWED_PORTS
        self.max_response_length = max_response_length
        self.request_timeout_seconds = request_timeout_seconds

    def is_ip_prohibited(self, ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> tuple[bool, str]:
        """
        Determines whether a resolved IP address violates security isolation boundaries.
        Returns:
            (is_prohibited, reason)
        """
        ip_str = str(ip_obj)

        # 1. Cloud instance metadata
        if ip_str in METADATA_IPS:
            return True, f"Access to cloud instance metadata endpoint ({ip_str}) is blocked."

        # 2. Loopback addresses (127.0.0.0/8, ::1)
        if ip_obj.is_loopback:
            return True, f"Access to loopback address ({ip_str}) is blocked."

        # 3. Private network addresses (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
        if ip_obj.is_private:
            return True, f"Access to private internal network ({ip_str}) is blocked."

        # 4. Link-local addresses (169.254.0.0/16, fe80::/10)
        if ip_obj.is_link_local:
            return True, f"Access to link-local address ({ip_str}) is blocked."

        # 5. Multicast addresses (224.0.0.0/4, ff00::/8)
        if ip_obj.is_multicast:
            return True, f"Access to multicast address ({ip_str}) is blocked."

        # IPv4-mapped IPv6 check (e.g. ::ffff:127.0.0.1)
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
            return self.is_ip_prohibited(ip_obj.ipv4_mapped)

        # RFC 6052 Well-Known Prefix for NAT64 (64:ff9b::/96)
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj in ipaddress.IPv6Network("64:ff9b::/96"):
            embedded_ipv4 = ipaddress.IPv4Address(ip_obj.packed[-4:])
            return self.is_ip_prohibited(embedded_ipv4)

        # 6. Reserved addresses (0.0.0.0/8, 240.0.0.0/4, etc.)
        if ip_obj.is_reserved:
            return True, f"Access to reserved network address ({ip_str}) is blocked."

        # 7. Unspecified address (0.0.0.0, ::)
        if ip_obj.is_unspecified:
            return True, f"Access to unspecified address ({ip_str}) is blocked."

        return False, ""

    def validate_url(self, raw_url: str) -> tuple[bool, str, str]:
        """
        Validates and canonicalizes a target URL.
        Returns:
            (is_valid, canonical_url, error_message)
        """
        if not raw_url or not isinstance(raw_url, str):
            return False, "", PolicyValidationError("URL must be a non-empty string.", error_type="ValidationError")

        url_clean = raw_url.strip()

        # Scheme validation
        try:
            parsed = urllib.parse.urlparse(url_clean)
        except Exception as e:
            return False, "", PolicyValidationError(f"Malformed URL: {e}", error_type="ValidationError")

        scheme = (parsed.scheme or "").lower()
        if not scheme:
            return False, "", PolicyValidationError("Missing URL scheme. Only HTTP and HTTPS are permitted.", error_type="ValidationError")

        if scheme not in self.allowed_schemes:
            return False, "", PolicyValidationError(f"Unsupported URL scheme '{scheme}'. Only HTTP and HTTPS are permitted.", error_type="SecurityViolation")

        # Port validation
        if parsed.port and parsed.port not in self.allowed_ports:
            return False, "", PolicyValidationError(f"Port '{parsed.port}' is blocked for web retrieval. Allowed ports: {sorted(self.allowed_ports)}.", error_type="SecurityViolation")

        # Hostname validation
        hostname = parsed.hostname
        if not hostname:
            return False, "", PolicyValidationError("URL must include a valid hostname.", error_type="ValidationError")

        hostname_lower = hostname.lower().strip(".")

        # Prohibit localhost aliases and local domains
        if (
            hostname_lower in LOCAL_HOST_NAMES
            or hostname_lower.endswith(".local")
            or hostname_lower.endswith(".localhost")
            or hostname_lower.endswith(".internal")
        ):
            return False, "", PolicyValidationError(f"Access to local or internal host '{hostname}' is blocked.", error_type="SecurityViolation")

        # Metadata hostnames
        if hostname_lower in METADATA_HOSTNAMES:
            return False, "", PolicyValidationError(f"Access to metadata service '{hostname}' is blocked.", error_type="SecurityViolation")

        # Prohibit embedded credentials (e.g. http://user:pass@host)
        if parsed.username or parsed.password:
            return False, "", PolicyValidationError("Embedded credentials in URLs are prohibited.", error_type="SecurityViolation")

        # Evaluate IP literal vs Domain
        # Handle integer representation e.g. http://2130706433
        if hostname_lower.isdigit():
            try:
                ip_int = int(hostname_lower)
                ip_obj = ipaddress.ip_address(ip_int)
                prohibited, reason = self.is_ip_prohibited(ip_obj)
                if prohibited:
                    return False, "", PolicyValidationError(reason, error_type="SecurityViolation")
            except ValueError:
                return False, "", PolicyValidationError(f"Invalid integer IP representation '{hostname}'.", error_type="ValidationError")
        else:
            try:
                # Direct IP literal check (IPv4 or IPv6)
                ip_obj = ipaddress.ip_address(hostname_lower)
                prohibited, reason = self.is_ip_prohibited(ip_obj)
                if prohibited:
                    return False, "", PolicyValidationError(reason, error_type="SecurityViolation")
            except ValueError:
                # Hostname is a domain name -> resolve via DNS and evaluate all addresses
                try:
                    port = parsed.port or (443 if scheme == "https" else 80)
                    addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
                    if not addr_info:
                        return False, "", PolicyValidationError(f"Could not resolve host '{hostname}'.", error_type="DNSResolutionError")

                    for family, socktype, proto, canonname, sockaddr in addr_info:
                        ip_str = sockaddr[0]
                        try:
                            ip_obj = ipaddress.ip_address(ip_str)
                            prohibited, reason = self.is_ip_prohibited(ip_obj)
                            if prohibited:
                                return False, "", PolicyValidationError(f"Host '{hostname}' resolved to prohibited address ({ip_str}): {reason}", error_type="SecurityViolation")
                        except ValueError:
                            return False, "", PolicyValidationError(f"Host '{hostname}' resolved to invalid address '{ip_str}'.", error_type="SecurityViolation")
                except socket.gaierror as ge:
                    return False, "", PolicyValidationError(f"DNS resolution failed for '{hostname}': {ge}", error_type="DNSResolutionError")
                except Exception as e:
                    return False, "", PolicyValidationError(f"Failed to validate host '{hostname}': {e}", error_type="NetworkError")

        # Canonicalize URL (rebuild clean without credentials or fragments)
        port_str = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        canonical_url = urllib.parse.urlunparse((
            scheme,
            f"{hostname_lower}{port_str}",
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",  # strip fragment
        ))

        return True, canonical_url, ""
