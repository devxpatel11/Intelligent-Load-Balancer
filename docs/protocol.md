# Frozen TCP protocol (contract version 1)

This contract is shared by the client, proxy, and backend. Changes require a dedicated contract PR approved by both members before dependent implementation changes.

## Framing and connection lifecycle

- Each TCP connection carries exactly one request and one response.
- Each message is one UTF-8 JSON object followed by byte `0x0A` (`\n`).
- Readers wait for the newline because TCP is a byte stream; one socket read is not one message.
- The maximum complete frame is 65,536 bytes including the newline.
- Reject an over-limit frame, invalid UTF-8, invalid JSON, a non-object JSON value, or EOF before a newline.
- Close the connection after the response or bounded error handling.

## Work message

Request:

```json
{"id":"r0001","op":"work","work_units":1,"payload":"hello"}
```

Successful response:

```json
{"id":"r0001","ok":true,"backend_id":"s1","echo":"hello"}
```

Validation is strict:

| Field | Rule |
| --- | --- |
| `id` | Required nonempty string, at most 64 characters |
| `op` | Required string equal to `work` |
| `work_units` | Required integer from 1 through 10; booleans are rejected |
| `payload` | Required string, at most 1,024 bytes after UTF-8 encoding |

Clients cannot provide an arbitrary server delay. The backend derives service time from its configured base service time and `work_units`.

A successful response must preserve the request `id`, name the configured selected backend in `backend_id`, set `ok` to `true`, and echo the request payload in `echo`.

## Health message

Request:

```json
{"id":"probe-s1","op":"health"}
```

Response:

```json
{"id":"probe-s1","ok":true,"backend_id":"s1","status":"healthy"}
```

Health requests require only a valid `id` and `op`. They bypass backend work-capacity slots, remain responsive while work slots are occupied, and never enter work or assignment metrics.

## Error message

```json
{"id":"r0001","ok":false,"backend_id":null,"error":{"code":"NO_HEALTHY_BACKEND","message":"no backend is currently eligible"}}
```

- `id` is the validated request ID, or `null` when no valid ID is available.
- `backend_id` is the selected backend when the failure is attributable to one; otherwise it is `null`.
- `error.code` is stable and machine-readable; `error.message` is a nonempty human-readable string.

Stable error codes:

- `INVALID_REQUEST`
- `FRAME_TOO_LARGE`
- `CLIENT_READ_TIMEOUT`
- `OVERLOADED`
- `NO_HEALTHY_BACKEND`
- `BACKEND_UNAVAILABLE`
- `BACKEND_TIMEOUT`
- `BACKEND_PROTOCOL_ERROR`

## Deadlines and retry policy

| Operation | Deadline |
| --- | --- |
| Read complete client frame | 2.0 seconds |
| Connect to backend | At most 0.5 seconds |
| Whole backend transaction | 3.0 seconds |
| Workload client's complete attempt | 4.0 seconds |

There is no automatic replay. Once assigned, a request may return a bounded backend error; retrying could duplicate non-idempotent work.
