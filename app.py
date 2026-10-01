#!/usr/bin/env python3
"""Dummy production-like live log generator. Standard library only.

Logs come out as: <line_no> <LEVEL> <text>
Several API calls are "in flight" at the same time, so their lines (request,
downstream calls, response) interleave with background/system logs and
occasional crashes, just like a real production stream.
"""
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone

MIN_DELAY = float(os.getenv("LOG_INTERVAL_MIN", "0.1"))
MAX_DELAY = float(os.getenv("LOG_INTERVAL_MAX", "1.0"))
CRASH_PROB = float(os.getenv("CRASH_PROBABILITY", "0.004"))  # per tick
BURST_PROB = float(os.getenv("BURST_PROBABILITY", "0.02"))  # traffic spike per tick
WITH_TS = os.getenv("LOG_TIMESTAMP", "0") == "1"

R = random
SERVICES = ["api-gateway", "auth-service", "user-service", "order-service", "payment-service",
            "inventory-service", "shipping-service", "search-service", "recommendation-service",
            "notification-service", "report-service", "scheduler"]


# ---------------------------------------------------------------- generators
def hexid(n=8):
    return "".join(R.choices("0123456789abcdef", k=n))


def ip():
    return f"{R.choice([10, 10, 10, 172, 192])}.{R.randint(0, 255)}.{R.randint(0, 255)}.{R.randint(1, 254)}"


def pubip():
    return f"{R.choice([3, 13, 34, 52, 54, 103, 122, 157, 182, 203])}.{R.randint(0, 255)}.{R.randint(0, 255)}.{R.randint(1, 254)}"


def ms(lo=3, hi=400):
    return R.randint(lo, hi)


def uid():
    return R.randint(1000, 99999)


def email():
    return f"{R.choice(['amit', 'priya', 'rahul', 'neha', 'john', 'sara', 'ravi', 'anita', 'mike', 'kavya'])}{R.randint(1, 9999)}@{R.choice(['gmail.com', 'yahoo.com', 'outlook.com', 'example.com', 'corp.in'])}"


def sku():
    return f"SKU-{R.randint(1000, 9999)}"


def order():
    return f"ORD-{R.randint(100000, 999999)}"


def txn():
    return f"txn_{hexid(14)}"


def money():
    return f"{R.randint(5, 9000)}.{R.randint(0, 99):02d}"


def cur():
    return R.choice(["INR", "INR", "INR", "USD", "EUR", "GBP"])


def pod(s=None):
    return f"{s or R.choice(SERVICES)}-{hexid(9)}-{hexid(5)}"


def svc():
    return R.choice(SERVICES)


def table():
    return R.choice(["orders", "users", "payments", "products", "carts", "sessions", "shipments", "inventory", "audit_log", "coupons"])


def topic():
    return R.choice(["order.created", "order.updated", "payment.completed", "user.registered", "inventory.changed", "email.send", "shipment.dispatched"])


def job():
    return R.choice(["cleanup-sessions", "sync-inventory", "daily-report", "expire-carts", "reindex-search", "rotate-logs", "send-digest", "refresh-fx-rates", "purge-tmp"])


def ua():
    return R.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5) Safari/605.1",
        "Mozilla/5.0 (Linux; Android 14) Chrome/125.0 Mobile",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) Firefox/127.0",
        "okhttp/4.12.0", "python-requests/2.32.3", "axios/1.7.2", "PostmanRuntime/7.39.0",
        "curl/8.5.0", "Go-http-client/2.0", "kube-probe/1.29", "Googlebot/2.1",
    ])


def region():
    return R.choice(["ap-south-1", "us-east-1", "eu-west-1", "ap-southeast-1"])


