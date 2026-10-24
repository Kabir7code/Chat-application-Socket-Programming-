# Deviations from Submitted Documents

Real-Time Chat Application Using Socket Programming. Software Engineering (UE23CS341A), PES University.

This file lists every place where the Sprint 1 build differs from the SRS, the SAD, the Test Cases or the sprint process in the deliverables sheet, and why. It is updated at the end of each sprint and is what we will walk through in the final demo.

Last updated: 24 Oct 2026, after Sprint 1.

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
