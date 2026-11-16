# Final test run (17 Nov 2026)

A re-run of every test after two changes made after the Part-3 testing: the #53 web-history fix (branch `fix/web-history-53`) and sending images, videos and documents (branch `feature/send-files`). The Part-3 reports in [`Documents/Test_Reports/`](..) (11 Nov) are unchanged; this folder only adds the newer results.

**Code tested:** `main` (1a9fed9) merged with `fix/web-history-53` (ca47ede) and `feature/send-files` (0dea331), Python 3.13, Linux.

| Check | Result | Files |
|---|---|---|
| flake8 | Clean | `flake8.txt` |
| Unit and integration tests (`tests/`) | **394 passed**, 0 failed | `unit_tests.txt`, `unit_test_report.html`, `junit_unit.xml` |
| System validation tests (`system_tests/`) | **20 passed**, one per requirement (FR-001 to FR-013, NFR-001 to NFR-007) | `system_tests.txt`, `junit_system.xml` |
| Code coverage (`chat` package, `tests/` suite) | **89.8% of lines, 84.1% of branches** (targets 80% and 75%) | `coverage.json`, `coverage_html/index.html` |
| The 88 documented test cases | **85 Pass, 2 Partial (UT_02, UT_03), 1 not re-run (ST_06)** | `test_case_results.json` |
| 20 users, 200 messages, 2,000 deliveries | Nothing lost; median 48 ms, slowest 59 ms (limit 1 second) | `performance_20_users.json` |

Notes:

- **UT_02, UT_03 Partial:** same as Part-3. The web page blocks bad usernames before sending; the terminal client leaves the check to the server (bug #29, Deviations B4).
- **ST_06** is the 10-minute idle case and was not repeated here; it passed in the Part-3 run.
- **ST_19** first failed in this run only because its script expected exactly 5 database tables, and file sharing adds a sixth (`files`). The app was correct; the script now expects the `files` table too (pushed on `feature/send-files`), and ST_19 passes.
- Coverage is a little lower than the 91.5% / 86.1% in the Part-3 reports because those also counted code run inside separately started server and client programs; this run counts the `tests/` suite only.

Re-running: see [`../README.md`](../README.md#re-running).
