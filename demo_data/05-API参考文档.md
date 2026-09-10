# CloudFlow REST API 参考文档

> 文档版本：v2.4　|　适用套餐：专业版及以上　|　最后更新：2026-08-15
>
> API 基础地址：`https://api.cloudflow.io/v2`

## 1. 认证

所有 API 请求必须携带访问令牌（Access Token），通过 HTTP Header 传递：

```
Authorization: Bearer <ACCESS_TOKEN>
```

### 1.1 获取访问令牌

```
POST /v2/auth/token
Content-Type: application/json

{
  "client_id": "your_client_id",
  "client_secret": "your_client_secret"
}
```

**响应**：

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 7200
}
```

> **注意**：Access Token 有效期为 **2 小时**。过期后需重新获取，或使用 Refresh Token 刷新。

### 1.2 刷新令牌

```
POST /v2/auth/token/refresh
Content-Type: application/json

{ "refresh_token": "<REFRESH_TOKEN>" }
```

Refresh Token 有效期为 **7 天**。

---

## 2. 接口限流

| 套餐 | 限流阈值 |
|------|----------|
| 基础版 | 60 次 / 分钟 |
| 专业版 | 300 次 / 分钟 |
| 企业版 | 1000 次 / 分钟 |
| 旗舰版 | 不限流（公平使用） |

超出限流返回 HTTP `429 Too Many Requests`，响应头包含 `Retry-After` 字段指示重试等待秒数。

---

## 3. 同步任务接口

### 3.1 创建同步任务

```
POST /v2/sync-tasks
```

**请求体**：

```json
{
  "name": "order-db-to-snowflake",
  "source": {
    "connection_id": "conn_8a2f",
    "table": "orders",
    "mode": "INCREMENTAL",
    "incremental_column": "updated_at"
  },
  "destination": {
    "connection_id": "conn_3b91",
    "table": "orders_sync",
    "write_strategy": "UPSERT",
    "primary_key": ["order_id"]
  },
  "schedule": "0 */1 * * *",
  "parallelism": 8,
  "batch_size": 5000
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 任务名称，租户内唯一 |
| `source.mode` | enum | 是 | `FULL` / `INCREMENTAL` / `CDC` |
| `source.incremental_column` | string | 条件必填 | `INCREMENTAL` 模式必填 |
| `destination.write_strategy` | enum | 是 | `APPEND` / `UPSERT` / `OVERWRITE` |
| `destination.primary_key` | array | 条件必填 | `UPSERT` 策略必填 |
| `parallelism` | int | 否 | 并发度，默认 4，上限受套餐限制 |
| `batch_size` | int | 否 | 批量提交大小，默认 5000 |

**响应** `201 Created`：

```json
{
  "task_id": "task_7f3c91a2",
  "name": "order-db-to-snowflake",
  "status": "ENABLED",
  "created_at": "2026-08-15T10:23:41Z"
}
```

### 3.2 触发任务运行

```
POST /v2/sync-tasks/{task_id}/runs
```

**响应**：

```json
{
  "run_id": "run_5d8e21b7",
  "status": "RUNNING",
  "started_at": "2026-08-15T10:25:00Z"
}
```

### 3.3 查询运行实例

```
GET /v2/sync-tasks/{task_id}/runs/{run_id}
```

**响应**：

```json
{
  "run_id": "run_5d8e21b7",
  "status": "SUCCESS",
  "rows_synced": 1284503,
  "duration_seconds": 47,
  "started_at": "2026-08-15T10:25:00Z",
  "finished_at": "2026-08-15T10:25:47Z",
  "error_code": null
}
```

**status 取值**：`RUNNING` / `SUCCESS` / `FAILED` / `STALLED` / `CANCELLED`

### 3.4 列出所有同步任务

```
GET /v2/sync-tasks?page=1&page_size=20
```

支持查询参数 `status`、`name`（模糊匹配）、`page`、`page_size`（上限 100）。

### 3.5 删除同步任务

```
DELETE /v2/sync-tasks/{task_id}
```

删除任务不会删除目标端已同步的数据。

---

## 4. 连接管理接口

### 4.1 创建连接

```
POST /v2/connections
```

```json
{
  "name": "prod-order-db",
  "type": "mysql",
  "host": "10.0.1.20",
  "port": 3306,
  "database": "order_db",
  "username": "cloudflow_ro",
  "password": "******"
}
```

> **安全说明**：密码仅在创建/更新时传输，服务端使用 AES-256 加密存储，任何接口均不返回密码明文。

### 4.2 测试连接

```
POST /v2/connections/{connection_id}/test
```

**响应**：

```json
{
  "success": true,
  "latency_ms": 42,
  "message": "连接成功"
}
```

---

## 5. 错误响应格式

所有错误返回统一结构：

```json
{
  "error": {
    "code": "CONN_TIMEOUT",
    "message": "connect timed out after 30000ms",
    "request_id": "req_9a1b2c3d"
  }
}
```

**HTTP 状态码约定**：

| 状态码 | 含义 |
|--------|------|
| `400` | 请求参数错误 |
| `401` | 未认证或 Token 已过期 |
| `403` | 无权限（如套餐不支持该功能） |
| `404` | 资源不存在 |
| `429` | 触发限流 |
| `500` | 服务端错误 |

> **反馈工单时请附上 `request_id`**，可大幅加快定位速度。
