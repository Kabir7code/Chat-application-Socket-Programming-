# Final documents (course templates, version 2.1)

These are the final versions of the SRS, the Software Architecture Document and the Test Plan, written in the course templates (SRS template, SAD template, Test Plan template) on 17 Nov 2026 (updated 19 Nov for audio sharing), after Sprint 3, the Part-3 testing and the file-sharing feature.

The earlier versions submitted during the project are kept unchanged in [`Documents/`](..):
`Requirements_SRS_Chat_Application_Socket_Programming.docx`, `Software_Architecture_Document.docx` (v1.1) and `Test_Plan.docx` (v1.1).

| Document | Files | What changed from the earlier version |
|---|---|---|
| Software Requirements Specification | `SRS_v2.1.docx` / `.pdf` | Course SRS template. Same requirement IDs (FR-001 to FR-013, NFR-001 to NFR-007) plus FR-014 (web page), FR-015 and FR-016 (file sharing); acceptance criteria and test case for every requirement; 4 security objectives and 15 security requirements; two use case diagrams; Requirements Traceability Matrix. |
| Software Architecture and Design Specification | `SAD_v2.1.docx` / `.pdf` | Course SAD template. Updated component and database diagrams (web gateway, TLS, file storage); three sequence diagrams; API design for the chat server and the web gateway; STRIDE threat model; risks, traceability, open issues. |
| Software Test Plan | `Test_Plan_v2.1.docx` / `.pdf` | Course Test Plan template, all 15 sections, with the real schedule, roles, security tests and final results. |

Diagram sources (PlantUML and Graphviz) and pictures are in [`diagrams/`](diagrams).

The documents describe the app with the #53 web-history fix and file sharing (images, videos, audio and documents) included. Test results: Part-3 run on 11 Nov (88 test cases, 86 pass, 2 partial; 338 automated tests; 91.5% line and 86.1% branch coverage), and the final run on 19 Nov (402 automated tests, 89.7% line and 84.3% branch coverage; see `Documents/Test_Reports/Final_Run/`). See [Deviations.md](../Deviations.md), section 9.