# --------------------------------------------------------------- API call flow
ENDPOINTS = [  # (method, path factory, owning service, weight)
    ("GET", lambda: f"/api/v1/products?page={R.randint(1, 40)}&limit={R.choice([10, 20, 50])}", "search-service", 10),
    ("GET", lambda: f"/api/v1/products/{sku()}", "inventory-service", 9),
    ("GET", lambda: f"/api/v1/search?q={R.choice(['phone', 'laptop', 'shoes', 'watch', 'bag', 'tv', 'book'])}", "search-service", 8),
    ("GET", lambda: f"/api/v2/recommendations?user_id={uid()}", "recommendation-service", 5),
    ("GET", lambda: f"/api/v1/users/{uid()}", "user-service", 7),
    ("POST", lambda: "/api/v1/users", "user-service", 2),
    ("PUT", lambda: f"/api/v1/users/{uid()}", "user-service", 2),
    ("DELETE", lambda: f"/api/v1/users/{uid()}", "user-service", 1),
    ("POST", lambda: "/api/v1/auth/login", "auth-service", 7),
    ("POST", lambda: "/api/v1/auth/register", "auth-service", 2),
    ("POST", lambda: "/api/v1/auth/refresh", "auth-service", 5),
    ("POST", lambda: "/api/v1/auth/logout", "auth-service", 3),
    ("POST", lambda: "/api/v1/auth/password/reset", "auth-service", 1),
    ("GET", lambda: "/api/v1/cart", "order-service", 6),
    ("POST", lambda: "/api/v1/cart/items", "order-service", 6),
    ("DELETE", lambda: f"/api/v1/cart/items/{sku()}", "order-service", 2),
    ("POST", lambda: "/api/v1/coupons/apply", "order-service", 2),
    ("GET", lambda: "/api/v1/orders", "order-service", 6),
    ("GET", lambda: f"/api/v1/orders/{order()}", "order-service", 6),
    ("POST", lambda: "/api/v1/orders", "order-service", 5),
    ("POST", lambda: f"/api/v1/orders/{order()}/cancel", "order-service", 1),
    ("POST", lambda: "/api/v1/payments", "payment-service", 5),
    ("GET", lambda: f"/api/v1/payments/{txn()}", "payment-service", 3),
    ("POST", lambda: f"/api/v1/payments/{txn()}/refund", "payment-service", 1),
    ("POST", lambda: "/api/v1/webhooks/stripe", "payment-service", 3),
    ("GET", lambda: f"/api/v1/shipments/{hexid(10)}/track", "shipping-service", 4),
    ("GET", lambda: "/api/v1/notifications", "notification-service", 3),
    ("GET", lambda: "/api/v1/reports/daily", "report-service", 1),
    ("GET", lambda: "/health", "api-gateway", 5),
    ("GET", lambda: "/ready", "api-gateway", 2),
    ("GET", lambda: "/metrics", "api-gateway", 2),
]
EP_WEIGHTS = [e[3] for e in ENDPOINTS]

# status -> (weight, level, log reason or None)
STATUSES = {
    200: (60, "INFO", None), 201: (9, "INFO", None), 202: (2, "INFO", None), 204: (4, "INFO", None),
    301: (1, "INFO", None), 304: (5, "INFO", None),
    400: (2, "WARNING", lambda: R.choice(["invalid JSON body", f"missing required field '{R.choice(['email', 'sku', 'quantity', 'address'])}'", "malformed query string"])),
    401: (3, "WARNING", lambda: R.choice(["missing or expired token", "invalid credentials", "jwt signature mismatch"])),
    403: (1, "WARNING", lambda: R.choice(["insufficient scope", "IP blocked by WAF rule", "account suspended"])),
    404: (3, "WARNING", lambda: R.choice(["resource not found", "no such product", "order does not exist"])),
    409: (1, "WARNING", lambda: R.choice(["duplicate entry", "version conflict", "order already cancelled"])),
    422: (1, "WARNING", lambda: f"validation failed field={R.choice(['email', 'phone', 'pincode', 'amount', 'quantity'])}"),
    429: (1, "WARNING", lambda: f"rate limit exceeded {R.randint(100, 300)}/100 req/min"),
    500: (1, "ERROR", lambda: R.choice(["unexpected error: NullPointerException", "unhandled exception: KeyError", "panic recovered in handler", "serialization failed"])),
    502: (0.5, "ERROR", lambda: f"bad gateway upstream={svc()} connection refused"),
    503: (0.5, "ERROR", lambda: f"service unavailable circuit breaker open upstream={svc()}"),
    504: (0.5, "ERROR", lambda: f"upstream timeout after {R.choice([5000, 10000, 30000])}ms upstream={svc()}"),
}
ST_CODES = list(STATUSES)
ST_WEIGHTS = [STATUSES[c][0] for c in ST_CODES]

