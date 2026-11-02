# MCP Gateway 학습 계획

> 목표: **도구(tool) 단위**로 MCP 서버와 REST 엔드포인트를 관리하는 MCP 게이트웨이를 직접 만들며 구조를 이해한다.
> 상태 표기: `[ ]` 미착수 · `[~]` 진행 중 · `[x]` 완료
>
> **기준 스펙: MCP 2026-07-28 (stateless).** initialize와 세션이 없고, 요청마다 `_meta`에 버전을 담으며, `Mcp-Method`/`Mcp-Name` 헤더가 필수다. 2025-11-25(legacy) 호환은 M7에서 다룬다. 자세한 내용은 [notes/m0-raw-jsonrpc.md](notes/m0-raw-jsonrpc.md) 참고.

---

## 1. 핵심 개념 (조사로 확인한 내용)

상용·오픈소스 게이트웨이는 공통적으로 이렇게 나뉜다.

| 층위 | 단위 | 하는 일 |
|---|---|---|
| 등록 | 서버 / API / Target | upstream MCP 서버나 REST API를 게이트웨이에 연결 |
| 카탈로그 | **도구** | upstream의 `tools/list`를 수집하거나 REST operation을 도구로 변환하고, 이름 충돌을 처리함 |
| 노출 | **도구 묶음 (가상 서버)** | 고른 도구만 모아 별도 MCP 엔드포인트로 노출 |
| 권한 | **도구** | 키·팀별로 허용할 도구를 정함. 목록 조회와 호출 시점에 모두 검사 |

| 참고 제품 | 배울 점 |
|---|---|
| Azure APIM | REST operation을 골라 도구로 노출 (엔드포인트 = 도구) |
| Kong AI MCP Proxy | route별 도구 정의, 도구별 ACL(조회·호출 양쪽 검사), 여러 route를 listener 하나로 합침 |
| IBM ContextForge | Gateway → Tool 카탈로그 → Virtual Server(`associated_tools`) 구조 |
| LiteLLM | 서버 수준 `allowed_tools`/`disallowed_tools`와 키·팀 수준 `mcp_tool_permissions`의 분리 |
| agentgateway | target prefix 네이밍, CEL 기반 도구 권한, fan-out 후 결과 병합 |
| AWS AgentCore Gateway | target 합치기, 시맨틱 도구 검색, outbound credential 주입 |

---

## 2. 학습 경로

| 단계 | 할 일 | 볼 자료 |
|---|---|---|
| **A. 프로토콜** | 2026-07-28 스펙의 changelog, Streamable HTTP transport, tools를 읽고 원시 JSON-RPC를 직접 주고받아 본다 | modelcontextprotocol.io/specification/2026-07-28 |
| **B. 참조 구현 읽기** | ContextForge의 데이터 모델과 서비스 계층을 읽고, 도구 동기화와 가상 서버 구성 흐름을 따라간다 | `IBM/mcp-context-forge` 저장소 (`mcpgateway/services/` 아래 gateway/tool/server 서비스. 경로는 최신 저장소에서 확인) |
| **C. 직접 구현** | 아래 마일스톤 M0~M6 | 이 문서 |
| **D. 비교** | 각 마일스톤을 마치면 같은 기능을 다른 제품이 어떻게 풀었는지 비교해 §7에 기록 | LiteLLM `mcp_control` 문서, agentgateway tool-access 문서, Kong·APIM 문서 |

원칙: **구현 → 참조 코드와 비교 → 차이 기록** 순서로 진행한다. 참조 코드를 먼저 베끼지 않는다.

---

## 3. 기술 스택

| 항목 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.12+ | ContextForge와 LiteLLM이 Python이라 비교하기 쉬움 |
| 웹 | FastAPI + uvicorn | SSE와 스트리밍 응답 지원 |
| HTTP 클라이언트 | httpx (async) | upstream MCP 서버와 REST 호출 |
| 저장소 | SQLite + SQLModel | 학습용으로 충분함 |
| 테스트용 upstream | 공식 `mcp` Python SDK 2.x (`MCPServer`. 1.x의 FastMCP) | upstream 서버를 빠르게 만들기 위함 |
| 검증 도구 | curl(`scripts/probe.sh`), pytest, SDK 클라이언트. MCP Inspector는 Node가 필요해 선택 사항 | |

**학습 포인트**: 게이트웨이가 클라이언트를 상대하는 쪽(JSON-RPC 처리, 헤더 검증, 라우팅)은 SDK 없이 **직접 구현**한다. 이 부분이 게이트웨이의 본질이기 때문이다. upstream 호출도 stateless라 httpx로 직접 구현할 수 있다. stdio upstream은 SDK 클라이언트를 쓴다.

