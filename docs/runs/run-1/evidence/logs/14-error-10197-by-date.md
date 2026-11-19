# Error 10197 (competing live session), count of log lines per local date since 2026-10-08

Source: logs/approval.log, logs/monitor.log, logs/spreads.log, counting lines that contain `10197` (a single event often logs several lines, one per contract). Dates are local (UTC+8).
Supports: README section 9 'Competing IBKR login (Nov 18)', whose list (Oct 8, 9, 10, 13, 14, 15, 20, 23, 27, 29, 30; Nov 3, 12, 15, 19) is the union over approval.log and monitor.log; spreads.log adds Nov 7 and Nov 11.

| local date | approval.log | monitor.log | spreads.log | first line (file:line, time) |
|---|---|---|---|---|
| 2026-10-08 |  | 114 |  | monitor:94556 04:10:32 |
| 2026-10-09 | 5 | 53 |  | approval:657054 00:01:40 |
| 2026-10-10 | 7 | 376 |  | approval:664823 00:08:40 |
| 2026-10-13 |  | 30 |  | monitor:97386 06:02:43 |
| 2026-10-14 |  | 10 |  | monitor:97835 12:23:24 |
| 2026-10-15 |  | 128 |  | monitor:98092 00:16:21 |
| 2026-10-20 | 4 | 543 |  | approval:689620 01:33:07 |
| 2026-10-23 | 4 | 629 |  | approval:700475 22:32:15 |
| 2026-10-27 | 4 | 1156 |  | approval:705194 03:02:04 |
| 2026-10-29 |  | 155 |  | monitor:108370 12:09:56 |
| 2026-10-30 | 4 | 647 |  | approval:713438 00:02:32 |
| 2026-11-03 |  | 10 |  | monitor:110615 17:31:55 |
| 2026-11-07 |  |  | 3 | spreads:15998 01:50:13 |
| 2026-11-11 |  |  | 1 | spreads:16268 04:09:08 |
| 2026-11-12 |  | 7 | 1 | monitor:115764 20:20:09 |
| 2026-11-15 |  | 5 |  | monitor:116185 04:50:12 |
| 2026-11-19 | 8 | 417 |  | approval:756904 02:35:38 |

Distinct local dates: 17 (approval.log and monitor.log alone: 15).
