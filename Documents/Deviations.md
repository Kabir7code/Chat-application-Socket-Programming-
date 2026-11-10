# Deviations from Submitted Documents

Real-Time Chat Application Using Socket Programming. Software Engineering (UE23CS341A), PES University.

This file lists every place where the build differs from the SRS, the SAD, the Test Cases or the sprint process in the deliverables sheet, and why. It is updated at the end of each sprint and is what we will walk through in the final demo.

Last updated: 11 Nov 2026, after Sprint 3 and the Part-3 testing (sections 5 to 8). Sections 1 to 4 are the Sprint 1 entries; their current status is in section 5.

## 1. Process

| # | Deviation | Reason | Action |
|---|---|---|---|
| P1 | PRs #25 (Joshua) and #26 (Keerthana) were merged by their authors, not by the repo owner. The deliverables sheet says repo owners should review and merge. | Both PRs were raised correctly by the assignees and passed CI, but they merged them themselves before the repo owner had reviewed them. | For Sprint 2, only the repo owner merges. |
| P2 | Backlog item #23 (GitHub Actions) is not in the SRS. | Required by the deliverables sheet (Sprint 1, point b) rather than by a requirement. | Kept as a process item. |
| P3 | Backlog item #9 (thread-safe client list) is not listed in the SRS requirement-to-backlog table. | Found to be needed while building concurrent sessions; it supports NFR-002 and NFR-003. | Mapped to NFR-002 on the board. |

## 2. Requirements and design

