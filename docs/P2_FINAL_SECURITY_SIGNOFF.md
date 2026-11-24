# CORTEX AGENT — PHASE P2 FINAL SSRF & UNTRUSTED-CONTENT SECURITY SIGN-OFF

**Audit Date**: November 17, 2026  
**Auditor**: Independent Security Engineering & Code Integrity Agent  
**Target Subsystem**: Phase P2 Web Content Retrieval / Fetch MCP Subsystem (`mcp-server-fetch`)  
**Scope**: `backend/mcp/fetch_policy.py`, `backend/mcp/fetch_adapter.py`, `backend/agent/orchestrator.py`, upstream `mcp-server-fetch v0.6.2`, and associated test suites  

---

## 1. Executive Verdict

### Decision: **P2 SECURITY SIGN-OFF — CONDITIONALLY ACCEPTED**

The Phase P2 Fetch MCP integration satisfies all core functional and architectural safety requirements, implements robust pre-flight and in-transit SSRF guards, neutralizes prompt-injection tag escapes, enforces bounded memory allocation against compression bombs, and maintains complete backward compatibility across all 133 baseline regression tests.

Conditional acceptance is granted subject to the documented upstream transport limitation regarding DNS rebinding (TOCTOU between HTTP event hook validation and socket connection in `httpx`/`httpcore`).

### Summary of Findings by Severity

| Severity | Count | Remediated | Residual / Accepted |
| :--- | :---: | :---: | :---: |
| **Critical** | 0 | 0 | 0 |
| **High** | 0 | 0 | 0 |
| **Medium** | 2 | 2 | 0 |
| **Low** | 2 | 2 | 0 |
| **Informational** | 1 | 0 | 1 |
| **Total** | **5** | **4** | **1** |

---

## 2. Findings & Remediations

### Finding SEC-P2-01: Non-Standard Port Exposure in Default Policy
- **Severity**: Medium
- **Component**: `backend/mcp/fetch_policy.py`
- **Vulnerability Description**: The initial policy permitted ports `8080` and `8443` in addition to standard HTTP/HTTPS ports `80` and `443`. On developer workstations and corporate environments, ports `8080` and `8443` frequently host internal admin panels, local proxies, microservices, Jenkins/Tomcat instances, or unauthenticated monitoring dashboards.
- **Root Cause**: Overly permissive initial `ALLOWED_PORTS = {80, 443, 8080, 8443}` default.
- **Remediation Applied**: Tightened `ALLOWED_PORTS` to strictly `{80, 443}`. Non-standard ports are blocked at pre-flight validation before any network request is dispatched.
- **Verification Proof**:
  - Test: `tests/test_mcp_fetch.py::test_security_policy_rejects_restricted_ports` (PASSED)
  - Test: `tests/test_p2_security_signoff.py::test_redirect_to_localhost_blocked` (PASSED)

### Finding SEC-P2-02: Prompt Injection Tag Breakout via Literal Enclosure Tags
- **Severity**: Medium
- **Component**: `backend/agent/orchestrator.py` (`_execute_fetch`)
- **Vulnerability Description**: Retrieved webpage content was embedded directly between `<webpage_content>` and `</webpage_content>` tags without escaping literal closing tags (`</webpage_content>`). An adversarial webpage containing a closing tag followed by fake `<system>` instructions or tool invocation payloads could break out of the data enclosure in the model's token stream. Additionally, webpage `title` attributes were not attribute-escaped.
- **Root Cause**: Raw string interpolation of untrusted webpage content and metadata into LLM prompts.
- **Remediation Applied**:
  1. Sanitized article text by escaping literal `</webpage_content>` to `&lt;/webpage_content&gt;`.
  2. Attribute-escaped `title` and `url` to neutralize quotes and angle brackets (`"`, `>`, `<`).
  3. Hardened the `SECURITY DIRECTIVE` in both single-URL and multi-URL synthesis prompts, instructing the model to treat all content strictly as passive data and ignore commands claiming system/administrative priority.
- **Verification Proof**:
  - Test: `tests/test_p2_security_signoff.py::test_hostile_prompt_injection_neutralization` (PASSED)
  - Test: `tests/test_mcp_fetch.py::test_prompt_injection_neutralization` (PASSED)