---

## 4. 목표 아키텍처

```mermaid
flowchart LR
  C[MCP Client] -->|POST /servers/{vs_id}/mcp<br/>Authorization: Bearer key<br/>Mcp-Method · Mcp-Name| GW

  subgraph GW[Gateway]
    direction TB
    T[Transport<br/>JSON-RPC · 헤더/본문 검증] --> AZ[AuthZ<br/>key → 허용 도구]
    AZ --> R[Router<br/>도구 이름 → 실행기]
    R --> MX[MCP 실행기]
    R --> HX[HTTP 실행기]
    CAT[(Catalog DB<br/>upstream · tool · vserver · key)]
  end

  MX -->|tools/call 원래 이름| U1[Upstream MCP 서버 A]
  MX --> U2[Upstream MCP 서버 B]
  HX -->|REST 요청| API[REST API]
```

### 요청 흐름
- **공통**: `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` 헤더가 `_meta`와 본문에 일치하는지 검증한다. 다르면 `-32020`과 400.
- **`server/discover`**: 가상 서버의 이름, 지원 버전, capabilities(`tools`)를 응답한다.
- **`tools/list`**: 가상 서버에 속한 도구 중 키에 허용된 것만 고르고, 카탈로그에 저장된 스키마로 응답한다. upstream은 호출하지 않는다. 키마다 결과가 다르므로 `cacheScope: "private"`로 응답한다.
- **`tools/call`**: 노출 이름으로 도구를 찾고 → **권한을 다시 검사**하고 → 도구 종류에 따라 실행한다.
  - MCP 도구: upstream에 원래 이름으로 `tools/call`을 보낸다. `Mcp-Name` 헤더도 원래 이름으로 바꾸고, `traceparent`는 그대로 전달한다.
  - HTTP 도구: arguments를 path, query, body에 매핑해 REST를 호출하고, 결과를 `content`로 감싼다.

---

## 5. 데이터 모델 (초안)

```text
Upstream        id, name(prefix로 사용), kind[mcp_http|mcp_stdio|rest], url|command,
                auth(json), enabled, last_synced_at
Tool            id, upstream_id, original_name, exposed_name(unique),
                description, input_schema(json), kind[mcp|http],
                http_spec(json: method, path_template, param 매핑) | null, enabled
VirtualServer   id, name, description
VirtualServerTool  virtual_server_id, tool_id
ApiKey          id, key_hash, name, created_at
KeyToolGrant    key_id, virtual_server_id, tool_id | null(null이면 서버 전체), effect[allow|deny]
CallLog         id, ts, key_id, virtual_server_id, tool_id, latency_ms, is_error, error
```

설계 결정 (나중에 바꿀 수 있음):
- `exposed_name = f"{upstream.name}__{original_name}"`. 스펙의 도구 이름 허용 문자(`A-Z a-z 0-9 _ - .`, 최대 128자)를 지킨다.
- 서버 수준 허용·거부 목록(Tool.enabled)과 키 수준 권한(KeyToolGrant)을 분리한다. LiteLLM과 같은 방식이다.
- **deny가 allow보다 우선**하며, 조회와 호출 모두에서 같은 함수로 판정한다. LiteLLM 버그 #48166에서 얻은 교훈이다.

---

## 6. 마일스톤

각 마일스톤은 **완료 조건**을 만족해야 끝난다.

### M0. 준비 · upstream 만들기 `[x]`
- [x] 프로젝트 골격 생성 (§8 디렉터리 구조)
- [x] SDK `MCPServer`로 테스트용 upstream 2개 만들기
  - `math`: `add`, `multiply` 도구 (Streamable HTTP, :9001)
  - `notes`: `create_note`, `list_notes` 도구 (Streamable HTTP, :9002)
- [x] 간단한 REST API 1개 만들기 (FastAPI, :9003, `GET /weather/{city}`, `GET/POST /todos`)
- [x] curl로 2026-07-28 방식(`server/discover`, `tools/list`, `tools/call`)과 오류 케이스, legacy 세션 흐름을 **직접** 보내고 [notes/m0-raw-jsonrpc.md](notes/m0-raw-jsonrpc.md)에 기록

**완료 조건**: stateless 요청 형식(`_meta`, `Mcp-Method`/`Mcp-Name`)과 legacy 세션 방식의 차이, 프로토콜 오류와 도구 오류(`isError`)의 경계를 설명할 수 있다. ✅