| # | Deviation | Reason | Action |
|---|---|---|---|
| D1 | Username rules are now fixed: 1 to 20 letters, digits or underscores, and case-sensitive ("Rahul" and "rahul" are different). The SRS did not define them. | Needed a definite rule to implement FR-001 and to test IT_03. | Documented in the SAD (sections 6.2 and 11.2). |
| D2 | Usernames are validated by the server, not the client. UT_02 and UT_03 expected the client to block empty or too-long names before sending. | Keeping the rule in one place means every client gets the same check. The user still sees a clear error and can retry. | Add matching checks to the client in Sprint 2 so no request is sent. Bug #29. |
| D3 | Chat messages have no message ID. UT_07 expected one. | Not needed for any Sprint 1 feature. | Add an ID in Sprint 2 together with timestamps (#13). Bug #30. |
| D4 | Maximum message length is 4000 characters. Test cases UT_09 and UT_15 use 1000 as an example limit. | 1000 was only an example in the test cases; 4000 fits a long paragraph comfortably. | Limit documented in the SAD. Tests passed against the 4000 limit. |
| D5 | Added protocol details not in the SRS: length-prefixed JSON framing, message types and error codes. | TCP does not keep messages separate, so framing was needed to meet NFR-003. | Fully documented in the SAD, section 6. |

## 3. Features moved or not yet complete

| # | Item | Status |
|---|---|---|
| F1 | On-screen list of online users (/users, #7) | Sprint 2. Join and leave notices work now, so IT_18 and IT_19 are marked Partial. |
| F2 | Server logging (#14) | Sprint 2. UT_24 failed because errors are handled but not logged. |
| F3 | TLS encryption (second half of NFR-005, #22) | Sprint 2. The first half (rejecting unregistered sockets) is done. |
| F4 | GUI client (#16) | Sprint 2, as planned. Sprint 1 uses a terminal client. |

## 4. Defects found in Sprint 1 testing

| # | Test case | Problem | Plan |
|---|---|---|---|
| B1 | IT_08 | When several users send at exactly the same moment, two other users can see those messages in a different order (4 times in 300 runs). Never seen with normal back-to-back messages. | Serialise broadcasts in the server in Sprint 2. Bug #31. |
| B2 | UT_02, UT_03 | See D2. | Sprint 2. Bug #29. |
| B3 | UT_07 | See D3. | Sprint 2. Bug #30. |

Full results are in the Test Cases document: 42 Pass, 4 Partial, 5 Fail, 15 Not executed (they need group chat, a Sprint 2 feature).

## 5. Status of the Sprint 1 entries

| # | Status after Sprint 3 |
|---|---|
| D2, B2 | **Still open.** Bug #29 was closed, but the change it asks for was never made to the terminal client: only a mock-up file (`Client-should-validate-username-before-sending.jsx`) was added at the repository root. The web UI does check names before sending (empty name blocked; the box stops at 20 characters). UT_02 and UT_03 are therefore Partial. See B4. |
| D3, B3 | Fixed in Sprint 2: every message has an ID and a timestamp (#30, #13). UT_07 passes. |
| B1 | Fixed in Sprint 2 (#31): broadcasts are sent under one lock. IT_08 passed 200 out of 200 simultaneous-send rounds in each of 4 runs. |
| F1 | Done in Sprint 2 (#7): `/users` and the web UI's online list. IT_18 and IT_19 now pass. |
| F2 | Done in Sprint 2 (#14): logging with time, level, user and traceback. UT_24 passes. |
| F3 | Done in Sprint 2 (#22): TLS encryption. |
| F4 | Done in Sprint 2 (#16) as a web page served on localhost by `python -m chat.web`, rather than a desktop window. It needs no extra libraries and works the same on every laptop. |

## 6. Sprint 3 (optional sprint for spill-over: saving the chat)

| # | Deviation | Reason | Action |
|---|---|---|---|
| S1 | Requirements FR-011 (saved messages and history on login), FR-012 (private history, offline messages), FR-013 (groups survive a restart), NFR-006 (data survives a restart) and NFR-007 (database size kept in check) were added to the backlog (#50 to #61). They are not in the SRS document. | Part-3 allows an extra sprint; the team used it to make the chat persistent, which the SRS had left out. | Traced and validated in the System Validation Report and the Test Cases document. |
| S2 | IT_16 changed: a private message to someone who has used the chat but is offline is now kept and delivered at their next login, instead of returning "User not found/offline". | Intended behaviour of FR-012 (#59). | Test case updated. A name that never logged in still gets the error (UT_14). |
| S3 | The "Testing" week in the Part-3 sheet (2 to 6 Nov) overlapped Sprint 3 (5 to 11 Nov). | Sprint 3 changed the same features, so testing them before it finished would have had to be redone. | All 88 test cases were run on the complete Sprint 3 code on 11 Nov; the Test Plan schedule records this. |
| S4 | Several Sprint 3 uploads put their files at the top of the repository instead of in `chat/`, `tests/` or `Documents/` (PRs #66, #67, #68, #69, #70). The app did not use those files. | Files were dragged into GitHub's upload page one by one instead of as folders. | #66 and #67 were fixed before merging; #69 and #70 are fixed by PR #71. #53 (PR #68) must be uploaded again. The upload instructions now say to drag the folders and check the paths before committing. |
| S5 | Sprint 3 pull requests were merged in a different order from the plan. | Team members uploaded when they were ready. | Conflicts were resolved and each later upload was rebuilt on top of what was already merged. |

## 7. Defects found in Part-3 testing

| # | Test case | Problem | Plan |
|---|---|---|---|
| B4 | UT_02, UT_03 | The terminal client sends an empty or too-long username to the server instead of rejecting it first. The server rejects it with a clear message, so nothing breaks. | Reopen #29 and add the check to `register()` in `chat/client.py`. |
| B5 | Found while testing (not a test case) | `ChatServer.stop()` closes the database while a client thread may still be handling a message. Seen once: a user logging in during shutdown got a server error, which was logged. | Low priority. Close sessions and wait for their threads before closing the store. |
| B6 | ST_21 | After a server restart, a private chat appears in the web UI's chat list only when the other person is online or sends a new message; its saved history then loads. There is no list of past private conversations. | Low priority. History is not lost (`/history <user>` also works). Possible future item. |

## 8. Part-3 test results

Full results are in the Test Cases document and `Documents/Test_Reports/`:

- 88 test cases (66 from Sprints 1 and 2, 9 of them updated, plus 22 new for Sprint 3): 86 Pass, 2 Partial (UT_02, UT_03), 0 Fail, 0 Not executed. Every case was run 4 times with the same result (ST_06, the 10-minute idle case, once).
- Automated suite: 338 tests pass on Python 3.10, 3.12 and 3.13; flake8 is clean.
- Line coverage 91.5%, branch coverage 86.1% (targets 80% and 75%).
- 20 users, 2,000 deliveries: none lost, slowest 61 ms (limit 1 second).