MIDDLE = {  # downstream steps for each service (level, text-factory)
    "db": [("DEBUG", lambda: f"[db] SELECT * FROM {table()} WHERE id={R.randint(1, 999999)} rows={R.randint(0, 50)} {ms(1, 60)}ms"),
           ("DEBUG", lambda: f"[db] INSERT INTO {table()} id={R.randint(1, 999999)} {ms(1, 40)}ms"),
           ("DEBUG", lambda: f"[db] UPDATE {table()} SET status='{R.choice(['paid', 'shipped', 'active', 'done'])}' rows=1 {ms(1, 40)}ms")],
    "cache": [("DEBUG", lambda: f"[cache] GET {R.choice(['session', 'product', 'user', 'cart'])}:{hexid(8)} {R.choice(['hit', 'hit', 'miss'])}"),
              ("DEBUG", lambda: f"[cache] SET {R.choice(['session', 'product', 'user'])}:{hexid(8)} ttl={R.choice([60, 300, 1800, 3600])}s")],
    "event": [("INFO", lambda: f"[kafka] published topic={topic()} partition={R.randint(0, 11)} offset={R.randint(100000, 9999999)}")],
    "ext": [("INFO", lambda: f"[payment-service] stripe charge ok id={txn()} amount={money()} {cur()} {ms(120, 900)}ms"),
            ("INFO", lambda: f"[shipping-service] courier api ok carrier={R.choice(['delhivery', 'bluedart', 'fedex', 'dhl'])} {ms(80, 600)}ms"),
            ("INFO", lambda: f"[notification-service] sendgrid accepted to={email()} {ms(50, 400)}ms")],
}


def middle_line(service):
    kind = R.choice(["db", "db", "cache", "event", "ext"] if service != "api-gateway" else ["cache"])
    return R.choice(MIDDLE[kind])


def api_call():
    """Return a list of lines (level, text) for one API request lifecycle."""
    method, pathf, service, _ = R.choices(ENDPOINTS, EP_WEIGHTS)[0]
    path = pathf()
    rid = hexid()
    code = R.choices(ST_CODES, ST_WEIGHTS)[0]
    _, level, reason = STATUSES[code]
    lines = [("INFO", f'[api-gateway] --> {method} {path} client={pubip()} req_id={rid} ua="{ua()}"')]
    if path not in ("/health", "/ready", "/metrics") and "/auth/" not in path:
        lines.append(("DEBUG", f"[auth-service] token validated req_id={rid} user_id={uid()} scopes={R.choice(['read', 'read,write', 'admin'])}"))
    for _ in range(R.randint(0, 3)):
        lvl, f = middle_line(service)
        lines.append((lvl, f"{f()} req_id={rid}"))
    if reason:
        lines.append((level, f"[{service}] {method} {path} failed: {reason()} req_id={rid}"))
    if code >= 500:
        dur = R.choice([ms(800, 2500), ms(5000, 30000)])
    elif code == 429 or code == 400:
        dur = ms(1, 30)
    else:
        dur = R.choices([ms(2, 90), ms(90, 400), ms(400, 2500)], [75, 20, 5])[0]
    size = 0 if code in (204, 304) else R.randint(60, 48000)
    final_level = level
    if level == "INFO" and dur > 1500:
        lines.append(("WARNING", f"[api-gateway] slow request {method} {path} took {dur}ms req_id={rid}"))
    lines.append((final_level, f"[api-gateway] <-- {method} {path} {code} {dur}ms bytes={size} req_id={rid}"))
    return lines