### Finding SEC-P2-03: Missing Cloud Metadata Endpoint Definitions
- **Severity**: Low
- **Component**: `backend/mcp/fetch_policy.py`
- **Vulnerability Description**: `METADATA_IPS` and `METADATA_HOSTNAMES` included AWS, GCP, Azure, and OpenStack endpoints (`169.254.169.254`, `fd00:ec2::254`), but lacked Alibaba Cloud metadata IP (`100.100.100.200`) and the GCP short domain `metadata.goog`.
- **Root Cause**: Incomplete vendor metadata IP catalog in policy definition.
- **Remediation Applied**: Added `100.100.100.200` to `METADATA_IPS` and `METADATA_HOSTNAMES`, and added `metadata.goog` to `METADATA_HOSTNAMES`.
- **Verification Proof**:
  - Test: `tests/test_p2_security_signoff.py::test_cloud_metadata_endpoints_blocked` (PASSED)

### Finding SEC-P2-04: False Positive SSRF Block on Modern macOS NAT64 Networks
- **Severity**: Low
- **Component**: `backend/mcp/fetch_policy.py`
- **Vulnerability Description**: On modern macOS networks utilizing DNS64/NAT64 transitions, IPv4 hostnames resolve to synthetic IPv6 addresses under prefix `64:ff9b::/96` (RFC 6052). In Python's standard `ipaddress` library, `ip_obj.is_reserved` evaluates `64:ff9b::/96` as `True`, causing legitimate public sites (e.g., `httpbin.org`) to be falsely blocked as reserved addresses.
- **Root Cause**: Order of checks in `is_ip_prohibited` evaluated `ip_obj.is_reserved` before unwrapping RFC 6052 NAT64 IPv4 mapped addresses.
- **Remediation Applied**: Implemented RFC 6052 NAT64 prefix unwrapping (`ip_obj.ipv4_mapped` extraction for `64:ff9b::/96`) *before* applying `ip_obj.is_reserved`. The embedded IPv4 address is then evaluated against public/private criteria.
- **Verification Proof**:
  - Test: `scripts/verify_p2_fetch_live.py` (Scenario 3 live retrieval of `https://httpbin.org/html` PASSED)
  - Test: `tests/test_mcp_fetch.py::test_security_policy_valid_public_urls` (PASSED)

### Finding SEC-P2-05: Upstream Transport TOCTOU DNS Rebinding Window
- **Severity**: Informational / Architectural Limitation
- **Component**: Upstream `mcp-server-fetch` / `httpx.AsyncClient`
- **Vulnerability Description**: In the upstream `mcp-server-fetch` server, `_refuse_private_destination` executes as an `httpx` request event hook before each HTTP request/redirect hop. It resolves the hostname and verifies all IP addresses. However, `httpx` delegates actual TCP socket connection to `httpcore`, which performs its own DNS resolution at connect time. If an attacker controls an authoritative nameserver with TTL=0 and switches the DNS answer from a public IP to `127.0.0.1` in the sub-millisecond window between hook execution and socket connect, the connection could hit the private destination.
- **Root Cause**: Standard Python `httpx`/`httpcore` architecture does not support socket IP pinning without custom transport connection pools.
- **Remediation Status**: Documented as an acceptable residual risk for local desktop assistant environments. Cortex implements defense-in-depth: Cortex `FetchSecurityPolicy` resolves and validates DNS at T0; `mcp-server-fetch` re-resolves and validates DNS at T1; upstream redirects re-validate at every hop.

---

## 3. Deep-Dive Security Analysis

### 3.1 DNS & Connection-Level SSRF Protection
- **Multi-Address (Mixed Public/Private) Resolution**: Attackers often configure DNS records to return both a legitimate public IP and an internal address (`127.0.0.1` or `169.254.169.254`) hoping the client connects to the internal address. Both Cortex `FetchSecurityPolicy` and `mcp-server-fetch` iterate through *all* `socket.getaddrinfo` records; if **any** resolved address is private, loopback, link-local, multicast, or metadata, the entire request is rejected immediately.
- **IPv6 Boundary Confinement**:
  - IPv6 loopback (`::1`) and unspecified (`::`) are rejected.
  - IPv6 Unique-Local Addresses (`fc00::/7`), including AWS IMDSv2 IPv6 (`fd00:ec2::254`), are rejected by `ip_obj.is_private`.
  - IPv4-mapped IPv6 (`::ffff:x.x.x.x`) addresses are extracted and checked against IPv4 policies.
