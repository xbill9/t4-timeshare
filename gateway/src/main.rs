//! t4-gateway: one vLLM, several tenants.
//!
//! Per request: key -> tenant (401 if unknown), model checked against the tenant's own adapter
//! (403 for anyone else's), then the tenant's priority and cache salt are written into the body,
//! the request waits for one of the tenant's in-flight slots, and is forwarded to vLLM.
//! When the response ends (or the client goes away) one JSON line goes to the ledger with the
//! token counts vLLM reported in its `usage` field.
//!
//! usage: t4-gateway <tenants.toml> <ledger.jsonl>

use axum::{
    Router,
    body::Body,
    extract::State,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::post,
};
use futures_util::StreamExt;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    fs::{File, OpenOptions},
    io::Write,
    sync::{Arc, Mutex},
    time::{Instant, SystemTime, UNIX_EPOCH},
};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

#[derive(Deserialize)]
struct Config {
    listen: String,
    upstream: String,
    base_model: String,
    tenant: Vec<TenantCfg>,
}

#[derive(Deserialize)]
struct TenantCfg {
    name: String,
    key: String,
    adapter: Option<String>,
    max_inflight: usize,
    /// vLLM priority: lower runs first.
    priority: i64,
}

struct Tenant {
    cfg: TenantCfg,
    slots: Arc<Semaphore>,
}

struct App {
    upstream: String,
    base_model: String,
    by_key: HashMap<String, Arc<Tenant>>,
    adapters: Vec<String>,
    ledger: Mutex<File>,
    http: reqwest::Client,
}

fn now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64()
}

impl App {
    fn record(&self, row: Value) {
        let mut f = self.ledger.lock().unwrap();
        let _ = writeln!(f, "{row}");
    }

    fn refuse(&self, tenant: Option<&str>, status: StatusCode, why: &str) -> Response {
        self.record(json!({"ts": now(), "tenant": tenant, "status": status.as_u16(), "refused": why}));
        (status, axum::Json(json!({"error": why}))).into_response()
    }
}

/// Ledger row for one forwarded request. Written on drop, so a request whose client disconnects
/// mid-stream is still recorded, and the tenant's slot is released at the same moment.
struct Meter {
    app: Arc<App>,
    tenant: String,
    model: String,
    queue_ms: f64,
    started: Instant,
    status: u16,
    usage: Option<Value>,
    buf: Vec<u8>,
    _slot: OwnedSemaphorePermit,
}

impl Meter {
    /// Scan streamed SSE bytes for the chunk that carries `usage`.
    fn feed(&mut self, bytes: &[u8]) {
        self.buf.extend_from_slice(bytes);
        while let Some(i) = self.buf.iter().position(|&b| b == b'\n') {
            let line: Vec<u8> = self.buf.drain(..=i).collect();
            if let Some(data) = line.strip_prefix(b"data: {".as_slice()) {
                let mut j = b"{".to_vec();
                j.extend_from_slice(data);
                if let Ok(v) = serde_json::from_slice::<Value>(&j) {
                    if v.get("usage").is_some_and(|u| !u.is_null()) {
                        self.usage = Some(v["usage"].clone());
                    }
                }
            }
        }
    }
}

impl Drop for Meter {
    fn drop(&mut self) {
        let u = self.usage.as_ref();
        self.app.record(json!({
            "ts": now(),
            "tenant": self.tenant,
            "model": self.model,
            "status": self.status,
            "prompt_tokens": u.and_then(|u| u["prompt_tokens"].as_u64()),
            "completion_tokens": u.and_then(|u| u["completion_tokens"].as_u64()),
            "queue_ms": self.queue_ms,
            "total_ms": self.started.elapsed().as_secs_f64() * 1e3,
        }));
    }
}

