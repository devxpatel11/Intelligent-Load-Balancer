# Demonstration plan

The live demo is pending implementation. Do not treat these steps as verified commands until G5/G6 records successful execution.

1. Start three independently configured backend processes.
2. Start one service process with the proxy on TCP 9000 and dashboard/API on HTTP 8000.
3. Show all backends becoming healthy.
4. Run RR traffic and show cyclic assignment distribution.
5. Use a slow-server profile with concurrent traffic and show LC active reservations.
6. Use weights 5:3:2 and show SWRR configured distribution.
7. Stop and restart s2; show detection, exclusion, finite detection-window failures, and recovery without replay.
8. Show committed raw data/charts and the exact test evidence.
9. Stop the demo and confirm only owned child processes terminate and ports are reusable.

The operator must say “request flow,” not packet capture, and “application failures,” not packet loss. If the dashboard fails, the API output, CLI, and saved charts remain the fallback demonstration.
