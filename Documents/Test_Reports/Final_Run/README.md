# Final test run (19 Nov 2026)

Every test run again on the final code: Sprint 1 to 3, the #53 web-history fix, and sending images, videos, audio and documents. The Part-3 reports in [`Documents/Test_Reports/`](..) (11 Nov) are unchanged; this folder holds the final results.

**Code tested:** `main` after merging `fix/web-history-53` and `feature/send-files` (Python 3.13, Linux).

| Check | Result | Files |
|---|---|---|
| flake8 | No problems | `flake8.txt` |
| Unit and integration tests (`tests/`) | **402 passed**, 0 failed | `unit_tests.txt`, `unit_test_report.html`, `junit_unit.xml` |
| System validation tests (`system_tests/`) | **20 passed**, one per requirement (FR-001 to FR-013, NFR-001 to NFR-007) | `system_tests.txt`, `junit_system.xml` |
| Code coverage (`chat` package, `tests/` suite) | **89.7% of lines, 84.3% of branches** (targets 80% and 75%) | `coverage.json`, `coverage_html/index.html` |
| The 88 documented test cases | **86 Pass, 2 Partial (UT_02, UT_03), 0 Fail** | `test_case_results.json` |
| 20 users, 200 messages, 2,000 deliveries | Nothing lost; median 49 ms, slowest 68 ms (limit 1 second) | `performance_20_users.json` |

Notes:

- **UT_02, UT_03 Partial:** same as Part-3. The web page blocks bad usernames before sending; the terminal client leaves the check to the server (bug #29, Deviations B4).
- **ST_06** (both clients idle for 10 minutes, then a message) was run on its own and passed.
- **ST_19** checks the database tables; its script now expects the `files` table that file sharing added.
- Coverage is a little lower than the 91.5% / 86.1% in the Part-3 reports because those also counted code run inside separately started server and client programs; this run counts the `tests/` suite only.
- File sharing has 64 automated tests (`tests/test_files.py`, `tests/test_files_web.py`), and audio was also checked in a real browser (it plays in the chat; an 11 MB mp3 is refused).