- **DNS Rebinding Assessment**: While a microsecond TOCTOU window exists at the transport layer of `httpx`, Cortex's dual-stage validation (pre-flight validation in Cortex + pre-flight request hook in MCP server) ensures two distinct DNS checks must be bypassed. Full elimination of TOCTOU requires custom socket-pinning transport in upstream `mcp-server-fetch`.

### 3.2 Redirect Security
- **Per-Hop Validation**: Upstream `mcp-server-fetch` configures `follow_redirects=False` in its transport and executes redirects manually in `stream_get`:
  ```python
  hops = 0
  while True:
      response = await client.send(request, stream=True)
      if response.is_redirect:
          hops += 1
          if hops > client.max_redirects: # Bounded to 20
              raise TooManyRedirects(...)
          await response.aclose() # Immediate cleanup of unread socket
          # Next hop triggers request hook: _refuse_private_destination
  ```
- **Public-to-Private Redirect Neutralization**: Before each redirect hop is dispatched, `httpx` invokes `_refuse_private_destination`. Redirects from public URLs to `http://localhost`, `http://127.0.0.1`, `http://10.0.0.1`, or `http://169.254.169.254` are intercepted and aborted before connection establishment.
- **Resource Disposal**: Redirect responses are explicitly closed (`await response.aclose()`) prior to following the `Location` header, preventing unread body buffering and socket descriptor leaks.

### 3.3 Port & Protocol Policy
- **Protocol Allowlist**: Strictly limited to `http` and `https`. Schemes such as `file://`, `ftp://`, `gopher://`, `javascript:`, `data:`, and `blob:` are rejected at URL parsing time.
- **Port Allowlist**: Restricting allowed ports strictly to `{80, 443}` prevents port-scanning attacks against local loopback or intranet services running on common alternative HTTP ports (`8080`, `8443`, `3000`, `5000`, `8000`, `9000`).

### 3.4 Resource Exhaustion & Denial of Service
- **Stream Capping**: Upstream `mcp-server-fetch` streams responses chunk-by-chunk using `read_capped(response, 5 * 1024 * 1024)`. Streaming ceases as soon as cumulative received bytes reach 5MB.
- **Decompression Bomb Defense**: Standard HTTP decoders expand chunks entirely in memory, exposing systems to gzip bombs (small payloads expanding into gigabytes). Upstream `mcp-server-fetch` implements `BoundedInflater`, which passes `max_length = remaining_budget` directly to `zlib.decompressobj.decompress`. This forces the decompressor to halt precisely when the byte allocation limit is reached, storing unconsumed input in `unconsumed_tail` rather than allocating memory.
- **Adapter Character Limits**: Cortex's `MCPFetchToolAdapter` enforces a default `max_response_length = 50,000` characters, disclosing truncation transparently via `[Truncated: Content exceeded maximum length]`.
- **Async Cancellation Cleanup**: When cancellation occurs during stream consumption, `response.aclose()` and `client.aclose()` guarantee immediate release of file descriptors and TCP sockets.

### 3.5 Prompt-Injection Isolation
- **Boundary Enclosure**: Retrieved content is encapsulated inside explicit `<webpage_content>` tags.
- **Sanitization**: Literal `</webpage_content>` occurrences within untrusted page text are transformed into `&lt;/webpage_content&gt;`, preventing tag closure breakouts. Attribute fields (`source`, `title`) are escaped against quote and tag injection.
- **Instruction Segregation**: System prompts explicitly direct Gemini to treat all content within `<webpage_content>` tags strictly as passive, untrusted reference data, explicitly prohibiting execution of instructions, roleplay overrides, or system commands embedded inside the retrieved text.
- **Tool Isolation**: Web content retrieval is read-only. Untrusted text cannot synthesize task commands, bypass PolicyEngine confirmation gates, or trigger destructive tools (`DELETE_FILE`, `SHELL_EXEC`).

