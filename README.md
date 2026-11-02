# mcp-gateway-study

**도구(tool) 단위**로 MCP 서버와 REST 엔드포인트를 관리하는 MCP 게이트웨이를 직접 만들어 보는 학습 프로젝트입니다.

- 기준 스펙: [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28) (stateless, `Mcp-Method`/`Mcp-Name` 헤더)
- 참고 구현: IBM ContextForge, LiteLLM, agentgateway, Kong AI MCP Proxy, Azure APIM, AWS AgentCore Gateway
- 전체 계획과 진행 상황: [PLAN.md](PLAN.md)

## 목표 구조

```text
MCP Client ──► Gateway ──► MCP 서버 A ┐
               │  카탈로그     MCP 서버 B ├ 여러 출처의 도구를 골라
               │  가상 서버    REST API   ┘ 하나의 가상 MCP 서버로 노출
               └─ 키별 도구 권한
```

## 진행 상황

| 마일스톤 | 내용 | 상태 |
|---|---|---|
| M0 | upstream 준비, 원시 JSON-RPC 관찰 ([노트](notes/m0-raw-jsonrpc.md)) | ✅ |
| M1 | 서버 단위 패스스루 프록시 | ⬜ |
| M2 | 도구 카탈로그 | ⬜ |
| M3 | 가상 서버 | ⬜ |
| M4 | REST → 도구 | ⬜ |
| M5 | 인증과 도구 단위 권한 | ⬜ |
| M6 | 관측과 운영 | ⬜ |

## 실행

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

scripts/upstreams.sh start      # math :9001/mcp · notes :9002/mcp · rest :9003
scripts/probe.sh                # 원시 JSON-RPC 요청과 응답 출력
.venv/bin/pytest -q
scripts/upstreams.sh stop
```

## 디렉터리

```text
upstreams/   테스트용 upstream 서버 (MCP 2개, REST 1개)
scripts/     서버 실행, 프로토콜 관찰 스크립트
notes/       마일스톤별 학습 노트
gateway/     게이트웨이 구현 (M1~)
tests/
```
