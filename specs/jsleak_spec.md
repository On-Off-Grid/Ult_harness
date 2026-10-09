# Bug Bounty Harness Integration Specification: jsleak

## 1. System Overview
`jsleak` is a high-performance, concurrent, command-line tool written in Go, designed to analyze JavaScript source code or static assets to discover hidden API endpoints, routing links, and sensitive secrets (e.g., API keys, AWS credentials, auth tokens). 

It is highly optimized for pipelined command execution and matches code contents against custom regex schemas.

---

## 2. Architectural Analysis

### Tech Stack
- **Core Logic**: Go (Golang)
- **Regex Parsing**: Built-in Go `regexp` package with support for YAML-based external pattern databases (e.g., TruffleHog datasets, Mazen160 secrets database).
- **Network Stack**: Concurrency-driven HTTP requests with custom timeouts and status verification.

### File Structure & Components
- [`main.go`](file:///home/souhail/Desktop/Desktop/Ult_harness/jsleak/main.go): Single-entry file containing command-line parsing, concurrent worker pools, pattern matcher, link extraction logic, and HTTP status verification.
- **Input Channels**: Standard Input (`stdin`) stream accepting single URLs, absolute paths, or bulk URL list pipes.
- **Key Flags**:
  - `-l`: Extract links and URLs.
  - `-s`: Extract secrets.
  - `-t <file.yaml>`: Specify a custom YAML regex pattern definition.
  - `-e`: Enable URL auto-completion (relative to absolute mapping).
  - `-c <concurrency>`: Configure request concurrency limit.
  - `-k`: Test HTTP link status (liveness check).

### Data Flow
1. Target URLs are passed to `jsleak` via `stdin`.
2. It fetches the JavaScript content.
3. It concurrently matches regexes defined in the YAML file against the response body.
4. Relative links are identified and resolved to absolute URLs if `-e` is active.
5. If `-k` is active, it fires HEAD/GET requests to test status codes.
6. The output is structured and written to stdout for further command chaining.

---

## 3. Role in the Unified Harness
In the combined harness, `jsleak` functions as the **Static JS Analyzer & Secret Scanner**. 
- It is a fast, low-overhead utility designed to process large lists of Javascript URLs discovered during sub-domain spidering.
- It sits between the discovery phase (spiders/recon) and the active exploitation phase, uncovering new target parameters and credentials.

---

## 4. Optimal Bug Bounty Use Cases
- **Secret Extraction from Frontend Assets**: Scanning client-side JS bundles of single-page applications (React, Angular, Vue) to extract hardcoded developer keys, database credentials, or Firebase tokens.
- **Attack Surface Expansion**: Reading minified JS files to map out hidden administration panels, test endpoints, or parameter names that aren't linked anywhere on the main HTML document.
- **Dead Link & Subdomain Takeover Prep**: Extracting external links from JS files and verifying their HTTP status to check for subdomains pointing to orphaned cloud resources (S3, Heroku, etc.).

---

## 5. Harness Merging & Combination Strategy
To merge `jsleak` with the other components in the workspace:
1. **With `claude-bug-bounty` & `BugTraceAI`**: When the orchestrators spider a target, they identify JavaScript files (e.g., `*.js`). Instead of running Python-based parsers, they should invoke `jsleak` in a subprocess: `cat js_urls.txt | jsleak -l -s -t trufflehog-v3.yaml -e -k` to extract live endpoints and API keys, feeding them back to the scanner's database.
2. **With `mempalace`**: The output of `jsleak` (extracted endpoints, API endpoints, tokens) should be stored in a dedicated `mempalace` drawer under the target's wing. This ensures that even if the active session resets, the AI agent has semantic recall of discovered endpoints.
3. **With `Awesome-Redteam`**: The YAML regex patterns used by `jsleak` can be dynamically updated by pulling new matching regex blocks documented in the `Awesome-Redteam` cheatsheets.