### M1. 서버 단위 패스스루 프록시 `[ ]`
- [ ] `POST /proxy/{upstream}/mcp` → upstream으로 요청 본문과 MCP 헤더를 그대로 전달
- [ ] **본문을 파싱하지 않고** `Mcp-Method`/`Mcp-Name` 헤더만으로 접근 로그 남기기 (2026-07-28 헤더의 존재 이유를 체감하기)
- [ ] SSE 응답 스트리밍 중계 (`json_response=False`인 upstream으로 테스트)

**완료 조건**: SDK 클라이언트(또는 `probe.sh`)로 게이트웨이를 거쳐 `math` 도구를 호출할 수 있고, 로그에 메서드와 도구 이름이 남는다.
**배울 점**: 이 단계는 APISIX `mcp-bridge` 수준이다. 도구 개념이 없어 권한·조합·이름 변경을 할 수 없다는 한계를 직접 느낀다. stateless 덕분에 legacy와 달리 세션 매핑이 필요 없다는 점도 확인한다.

### M2. 도구 카탈로그 `[ ]`
- [ ] Upstream 등록 API (`POST /admin/upstreams`)
- [ ] 동기화: `POST /admin/upstreams/{id}/sync` → upstream에 `server/discover`(버전 확인), `tools/list` 요청(페이지네이션 `cursor` 처리) → Tool 테이블에 upsert. 응답의 `ttlMs`를 다음 동기화 시점 힌트로 저장
- [ ] 노출 이름 생성 및 충돌 검사
- [ ] upstream에서 사라진 도구 처리 방침 정하기 (삭제할지, disable할지)

**완료 조건**: `GET /admin/tools`에 두 upstream의 도구 4개가 `math__add` 형태로 나온다.

### M3. 가상 서버 (핵심) `[ ]`
- [ ] VirtualServer CRUD와 도구 연결 API
- [ ] `POST /servers/{vs_id}/mcp`에 MCP 서버 측 구현
  - 헤더·`_meta`·본문 검증 (`-32020` HeaderMismatch, `-32022` UnsupportedProtocolVersion)
  - `server/discover`: 지원 버전과 capabilities(`tools`)
  - `tools/list`: 카탈로그에서 응답 (`resultType`, `ttlMs`, `cacheScope` 포함, 결정적 순서)
  - `tools/call`: 노출 이름 → Tool → upstream 원래 이름으로 변환해 호출 (본문 `name`과 `Mcp-Name` 헤더 모두 변경)
  - 알 수 없는 메서드는 `-32601`과 HTTP 404
- [ ] upstream HTTP 클라이언트 재사용 (httpx `AsyncClient` 커넥션 풀. 세션 풀은 필요 없음)
- [ ] 오류 구분: 프로토콜 오류(JSON-RPC error, HTTP 4xx)와 도구 실행 오류(`isError: true`, HTTP 200)

**완료 조건**: `math__add`와 `notes__create_note`만 담은 가상 서버에 SDK 클라이언트로 연결하면 두 도구만 보이고, 둘 다 호출된다.

### M4. REST 엔드포인트 → 도구 `[ ]`
- [ ] 수동 등록: method, path template, inputSchema, 파라미터 매핑(path/query/body)으로 HTTP 도구 생성
- [ ] OpenAPI 가져오기: spec에서 operation을 **골라** 도구로 생성. `operationId`를 도구 이름으로, parameters와 requestBody를 inputSchema로 변환
- [ ] HTTP 실행기: 응답을 `content: [{type: "text", ...}]`로 감싸고, JSON 응답이면 `structuredContent`도 채움. 4xx/5xx는 `isError: true`

**완료 조건**: 가상 서버 하나에 MCP 도구와 REST 도구가 섞여 있고, 둘 다 호출된다. (APIM의 "operation 선택" 기능과 같은 결과)