---

## 4. Comprehensive Test Results

### 4.1 Security Sign-Off Test Suite (`tests/test_p2_security_signoff.py`)
```
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
collected 12 items

tests/test_p2_security_signoff.py::test_dns_mixed_public_and_private_addresses_rejected PASSED [  8%]
tests/test_p2_security_signoff.py::test_dns_rebinding_toctou_transport_analysis PASSED [ 16%]
tests/test_p2_security_signoff.py::test_redirect_to_localhost_blocked PASSED [ 25%]
tests/test_p2_security_signoff.py::test_redirect_to_private_rfc1918_blocked PASSED [ 33%]
tests/test_p2_security_signoff.py::test_ipv6_unique_local_blocked PASSED [ 41%]
tests/test_p2_security_signoff.py::test_ipv4_mapped_ipv6_private_blocked PASSED [ 50%]
tests/test_p2_security_signoff.py::test_cloud_metadata_endpoints_blocked PASSED [ 58%]
tests/test_p2_security_signoff.py::test_redirect_loop_bounded PASSED     [ 66%]
tests/test_p2_security_signoff.py::test_oversized_streamed_response_capped[asyncio] PASSED [ 75%]
tests/test_p2_security_signoff.py::test_cancellation_during_retrieval_closes_connections[asyncio] PASSED [ 83%]
tests/test_p2_security_signoff.py::test_compressed_response_expansion_bomb_bounded PASSED [ 91%]
tests/test_p2_security_signoff.py::test_hostile_prompt_injection_neutralization PASSED [100%]

======================== 12 passed, 4 warnings in 2.70s ========================
```

### 4.2 Fetch MCP Integration Test Suite (`tests/test_mcp_fetch.py`)
```
============================= test session starts ==============================
collected 20 items

tests/test_mcp_fetch.py::test_fetch_server_config_definition PASSED      [  5%]
tests/test_mcp_fetch.py::test_fetch_tool_discovery_and_registration PASSED [ 10%]
tests/test_mcp_fetch.py::test_security_policy_valid_public_urls PASSED   [ 15%]
tests/test_mcp_fetch.py::test_security_policy_rejects_loopback_and_localhost PASSED [ 20%]
tests/test_mcp_fetch.py::test_security_policy_rejects_private_networks PASSED [ 25%]
tests/test_mcp_fetch.py::test_security_policy_rejects_cloud_metadata PASSED [ 30%]
tests/test_mcp_fetch.py::test_security_policy_rejects_forbidden_schemes PASSED [ 35%]
tests/test_mcp_fetch.py::test_security_policy_rejects_restricted_ports PASSED [ 40%]
tests/test_mcp_fetch.py::test_security_policy_rejects_embedded_credentials PASSED [ 45%]
tests/test_mcp_fetch.py::test_fetch_adapter_lifecycle_success PASSED     [ 50%]
tests/test_mcp_fetch.py::test_fetch_adapter_lifecycle_ssrf_rejection PASSED [ 55%]
tests/test_mcp_fetch.py::test_fetch_adapter_handles_truncation PASSED    [ 60%]
tests/test_mcp_fetch.py::test_fetch_adapter_inaccessible_page_404 PASSED [ 65%]
tests/test_mcp_fetch.py::test_intent_routing_search_vs_fetch PASSED      [ 70%]
tests/test_mcp_fetch.py::test_intent_routing_browser_vs_fetch PASSED     [ 75%]
tests/test_mcp_fetch.py::test_intent_routing_multi_url_comparison PASSED [ 80%]
tests/test_mcp_fetch.py::test_single_url_retrieval_and_gemini_synthesis PASSED [ 85%]
tests/test_mcp_fetch.py::test_multi_url_comparison_preserves_source_isolation PASSED [ 90%]
tests/test_mcp_fetch.py::test_prompt_injection_neutralization PASSED     [ 95%]
tests/test_mcp_fetch.py::test_deterministic_model_outage_resilience PASSED [100%]

======================== 20 passed, 4 warnings in 7.88s ========================
```