# --------------------------------------------------------- background / system
BACKGROUND = {
    "INFO": [
        lambda: f"[auth-service] session created user_id={uid()} ip={pubip()} device={R.choice(['android', 'ios', 'web'])}",
        lambda: f"[auth-service] token refreshed user_id={uid()} ttl=3600s",
        lambda: f"[auth-service] password changed user_id={uid()}",
        lambda: f"[user-service] profile updated user_id={uid()} fields={R.choice(['phone', 'address', 'avatar', 'name,email'])}",
        lambda: f"[user-service] new signup user_id={uid()} email={email()} source={R.choice(['organic', 'google_ads', 'referral', 'play_store'])}",
        lambda: f"[order-service] order created order_id={order()} items={R.randint(1, 8)} total={money()} {cur()}",
        lambda: f"[order-service] order status changed order_id={order()} {R.choice(['PLACED->PACKED', 'PACKED->SHIPPED', 'SHIPPED->DELIVERED', 'PLACED->CANCELLED'])}",
        lambda: f"[order-service] coupon applied code={R.choice(['WELCOME10', 'FESTIVE20', 'FREESHIP', 'NEWUSER50'])} discount={money()}",
        lambda: f"[payment-service] payment captured txn={txn()} amount={money()} {cur()} gateway={R.choice(['stripe', 'razorpay', 'paypal'])}",
        lambda: f"[payment-service] refund processed txn={txn()} amount={money()} {cur()}",
        lambda: f"[payment-service] settlement batch uploaded count={R.randint(50, 900)} total={money()}",
        lambda: f"[inventory-service] stock updated {sku()} qty={R.randint(0, 800)} warehouse=WH-{R.choice(['BLR', 'DEL', 'MUM', 'HYD'])}",
        lambda: f"[inventory-service] restock received {sku()} qty={R.randint(50, 500)} po=PO-{R.randint(1000, 9999)}",
        lambda: f"[shipping-service] shipment dispatched id={hexid(10)} carrier={R.choice(['delhivery', 'bluedart', 'fedex'])} order_id={order()}",
        lambda: f"[shipping-service] delivery confirmed id={hexid(10)} pincode={R.randint(110000, 799999)}",
        lambda: f"[search-service] index refreshed docs={R.randint(10000, 900000)} took={R.randint(1, 40)}s",
        lambda: f"[recommendation-service] model reloaded version=v{R.randint(1, 9)}.{R.randint(0, 30)} size={R.randint(40, 900)}MB",
        lambda: f"[notification-service] email sent to={email()} template={R.choice(['order_confirmation', 'shipping_update', 'password_reset', 'welcome'])}",
        lambda: f"[notification-service] sms sent to=+91{R.randint(7000000000, 9999999999)} provider=twilio",
        lambda: f"[notification-service] push delivered device={hexid(12)} topic={R.choice(['offers', 'order_updates'])}",
        lambda: f"[scheduler] job started name={job()} id={hexid(6)}",
        lambda: f"[scheduler] job completed name={job()} duration={R.randint(1, 120)}s processed={R.randint(0, 20000)}",
        lambda: f"[report-service] daily report generated rows={R.randint(1000, 500000)} size={R.randint(1, 80)}MB",
        lambda: f"[cache] hit ratio={R.randint(80, 99)}% keys={R.randint(10000, 900000)} mem={R.randint(200, 900)}MB",
        lambda: f"[db] replication lag={R.randint(0, 40)}ms replica=db-replica-{R.randint(1, 3)}",
        lambda: f"[db] checkpoint complete buffers={R.randint(100, 9000)} write={R.randint(1, 30)}s",
        lambda: f"[kafka] consumer group=order-workers lag={R.randint(0, 300)} topic={topic()}",
        lambda: f"[kafka] consumed topic={topic()} partition={R.randint(0, 11)} offset={R.randint(100000, 9999999)}",
        lambda: f"[s3] uploaded key=exports/{R.randint(2024, 2026)}/{hexid(10)}.csv bucket=prod-assets size={R.randint(1, 900)}KB",
        lambda: f"[health] liveness probe ok pod={pod()} uptime={R.randint(10, 999999)}s",
        lambda: f"[health] readiness probe ok pod={pod()}",
        lambda: f"[k8s] pod started {pod()} node=ip-10-0-{R.randint(0, 255)}-{R.randint(1, 254)}.{region()}.internal",
        lambda: f"[k8s] hpa scaled deployment={svc()} replicas={R.randint(2, 4)}->{R.randint(4, 8)} cpu={R.randint(60, 90)}%",
        lambda: f"[deploy] rollout complete service={svc()} version=2.{R.randint(1, 20)}.{R.randint(0, 30)} replicas={R.randint(2, 8)}",
        lambda: f"[config] configuration reloaded keys={R.randint(10, 80)} source=consul",
        lambda: f"[tls] certificate valid domain=api.example.com expires_in={R.randint(20, 80)}d",
        lambda: f"[lb] backend healthy target={ip()}:8080 pool={svc()}",
        lambda: f"[metrics] scrape ok targets={R.randint(20, 60)} duration={ms(20, 400)}ms",
        lambda: f"[backup] snapshot completed id=snap-{hexid(8)} size={R.randint(5, 400)}GB",
        lambda: f"[cdn] cache purge completed paths={R.randint(1, 500)} region={region()}",
        lambda: f"[feature-flag] flag toggled name={R.choice(['new_checkout', 'dark_mode', 'fast_search', 'upi_v2'])} enabled={R.choice(['true', 'false'])}",
    ],
    "DEBUG": [
        lambda: f"[db] acquired connection pool_id={R.randint(1, 20)} in_use={R.randint(1, 18)}/20",
        lambda: f"[db] released connection pool_id={R.randint(1, 20)} idle={R.randint(1, 15)}",
        lambda: f"[db] prepared statement cache size={R.randint(50, 400)}",
        lambda: f"[cache] eviction ran removed={R.randint(0, 600)} keys",
        lambda: f"[http] keep-alive reused conn={hexid(6)} upstream={svc()}",
        lambda: f"[http] dns resolved host={svc()}.internal -> {ip()} ttl={R.randint(5, 60)}s",
        lambda: f"[auth-service] jwks refreshed kid={hexid(6)}",
        lambda: f"[scheduler] next run in {R.randint(5, 900)}s job={job()}",
        lambda: f"[kafka] heartbeat sent group=order-workers generation={R.randint(1, 90)}",
        lambda: f"[gc] pause {R.randint(2, 120)}ms heap={R.randint(200, 900)}MB/{R.choice([1024, 2048])}MB",
        lambda: f"[threadpool] active={R.randint(2, 30)} queued={R.randint(0, 12)} max=64",
        lambda: f"[grpc] stream opened peer={svc()} id={hexid(6)}",
        lambda: f"[trace] span exported trace_id={hexid(16)} spans={R.randint(2, 30)}",
        lambda: f"[config] env=production region={region()} build={hexid(7)}",
    ],
    "WARNING": [
        lambda: f"[db] connection pool usage high {R.randint(85, 98)}% ({R.randint(17, 19)}/20)",
        lambda: f"[db] slow query {ms(1200, 6000)}ms table={table()} rows={R.randint(1000, 90000)}",
        lambda: f"[db] replication lag high {R.randint(800, 9000)}ms replica=db-replica-{R.randint(1, 3)}",
        lambda: f"[auth-service] failed login attempt user_id={uid()} ip={pubip()} attempts={R.randint(2, 5)}",
        lambda: f"[auth-service] suspicious login from new location user_id={uid()} country={R.choice(['RU', 'CN', 'BR', 'NG', 'VN'])}",
        lambda: f"[payment-service] retrying gateway call attempt={R.randint(1, 3)}/3 reason={R.choice(['timeout', '503', 'connection reset'])}",
        lambda: f"[payment-service] fraud score high txn={txn()} score={R.randint(70, 99)}",
        lambda: f"[cache] memory usage {R.randint(80, 95)}% eviction rate rising",
        lambda: f"[cache] latency {ms(40, 300)}ms above threshold node=redis-{R.randint(1, 6)}",
        lambda: f"[system] disk usage {R.randint(78, 92)}% on /var/lib/data",
        lambda: f"[system] cpu usage {R.randint(82, 97)}% pod={pod()}",
        lambda: f"[system] memory usage {R.randint(82, 96)}% pod={pod()} limit=1024MB",
        lambda: f"[api-gateway] rate limit nearly exceeded client={pubip()} {R.randint(90, 99)}/100 req/min",
        lambda: f"[api-gateway] deprecated endpoint called path=/api/v0/{R.choice(['orders', 'users', 'items'])} client={pubip()}",
        lambda: f"[inventory-service] low stock {sku()} qty={R.randint(1, 5)}",
        lambda: f"[kafka] consumer lag growing group=order-workers lag={R.randint(2000, 90000)} topic={topic()}",
        lambda: f"[kafka] rebalance triggered group=order-workers members={R.randint(2, 8)}",
        lambda: f"[tls] certificate expiring soon domain=api.example.com expires_in={R.randint(3, 14)}d",
        lambda: f"[lb] backend unhealthy target={ip()}:8080 removing from pool",
        lambda: f"[scheduler] job overran name={job()} duration={R.randint(300, 1800)}s expected=120s",
        lambda: f"[notification-service] email bounced to={email()} reason=mailbox_full",
        lambda: f"[shipping-service] courier api slow carrier={R.choice(['delhivery', 'bluedart', 'fedex'])} {ms(3000, 9000)}ms",
        lambda: f"[k8s] pod restarted {pod()} reason=Liveness probe failed restarts={R.randint(1, 4)}",
        lambda: f"[gc] long pause {R.randint(600, 3000)}ms heap={R.randint(800, 1000)}MB/1024MB",
        lambda: f"[threadpool] queue backlog active=64/64 queued={R.randint(50, 400)}",
        lambda: f"[config] unknown config key ignored key={R.choice(['legacy.timeout', 'feature.old_ui', 'cache.v1'])}",
    ],
    "ERROR": [
        lambda: f"[db] query failed: deadlock detected table={table()} retry_in={ms(50, 500)}ms",
        lambda: f"[db] query timeout after 30000ms table={table()}",
        lambda: f"[db] constraint violation table={table()} constraint=uniq_{R.choice(['email', 'order_ref', 'sku'])}",
        lambda: f"[cache] redis command failed: READONLY You can't write against a read only replica node=redis-{R.randint(1, 6)}",
        lambda: f"[payment-service] payment declined txn={txn()} code={R.choice(['card_declined', 'insufficient_funds', 'expired_card', 'do_not_honor'])}",
        lambda: f"[payment-service] webhook signature verification failed source=stripe ip={pubip()}",
        lambda: f"[payment-service] gateway error txn={txn()} status=502 body='upstream connect error'",
        lambda: f"[order-service] failed to reserve stock order_id={order()} {sku()} available=0",
        lambda: f"[order-service] order processing failed order_id={order()} err=InvalidStateTransition",
        lambda: f"[inventory-service] stock mismatch {sku()} expected={R.randint(10, 100)} actual={R.randint(0, 9)}",
        lambda: f"[notification-service] smtp send failed to={email()} err=connection reset by peer",
        lambda: f"[notification-service] push failed device={hexid(12)} err=InvalidRegistration",
        lambda: f"[kafka] produce failed topic={topic()} err=RequestTimedOut retries=3",
        lambda: f"[kafka] deserialization error topic={topic()} offset={R.randint(100000, 9999999)} skipping record",
        lambda: f"[s3] upload failed bucket=prod-assets key={hexid(10)}.csv err=SlowDown",
        lambda: f"[auth-service] invalid token signature client={pubip()}",
        lambda: f"[search-service] index shard unavailable shard={R.randint(0, 9)} index=products_v{R.randint(1, 4)}",
        lambda: f"[shipping-service] courier api error carrier={R.choice(['delhivery', 'bluedart', 'fedex'])} status={R.choice([500, 502, 503])}",
        lambda: f"[scheduler] job failed name={job()} err={R.choice(['TimeoutError', 'ConnectionError', 'OperationalError'])} retry={R.randint(1, 3)}/3",
        lambda: f"[report-service] report generation failed rows={R.randint(1000, 90000)} err=out of temporary disk space",
        lambda: f"[http] upstream connect error upstream={svc()} err=connection refused",
        lambda: f"[grpc] call failed peer={svc()} code=DEADLINE_EXCEEDED",
        lambda: f"[k8s] image pull failed pod={pod()} err=ErrImagePull registry rate limited",
        lambda: f"[backup] snapshot failed id=snap-{hexid(8)} err=AccessDenied",
        lambda: f"[config] consul unreachable using last known config age={R.randint(10, 600)}s",
    ],
    "CRITICAL": [
        lambda: f"[db] primary database unreachable host=db-primary-{R.randint(1, 3)} failing over to replica",
        lambda: f"[system] disk full on /var/lib/data writes are failing pod={pod()}",
        lambda: f"[payment-service] payment gateway down, all transactions failing since {datetime.now(timezone.utc).strftime('%H:%M:%S')}",
        lambda: f"[tls] certificate expired domain=api.example.com clients are failing handshakes",
        lambda: f"[cache] redis cluster down no quorum nodes_alive={R.randint(0, 2)}/6",
        lambda: f"[kafka] broker unavailable controller lost isr=0 topic={topic()}",
        lambda: f"[k8s] node NotReady node=ip-10-0-{R.randint(0, 255)}-{R.randint(1, 254)} evicting {R.randint(5, 30)} pods",
        lambda: f"[auth-service] signing key unavailable cannot issue tokens",
        lambda: f"[security] possible data exfiltration detected user_id={uid()} download={R.randint(1, 20)}GB ip={pubip()}",
    ],
}
LEVELS = [("INFO", 66), ("DEBUG", 14), ("WARNING", 12), ("ERROR", 6), ("CRITICAL", 0.6)]