async fn chat(State(app): State<Arc<App>>, headers: HeaderMap, body: bytes::Bytes) -> Response {
    let key = headers
        .get("authorization")
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.strip_prefix("Bearer "));
    let Some(tenant) = key.and_then(|k| app.by_key.get(k)).cloned() else {
        return app.refuse(None, StatusCode::UNAUTHORIZED, "missing or unknown key");
    };
    let name = tenant.cfg.name.as_str();
    let Ok(mut req) = serde_json::from_slice::<Value>(&body) else {
        return app.refuse(Some(name), StatusCode::BAD_REQUEST, "body is not JSON");
    };

    // Model: the tenant's adapter by default; the base model or the tenant's own adapter on request.
    let own = tenant.cfg.adapter.clone().unwrap_or_else(|| app.base_model.clone());
    let model = match req.get("model").and_then(|m| m.as_str()) {
        None => own,
        Some(m) if m == own || m == app.base_model => m.to_string(),
        Some(m) if app.adapters.iter().any(|a| a == m) => {
            return app.refuse(Some(name), StatusCode::FORBIDDEN, "adapter belongs to another tenant");
        }
        Some(_) => return app.refuse(Some(name), StatusCode::NOT_FOUND, "unknown model"),
    };
    let stream = req.get("stream").and_then(|s| s.as_bool()).unwrap_or(false);
    req["model"] = json!(model);
    req["priority"] = json!(tenant.cfg.priority);
    req["cache_salt"] = json!(format!("tenant:{name}"));
    if stream {
        req["stream_options"] = json!({"include_usage": true});
    }

    let started = Instant::now();
    let slot = tenant.slots.clone().acquire_owned().await.unwrap();
    let queue_ms = started.elapsed().as_secs_f64() * 1e3;
    let mut meter = Meter {
        app: app.clone(),
        tenant: name.to_string(),
        model,
        queue_ms,
        started,
        status: 502,
        usage: None,
        buf: Vec::new(),
        _slot: slot,
    };

    let upstream = match app
        .http
        .post(format!("{}/v1/chat/completions", app.upstream))
        .json(&req)
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => return (StatusCode::BAD_GATEWAY, e.to_string()).into_response(),
    };
    meter.status = upstream.status().as_u16();
    let status = upstream.status();
    let ctype = upstream.headers().get("content-type").cloned();

    let mut resp = if stream {
        let body = upstream.bytes_stream().map(move |chunk| {
            if let Ok(b) = &chunk {
                meter.feed(b);
            }
            chunk
        });
        Response::new(Body::from_stream(body))
    } else {
        let bytes = upstream.bytes().await.unwrap_or_default();
        if let Ok(v) = serde_json::from_slice::<Value>(&bytes) {
            meter.usage = v.get("usage").cloned();
        }
        drop(meter);
        Response::new(Body::from(bytes))
    };
    *resp.status_mut() = status;
    if let Some(c) = ctype {
        resp.headers_mut().insert("content-type", c);
    }
    resp
}

#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    let [_, cfg_path, ledger_path] = args.as_slice() else {
        eprintln!("usage: t4-gateway <tenants.toml> <ledger.jsonl>");
        std::process::exit(2);
    };
    let cfg: Config = toml::from_str(&std::fs::read_to_string(cfg_path).unwrap()).unwrap();
    let adapters = cfg.tenant.iter().filter_map(|t| t.adapter.clone()).collect();
    let by_key = cfg
        .tenant
        .into_iter()
        .map(|t| {
            let slots = Arc::new(Semaphore::new(t.max_inflight));
            (t.key.clone(), Arc::new(Tenant { cfg: t, slots }))
        })
        .collect::<HashMap<_, _>>();
    for t in by_key.values() {
        let c = &t.cfg;
        println!("tenant {:<8} adapter {:<6} max_inflight {} priority {}",
                 c.name, c.adapter.as_deref().unwrap_or("-"), c.max_inflight, c.priority);
    }
    let app = Arc::new(App {
        upstream: cfg.upstream,
        base_model: cfg.base_model,
        by_key,
        adapters,
        ledger: Mutex::new(OpenOptions::new().create(true).append(true).open(ledger_path).unwrap()),
        http: reqwest::Client::new(),
    });
    let router = Router::new().route("/v1/chat/completions", post(chat)).with_state(app);
    let listener = tokio::net::TcpListener::bind(&cfg.listen).await.unwrap();
    println!("listening on {}", cfg.listen);
    axum::serve(listener, router).await.unwrap();
}