### M5. 인증과 도구 단위 권한 `[ ]`
- [ ] API 키 발급(해시로 저장), `Authorization: Bearer` 검증
- [ ] KeyToolGrant 기반 `is_allowed(key, vs, tool)` 단일 함수
- [ ] `tools/list` 필터링과 `tools/call` 재검사에 **같은 함수** 사용
- [ ] `Mcp-Name` 헤더로 빠르게 거부하되, 본문 `name`과 일치하는지 반드시 검증 (헤더 우회 방지)
- [ ] 권한 없는 도구와 없는 도구를 같은 응답으로 처리할지 결정 (도구 존재 여부 노출 방지)
- [ ] 테스트: 목록에 없는 도구를 이름으로 직접 호출하면 거부되는지 (LiteLLM #48166 시나리오)

**완료 조건**: 키 A와 키 B가 같은 가상 서버에서 서로 다른 도구 목록을 보고, 숨겨진 도구는 직접 호출해도 실패한다.

### M6. 관측과 운영 `[ ]`
- [ ] 도구 호출마다 CallLog 기록 (지연 시간, 오류)
- [ ] 도구별·키별 rate limit (메모리 기반 token bucket)
- [ ] upstream 헬스체크(`server/discover`)와 `subscriptions/listen`(`toolsListChanged`) 구독으로 재동기화
- [ ] `_meta`의 `traceparent`를 upstream으로 전달하고 게이트웨이 구간 span 기록

**완료 조건**: `GET /admin/stats`로 도구별 호출 수, 오류율, p95 지연 시간을 볼 수 있다.

### M7. 선택 과제 `[ ]`
- [ ] legacy(2025-11-25) 클라이언트 호환: `initialize`와 `Mcp-Session-Id`를 받아 내부에서 stateless로 변환 (버전 번역 게이트웨이)
- [ ] stdio upstream 지원 (SDK 클라이언트)
- [ ] outbound 인증: upstream마다 API 키나 OAuth 토큰 주입 (AgentCore credential provider 참고)
- [ ] 시맨틱 도구 검색 메타 도구 `search_tools` (AgentCore 참고)
- [ ] CEL 같은 정책 표현식 (agentgateway 참고)
- [ ] MCP 클라이언트 측 OAuth (스펙의 Authorization 절)

---

## 7. 비교 노트 (마일스톤마다 작성)

| 마일스톤 | 내 구현 | ContextForge | LiteLLM | agentgateway | 배운 점 |
|---|---|---|---|---|---|
| M2 이름 충돌 | `upstream__tool` | | `server-tool` | `target_tool` | |
| M3 가상 서버 | | `associated_tools` | | | |
| M5 권한 | | | `mcp_tool_permissions` | CEL `mcp.tool.name` | |

---

## 8. 디렉터리 구조 (초안)

```text
mcp-gateway-study/
├── PLAN.md                 # 이 문서
├── README.md
├── pyproject.toml
├── notes/                  # 마일스톤별 학습 기록
├── scripts/
│   ├── upstreams.sh        # upstream 서버 시작·중지
│   └── probe.sh            # 원시 JSON-RPC 관찰
├── upstreams/              # M0 테스트용 서버
│   ├── math_server.py
│   ├── notes_server.py
│   └── rest_api.py
├── gateway/
│   ├── main.py             # FastAPI 앱
│   ├── transport.py        # JSON-RPC 파싱, 세션, SSE
│   ├── mcp_handler.py      # initialize / tools/list / tools/call
│   ├── catalog/            # models.py, sync.py, openapi_import.py
│   ├── executors/          # mcp_executor.py, http_executor.py
│   ├── authz.py
│   └── admin_api.py
└── tests/
```

---

## 9. 참고 자료
- MCP 스펙 2026-07-28: https://modelcontextprotocol.io/specification/2026-07-28 · changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- 2026-07-28 RC 발표 (게이트웨이 관점 변경점): https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/
- IBM ContextForge: https://ibm.github.io/mcp-context-forge/latest/ · https://github.com/IBM/mcp-context-forge
- LiteLLM MCP: https://docs.litellm.ai/docs/mcp · https://docs.litellm.ai/docs/mcp_control · https://github.com/BerriAI/litellm/issues/48166
- agentgateway: https://agentgateway.dev/docs/standalone/latest/documentation/mcp/ · https://agentgateway.dev/docs/kubernetes/latest/documentation/mcp/tool-access/
- Kong AI MCP Proxy: https://developer.konghq.com/plugins/ai-mcp-proxy · https://developer.konghq.com/mcp/map-api-to-mcp-tools/
- Azure APIM: https://learn.microsoft.com/en-us/azure/api-management/export-rest-mcp-server
- AWS AgentCore Gateway: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-core-concepts.html

---

## 10. 진행 로그
| 날짜 | 마일스톤 | 내용 |
|---|---|---|
| 2026-11-02 | - | 계획 수립 |
| 2026-11-02 | M0 | upstream 3개, probe 스크립트 작성. MCP 2026-07-28 stateless 전환을 발견해 계획을 수정함 (기준 스펙 변경, 세션 관련 작업 제거, legacy 호환은 M7로 이동) |