# ----------------------------------------------------------------- crashes
def restart(s, attempt=1):
    return [
        ("WARNING", f"[supervisor] restarting {s} attempt={attempt}/5 backoff={R.randint(1, 5)}s"),
        ("INFO", f"[{s}] starting pid={R.randint(10000, 19999)} version=2.{R.randint(1, 20)}.{R.randint(0, 30)}"),
        ("INFO", f"[{s}] loaded config, connecting to dependencies"),
        ("INFO", f"[{s}] ready, accepting traffic"),
    ]


def crash_oom():
    s = R.choice(["order-service", "inventory-service", "notification-service", "report-service"])
    return [
        ("WARNING", f"[{s}] heap usage {R.randint(96, 99)}% gc pause {R.randint(800, 2500)}ms"),
        ("CRITICAL", f"[{s}] OutOfMemoryError: Java heap space (used=1024MB limit=1024MB)"),
        ("CRITICAL", f"[{s}] process pid={R.randint(100, 9999)} killed by kernel exit_code=137 (OOMKilled)"),
    ] + restart(s)


def crash_python():
    s = R.choice(["payment-service", "order-service", "recommendation-service"])
    err = R.choice([("KeyError", "'customer_id'"), ("TypeError", "unsupported operand type(s) for +: 'NoneType' and 'int'"),
                    ("ValueError", "invalid literal for int() with base 10: 'null'"), ("AttributeError", "'NoneType' object has no attribute 'id'")])
    return [
        ("CRITICAL", f"[{s}] unhandled exception in worker thread, shutting down"),
        ("ERROR", "Traceback (most recent call last):"),
        ("ERROR", f'  File "/srv/{s}/handlers.py", line {R.randint(40, 300)}, in handle_request'),
        ("ERROR", "    result = process(payload)"),
        ("ERROR", f'  File "/srv/{s}/core.py", line {R.randint(10, 200)}, in process'),
        ("ERROR", "    return compute(payload)"),
        ("ERROR", f"{err[0]}: {err[1]}"),
        ("CRITICAL", f"[{s}] exited with code 1"),
    ] + restart(s)


