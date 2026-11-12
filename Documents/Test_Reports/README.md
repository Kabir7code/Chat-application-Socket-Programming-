# Test reports (Mini Project Part-3)

Testing of the chat application after Sprint 3, run on 11 Nov 2026 according to the [Test Plan](../Test_Plan.docx) (version 1.1).

| Report | Files | What it shows |
|---|---|---|
| Unit Test Report | `Unit_Test_Report.pdf` / `.docx`, `unit_test_report.html`, `junit*.xml` | The automated suite (338 tests, all passing on Python 3.10, 3.12 and 3.13) and the unit test cases UT_01 to UT_30 |
| System Validation Report | `System_Validation_Report.pdf` / `.docx`, `performance_20_users.json` | Every requirement (FR-001 to FR-013, NFR-001 to NFR-007) traced to its test cases, the IT and ST results, a 20-user delivery-time measurement and the defects found |
| Code Coverage Report | `Code_Coverage_Report.pdf` / `.docx`, `coverage_html/index.html`, `coverage.xml`, `coverage.json` | Line coverage: 91.5% of the `chat` package |
| Branch Coverage Report | `Branch_Coverage_Report.pdf` / `.docx`, same coverage files | Branch coverage: 86.1% |

**Test case results:** 88 cases, 86 Pass, 2 Partial (UT_02, UT_03), 0 Fail. They are filled in the [Test Cases document](../Test_Cases_Chat_Application_Socket_Programming.docx); the raw results are in `test_case_results.json`. Problems found are listed in [Deviations.md](../Deviations.md), sections 5 to 8.

Open `coverage_html/index.html` in a browser to see every module with its untested lines in red and partly tested branches in yellow.

## Screenshots (run on a team member's MacBook, Python 3.14, 12 Nov 2026)

| What | File |
|---|---|
| Unit and integration tests: 329 passed | [screenshots/unit_tests_mac.png](screenshots/unit_tests_mac.png) |
| Code and branch coverage table: 88% overall | [screenshots/code_and_branch_coverage_mac.png](screenshots/code_and_branch_coverage_mac.png) |
| System validation tests: 20 passed, one per requirement | [screenshots/system_validation_tests_mac.png](screenshots/system_validation_tests_mac.png) |

These runs are on main as of 12 Nov. The 88% here is lower than the 91.5% / 86.1% in the reports because the reports also counted the client and server when the tests start them as separate programs, and they include #53.

## Re-running

```
pip install -r requirements-dev.txt pytest-cov pytest-html
flake8 chat tests
pytest --cov=chat --cov-branch --cov-report=term-missing --cov-report=html --html=unit_test_report.html --self-contained-html
pytest system_tests -v                                                 # system validation tests (20)
python Documents/Test_Reports/run_test_cases.py . results.json        # all 88 test cases (needs Playwright + Chromium)
python Documents/Test_Reports/measure_performance.py . /tmp/load.db   # 20-user delivery times
```
