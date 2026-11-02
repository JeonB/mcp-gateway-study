# M0. 원시 JSON-RPC 관찰

- 날짜: 2026-11-02
- 환경: Python 3.15.2, `mcp` SDK 2.3.0 (`MCPServer`, 1.x의 `FastMCP`가 이름이 바뀜), upstream은 `json_response=True`
- 재현: `scripts/upstreams.sh start` 후 `scripts/probe.sh [url]`

## 0. 가장 큰 발견: MCP가 stateless가 되었다 (2026-07-28)

계획을 세울 때 가정한 2025-11-25 방식(initialize와 세션)은 이제 **legacy**다.
[2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)에서 게이트웨이와 관련된 변경은 다음과 같다.

| 변경 | 게이트웨이에 미치는 영향 |
|---|---|
| `initialize` 핸드셰이크와 `Mcp-Session-Id` 제거. 요청마다 `_meta`에 버전과 capabilities를 담음 | 세션 테이블과 sticky routing이 필요 없음. upstream 세션 풀도 필요 없음 |
| `server/discover` 추가 (MUST) | 게이트웨이(가상 서버)도 구현해야 함 |
| `Mcp-Method`, `Mcp-Name` 헤더 필수. 본문과 다르면 거부 | **본문을 파싱하지 않고 라우팅·권한 검사·rate limit을 할 수 있음** |
| list 결과에 `ttlMs`, `cacheScope` 필수 | 키마다 다른 도구 목록을 주면 `cacheScope: "private"`로 응답해야 함 |
| 모든 결과에 `resultType` 필수 | upstream 응답을 그대로 넘기거나, 직접 만들 때 반드시 포함 |
| `ping`, `logging/setLevel` 제거. `subscriptions/listen`이 GET 스트림을 대체 | M6의 `list_changed` 처리 방식이 바뀜 |
| `_meta`의 `traceparent`, `tracestate`, `baggage` 규약 | 게이트웨이가 트레이스를 이어 줄 수 있음 (M6) |
| SSE 재개(`Last-Event-ID`) 제거 | 스트림이 끊기면 클라이언트가 새 요청으로 재시도 |

## 1. 2026-07-28 요청 형식

```http
POST /mcp
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: add                       ← tools/call 같은 이름 있는 메서드만

{"jsonrpc":"2.0","id":3,"method":"tools/call",
 "params":{"name":"add","arguments":{"a":2,"b":3},
   "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
            "io.modelcontextprotocol/clientCapabilities":{},
            "io.modelcontextprotocol/clientInfo":{"name":"curl","version":"0"}}}}
```

응답:
```json
{"jsonrpc":"2.0","id":3,"result":{
  "content":[{"type":"text","text":"5.0"}],
  "structuredContent":{"result":5.0},
  "isError":false,
  "resultType":"complete",
  "_meta":{"io.modelcontextprotocol/serverInfo":{"name":"math","version":"0.1.0"}}}}
```

- `server/discover` → `supportedVersions`, `capabilities`, 그리고 `_meta.serverInfo`를 돌려준다.
- `tools/list` → `tools[]`와 함께 `ttlMs: 0`, `cacheScope: "private"`를 돌려준다.
- 반환 타입이 있는 도구는 `outputSchema`와 `structuredContent`가 자동으로 생긴다. `notes__list_notes`의 outputSchema는 `$defs`/`$ref`를 쓰므로, 게이트웨이가 스키마를 옮길 때 **스키마 단위로 통째로** 보관해야 한다.

## 2. 오류 케이스: 프로토콜 오류와 도구 오류의 경계

| 케이스 | HTTP | 응답 | 분류 |
|---|---|---|---|
| `Mcp-Name` ≠ 본문 `name` | 400 | error `-32020` HeaderMismatch | 프로토콜 |
| `Mcp-Method` 누락 | 400 | error `-32020` (누락도 mismatch로 처리) | 프로토콜 |
| 지원하지 않는 버전 | 400 | error `-32022`, `data.supported`/`requested` 포함 | 프로토콜 |
| 알 수 없는 메서드 | **404** | error `-32601` | 프로토콜 |
| 없는 도구 | 200 | result `isError: true`, "Unknown tool" | **도구 결과** (SDK 동작) |
| 인자 검증 실패 | 200 | result `isError: true`, pydantic 메시지 | 도구 결과 |

게이트웨이 설계에 주는 시사점:
- 오류 코드에 따라 **HTTP 상태도 달라진다** (400/404). 게이트웨이도 같은 매핑을 따라야 한다.
- upstream SDK는 "없는 도구"를 `isError` 결과로 돌려준다. 게이트웨이에서는 **권한이 없는 도구와 존재하지 않는 도구를 구분할 수 없게** 같은 응답을 주는 편이 안전하다 (도구 존재 여부를 노출하지 않기 위해). M5에서 결정한다.

## 3. 2025-11-25 (legacy) 비교

```text
POST initialize                       → 200, 응답 헤더 mcp-session-id: 2d67…
POST notifications/initialized (+sid) → 202
POST tools/call (+sid)                → 200, 결과 (resultType 없음)
POST tools/list (sid 없음)            → 400 "Missing session ID"
```

- legacy에서는 게이트웨이가 클라이언트 세션 ID와 upstream 세션 ID를 매핑하고, 세션마다 upstream으로 initialize를 따로 해야 한다. 원래 계획의 M1·M3에 있던 복잡도가 바로 이것이다.
- 같은 SDK 서버가 두 방식을 모두 받는다. 요청에 `_meta.protocolVersion`과 헤더가 있으면 modern, 없으면 legacy로 분기한다.

## 4. 설계 결정

1. **게이트웨이는 2026-07-28을 기본으로 구현한다.** 클라이언트를 상대하는 쪽과 upstream을 호출하는 쪽 모두 해당한다.
2. legacy(2025-11-25) 클라이언트 호환은 별도 마일스톤(M7)으로 미룬다. 아직 legacy만 지원하는 클라이언트가 있을 수 있다.
3. 라우팅과 권한 검사의 1차 판단은 `Mcp-Method`/`Mcp-Name` 헤더로 하고, 헤더와 본문이 일치하는지 반드시 검증한다. 헤더만 믿으면 헤더는 허용된 도구, 본문은 금지된 도구로 보내는 우회가 가능하다.

## 5. 아직 확인하지 않은 것
- [ ] SSE 응답 모드(`json_response=False`): 진행 알림이 있을 때 언제 `text/event-stream`으로 바뀌는지
- [ ] `subscriptions/listen` 동작
- [ ] MCP Inspector가 2026-07-28을 지원하는지 (이 환경에는 Node가 없어 미확인)