def crash_java():
    s = R.choice(["order-service", "inventory-service", "payment-service"])
    return [
        ("CRITICAL", f"[{s}] fatal error in request processing thread http-nio-8080-exec-{R.randint(1, 40)}"),
        ("ERROR", "java.lang.NullPointerException: Cannot invoke \"com.shop.model.Cart.getItems()\" because \"cart\" is null"),
        ("ERROR", f"\tat com.shop.{s.split('-')[0]}.CheckoutService.process(CheckoutService.java:{R.randint(40, 300)})"),
        ("ERROR", f"\tat com.shop.{s.split('-')[0]}.api.Controller.handle(Controller.java:{R.randint(20, 150)})"),
        ("ERROR", "\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:883)"),
        ("ERROR", "\tat org.apache.catalina.core.StandardWrapperValve.invoke(StandardWrapperValve.java:197)"),
        ("CRITICAL", f"[{s}] liveness probe failed 3 times, container will be killed"),
    ] + restart(s)


def crash_node():
    s = R.choice(["notification-service", "api-gateway", "search-service"])
    return [
        ("CRITICAL", f"[{s}] unhandledRejection: process will exit"),
        ("ERROR", "TypeError: Cannot read properties of undefined (reading 'userId')"),
        ("ERROR", f"    at handleEvent (/app/src/handlers/event.js:{R.randint(10, 200)}:{R.randint(5, 40)})"),
        ("ERROR", "    at processTicksAndRejections (node:internal/process/task_queues:95:5)"),
        ("CRITICAL", f"[{s}] exited with code 1"),
    ] + restart(s)


