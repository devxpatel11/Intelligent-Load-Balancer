# Scope and limitations

The completed A1-A5/B1-B5 implementation and B6 evidence audit remain limited to:

- an educational application-aware TCP proxy on loopback, not IP routing or a production load balancer;
- one request/response per connection, with no persistence, batching, transparent streaming, or replay;
- one service process and one Uvicorn worker, with in-memory state and no high availability;
- simulated backend delay/capacity, not measured server CPU or network bandwidth;
- application success/failure observations, not TCP packet-loss measurement;
- request-flow events, not packet capture;
- local HTTP with no TLS, authentication, database, cloud deployment, Docker, or Kubernetes;
- performance results that depend on the tested laptop and are not universal claims.

Optional LAN tests or packet capture require an explicit rubric need and come only after the core release gate.
