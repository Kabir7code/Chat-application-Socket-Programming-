import React, { useState } from "react";

const criteria = [
  "Empty name is rejected on the client with 'Username cannot be empty'",
  "Names over 20 characters are rejected on the client with 'Username exceeds maximum length'",
  "No register message is sent in either case",
  "Server-side check stays as a backup",
];

export default function GitHubIssue() {
  const [checkedItems, setCheckedItems] = useState([]);

  const toggleCriteria = (index) => {
    setCheckedItems((previous) =>
      previous.includes(index)
        ? previous.filter((item) => item !== index)
        : [...previous, index]
    );
  };

  const styles = {
    page: {
      minHeight: "100vh",
      padding: "28px 32px",
      background: "#0d1117",
      color: "#f0f6fc",
      fontFamily:
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
      boxSizing: "border-box",
    },
    title: {
      fontSize: "clamp(24px, 3.1vw, 46px)",
      fontWeight: 400,
      lineHeight: 1.35,
      letterSpacing: "-0.8px",
      margin: "0 0 16px",
      overflowWrap: "anywhere",
    },
    issueNumber: {
      color: "#9198a1",
      textDecoration: "underline",
      textDecorationColor: "#484f58",
    },
    editIcon: {
      color: "#9198a1",
      fontSize: 24,
      marginLeft: 18,
      verticalAlign: "middle",
    },
    badges: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      flexWrap: "wrap",
      marginBottom: 34,
    },
    status: {
      display: "inline-flex",
      alignItems: "center",
      gap: 7,
      padding: "12px 18px",
      background: "#347d39",
      borderRadius: 30,
      fontSize: 19,
      fontWeight: 600,
    },
    statusIcon: {
      fontSize: 15,
      border: "2px solid white",
      borderRadius: "50%",
      width: 23,
      height: 23,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
    },
    repo: {
      display: "inline-flex",
      alignItems: "center",
      gap: 7,
      border: "1px solid #30363d",
      borderRadius: 30,
      padding: "10px 18px",
      color: "#8b949e",
      fontSize: 16,
      flexWrap: "wrap",
    },
    visibility: {
      color: "#f0f6fc",
      background: "#21262d",
      borderRadius: 20,
      padding: "4px 11px",
      fontWeight: 600,
      whiteSpace: "nowrap",
    },
    card: {
      border: "1px solid #3d444d",
      borderRadius: 9,
      overflow: "hidden",
      width: "100%",
    },
    meta: {
      minHeight: 58,
      padding: 10,
      borderBottom: "1px solid #30363d",
      background: "#161b22",
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      gap: 15,
      flexWrap: "wrap",
    },
    author: { display: "flex", alignItems: "center", gap: 9, fontSize: 16 },
    avatar: {
      width: 38,
      height: 38,
      flexShrink: 0,
      borderRadius: "50%",
      background: "#e6edf3",
      color: "#9bcf83",
      border: "2px solid #8b949e",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: 26,
    },
    muted: { color: "#8b949e" },
    editorMeta: {
      display: "flex",
      alignItems: "center",
      gap: 9,
      color: "#8b949e",
      fontSize: 15,
      flexWrap: "wrap",
    },
    owner: {
      border: "1px solid #30363d",
      borderRadius: 20,
      padding: "4px 10px",
    },
    content: {
      padding: "10px 24px 30px",
      fontSize: 19,
      lineHeight: 1.65,
    },
    paragraph: { margin: "15px 0 24px" },
    heading: { marginTop: 32, marginBottom: 22, fontSize: 24, fontWeight: 600 },
    criteriaList: { display: "flex", flexDirection: "column", gap: 15 },
    criterion: {
      display: "flex",
      alignItems: "flex-start",
      gap: 12,
      cursor: "pointer",
      lineHeight: 1.6,
    },
    checkbox: {
      appearance: "none",
      width: 21,
      height: 21,
      flexShrink: 0,
      margin: "5px 0 0",
      border: "1px solid #6e7681",
      borderRadius: 5,
      background: "transparent",
      cursor: "pointer",
      accentColor: "#238636",
    },
    menu: {
      color: "#8b949e",
      marginLeft: "auto",
      paddingLeft: 12,
      letterSpacing: 2,
      fontSize: 16,
    },
  };

  return (
    <div style={styles.page}>
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; background: #0d1117; }
        .issue-checkbox:checked {
          accent-color: #238636;
        }
        .criterion-text.completed {
          color: #8b949e;
          text-decoration: line-through;
        }
        @media (max-width: 650px) {
          .github-page-content { padding: 10px 14px 24px !important; font-size: 16px !important; }
          .criteria-menu { display: none !important; }
          .github-page-root { padding: 20px 12px !important; }
        }
      `}</style>

      <header>
        <h1 style={styles.title}>
          Client should validate username before sending (UT_02, UT_03){" "}
          <span style={styles.issueNumber}>#29</span>
          <span style={styles.editIcon}>✎</span>
        </h1>

        <div style={styles.badges}>
          <span style={styles.status}>
            <span style={styles.statusIcon}>•</span> Open
          </span>
          <span style={styles.repo}>
            <span style={{ fontSize: 20 }}>▣</span>
            Kabir7code/Chat-application-Socket-Programming-
            <span style={styles.visibility}>Public</span>
          </span>
        </div>
      </header>

      <main style={styles.card}>
        <div style={styles.meta}>
          <div style={styles.author}>
            <div style={styles.avatar}>✚</div>
            <span>
              <strong style={{ fontSize: 19 }}>Kabir7code</strong>{" "}
              <span style={styles.muted}>opened 5d ago</span>
            </span>
          </div>

          <div style={styles.editorMeta}>
            <span>
              Last edited by <strong>KeerthanaK0304</strong>
            </span>
            <span style={{ fontSize: 12 }}>▼</span>
            <span style={styles.owner}>Owner</span>
            <span style={{ marginLeft: 8, fontSize: 19, letterSpacing: 2 }}>
              •••
            </span>
          </div>
        </div>

        <section className="github-page-content" style={styles.content}>
          <p style={styles.paragraph}>
            Found while running the Sprint 1 test cases.
          </p>

          <p style={styles.paragraph}>
            <strong>Expected (UT_02, UT_03):</strong> the client blocks an
            empty username with 'Username cannot be empty' and a too-long one
            with 'Username exceeds maximum length', without contacting the
            server.
          </p>

          <p style={styles.paragraph}>
            <strong>Actual:</strong> the client sends the name anyway and the
            server rejects it with 'Username must be 1-20 letters, digits or
            underscores.'
          </p>

          <h2 style={styles.heading}>Acceptance criteria</h2>

          <div style={styles.criteriaList}>
            {criteria.map((criterion, index) => {
              const checked = checkedItems.includes(index);
              return (
                <label style={styles.criterion} key={criterion}>
                  <input
                    className="issue-checkbox"
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleCriteria(index)}
                    style={styles.checkbox}
                  />
                  <span
                    className={`criterion-text${checked ? " completed" : ""}`}
                  >
                    {criterion}
                  </span>
                  <span className="criteria-menu" style={styles.menu}>
                    •••
                  </span>
                </label>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