def crash_go():
    s = R.choice(["shipping-service", "scheduler", "api-gateway"])
    return [
        ("CRITICAL", f"[{s}] panic: runtime error: invalid memory address or nil pointer dereference"),
        ("ERROR", f"goroutine {R.randint(10, 900)} [running]:"),
        ("ERROR", f"main.(*Handler).Serve(0xc000{hexid(6)}, 0x{hexid(8)})"),
        ("ERROR", f"\t/go/src/{s}/handler.go:{R.randint(30, 250)} +0x{hexid(3)}"),
        ("ERROR", "net/http.HandlerFunc.ServeHTTP(0x0, {0x9a1b60, 0xc000123456}, 0xc0001a2000)"),
        ("CRITICAL", f"[{s}] exit status 2"),
    ] + restart(s)


def crash_segfault():
    s = R.choice(["api-gateway", "search-service", "scheduler"])
    return [
        ("CRITICAL", f"[{s}] SIGSEGV: segmentation fault at address 0x{hexid(12)}"),
        ("CRITICAL", f"[{s}] core dumped to /var/crash/core.{R.randint(1000, 99999)}"),
    ] + restart(s)


def crash_db_lost():
    return [
        ("ERROR", "[db] connection lost: server closed the connection unexpectedly"),
        ("WARNING", "[db] reconnect attempt=1/3 backoff=1s"),
        ("WARNING", "[db] reconnect attempt=2/3 backoff=2s"),
        ("ERROR", "[db] reconnect attempt=3/3 failed: connection refused"),
        ("CRITICAL", "[db] all reconnect attempts exhausted, service degraded"),
        ("WARNING", "[health] readiness probe failing, removing pod from load balancer"),
        ("INFO", f"[db] connection re-established to db-primary-{R.randint(1, 3)}"),
        ("INFO", "[health] readiness probe ok, pod back in rotation"),
    ]