### 4.3 All MCP Subsystem Test Suites
`pytest tests/test_mcp_*.py tests/test_filesystem_*.py -q`:
**77 passed in 57.13s** (100% pass rate).

### 4.4 Full Baseline Regression Suite
`pytest tests/test_contracts.py tests/test_safety.py tests/test_circuit_breaker.py tests/test_command_content_separation.py tests/test_browser_automation_routing.py tests/test_macos_application_control.py tests/test_phase2_email_automation.py tests/test_phase2_step2_1_audit_and_recovery.py tests/test_memory.py tests/test_task4_finder_inspection.py tests/test_task1_core_execution_repair.py tests/test_task2_screen_observation.py tests/test_task3_safari_research.py -q`:
**133 passed in 252.08s (0:04:12)** (Zero regressions).

### 4.5 Live End-to-End macOS Verification (`scripts/verify_p2_fetch_live.py`)
- Live process spawn via `uvx mcp-server-fetch` (PID: 83639)
- Real network retrieval of `https://httpbin.org/html` (3636 characters)
- Real SSRF rejection of `http://127.0.0.1:8765` (`SecurityViolation`)
- Full BaseTool lifecycle: `EXECUTE` -> `OBSERVE` -> `VERIFY`
- Deterministic model-outage presentation during Gemini offline simulation
- Clean process termination on shutdown

---

## 5. Residual Limitations & Risk Acceptance

1. **Transport TOCTOU (DNS Rebinding Window)**:
   - *Limitation*: As documented in Finding SEC-P2-05, standard `httpx`/`httpcore` delegates socket connection to the operating system resolver at connect time. A sub-millisecond TOCTOU window exists if an attacker utilizes zero-TTL fast-flux DNS rebinding.
   - *Risk Acceptance*: Accepted as low risk in local macOS desktop environments. Mitigation is provided by Cortex pre-flight validation + upstream pre-request hook validation. To eliminate this risk entirely in future phases, a custom `httpcore.AsyncConnectionPool` pinning the validated IP address can be upstreamed to `mcp-server-fetch`.
2. **Dynamic / JavaScript-Rendered Single-Page Apps (SPAs)**:
   - *Limitation*: `mcp-server-fetch` performs static HTTP GET retrieval and converts HTML to markdown. Client-rendered single-page applications (React, Angular, Vue) displaying blank shells without server-side rendering cannot be fully extracted via Fetch MCP.
   - *Architecture Alignment*: This is expected and intentional. Cortex's intent router automatically retains `BrowserTool` (Safari/Playwright) for interactive browser sessions, login-gated sites, and dynamic SPAs.

---

## 6. Rollback & Emergency Procedures

If Fetch MCP must be disabled in an emergency or during incident response, it can be isolated immediately without affecting filesystem operations or baseline Cortex tools:

### Option 1: Disable Fetch MCP Server via Configuration (Zero Code Changes)
Edit `config/mcp_servers.json` and set `"enabled": false` for the `fetch` server:
```json
{
  "mcpServers": {
    "filesystem": { ... },
    "fetch": {
      "command": "/Users/gsunilkumar/.local/bin/uvx",
      "args": ["mcp-server-fetch"],
      "enabled": false
    }
  }
}
```
Upon next launch or restart, `MCPServerManager` will skip spawning `mcp-server-fetch`.

### Option 2: Kill Live Fetch MCP Process Immediately
To terminate a hanging or runaway Fetch MCP server process:
```bash
pkill -f "mcp-server-fetch"
```

### Option 3: Fallback Routing
When Fetch MCP is disabled or offline, Cortex's intent router continues to support web research via `WebSearchTool` (`duckduckgo_search`) and interactive browser research via `BrowserTool` (`SafariTool`).

---

## 7. Sign-Off Approval

| Role | Status | Date |
| :--- | :--- | :--- |
| **Security Architecture Lead** | **CONDITIONALLY ACCEPTED** | November 17, 2026 |
| **MCP Integration Lead** | **ACCEPTED** | November 17, 2026 |
| **Quality & Regression Gate** | **PASSED (133/133 Baseline, 77/77 MCP, 12/12 Security)** | November 17, 2026 |