def crash_crashloop():
    s = svc()
    p = pod(s)
    return [
        ("ERROR", f"[k8s] container {s} in pod {p} terminated reason=Error exit_code=1"),
        ("WARNING", f"[k8s] Back-off restarting failed container {s} in pod {p}"),
        ("ERROR", f"[k8s] pod {p} status=CrashLoopBackOff restarts={R.randint(3, 9)}"),
        ("CRITICAL", f"[k8s] deployment {s} has {R.randint(1, 3)} unavailable replicas, alerting on-call"),
        ("INFO", f"[deploy] rollback started service={s} to_version=2.{R.randint(1, 20)}.{R.randint(0, 30)}"),
        ("INFO", f"[deploy] rollback complete service={s}"),
    ]


def crash_threads():
    s = R.choice(["order-service", "payment-service", "api-gateway"])
    return [
        ("WARNING", f"[{s}] thread pool saturated active=64/64 queued={R.randint(200, 900)}"),
        ("ERROR", f"[{s}] RejectedExecutionException: task rejected from ThreadPoolExecutor"),
        ("CRITICAL", f"[{s}] deadlock detected between threads worker-{R.randint(1, 30)} and worker-{R.randint(31, 60)}"),
        ("CRITICAL", f"[{s}] watchdog timeout, killing process"),
    ] + restart(s)


def crash_disk():
    return [
        ("WARNING", f"[system] disk usage {R.randint(94, 99)}% on /var/lib/data"),
        ("ERROR", "[db] could not write to file pg_wal/xlog: No space left on device"),
        ("CRITICAL", "[db] PANIC: could not write to WAL, shutting down"),
        ("CRITICAL", "[system] disk full, all writes failing"),
        ("INFO", f"[backup] emergency cleanup removed {R.randint(5, 80)}GB of old logs"),
        ("INFO", "[db] database system is ready to accept connections"),
    ]


CRASHES = [crash_oom, crash_python, crash_java, crash_node, crash_go, crash_segfault,
           crash_db_lost, crash_crashloop, crash_threads, crash_disk]

# ------------------------------------------------------------------- engine
counter = 0
running = True


def emit(level, text):
    global counter
    counter += 1
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z " if WITH_TS else ""
    sys.stdout.write(f"{counter:06d} {ts}{level:<8} {text}\n")
    sys.stdout.flush()


def stop(*_):
    global running
    running = False


def background():
    level = R.choices([l for l, _ in LEVELS], [w for _, w in LEVELS])[0]
    return level, R.choice(BACKGROUND[level])()


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    emit("INFO", "[boot] live-log-api starting")
    emit("INFO", f"[boot] region={region()} env=production services={len(SERVICES)}")
    emit("INFO", "[boot] ready")

    inflight = []  # API calls whose remaining lines are still to be printed
    burst = 0
    try:
        while running:
            if R.random() < CRASH_PROB:
                for level, text in R.choice(CRASHES)():
                    emit(level, text)
                    time.sleep(R.uniform(0.05, 0.4))
            else:
                r = R.random()
                if inflight and (r < 0.55 or len(inflight) > 40):
                    flow = R.choice(inflight)
                    emit(*flow.pop(0))
                    if not flow:
                        inflight.remove(flow)
                elif r < 0.85:
                    flow = api_call()
                    emit(*flow.pop(0))
                    if flow:
                        inflight.append(flow)
                else:
                    emit(*background())

            if burst:
                burst -= 1
                time.sleep(R.uniform(0.0, 0.03))
            else:
                if R.random() < BURST_PROB:
                    burst = R.randint(8, 30)
                time.sleep(R.uniform(MIN_DELAY, MAX_DELAY))
    except BrokenPipeError:
        return

    emit("INFO", "[boot] shutdown signal received, exiting")


if __name__ == "__main__":
    main()
