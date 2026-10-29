import React, { useState } from "react";

const acceptanceCriteria = [
  "Users can connect, view users, create/join groups, send messages and leave from the GUI",
  "GUI works with the existing server without protocol changes",
];

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
    fontSize: "clamp(25px, 3vw, 46px)",
    fontWeight: 400,
    lineHeight: 1.3,
    letterSpacing: "-0.7px",
    margin: "0 0 16px",
    overflowWrap: "anywhere",
  },
  muted: { color: "#9198a1" },
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
    whiteSpace: "nowrap",
  },
  statusIcon: {
    width: 23,
    height: 23,
    border: "2px solid white",
    borderRadius: "50%",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
  },
  repo: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    border: "1px solid #30363d",
    borderRadius: 30,
    padding: "9px 16px",
    color: "#8b949e",
    fontSize: 16,
    flexWrap: "wrap",
  },
  publicBadge: {
    color: "#f0f6fc",
    background: "#21262d",
    borderRadius: 20,
    padding: "4px 11px",
    fontWeight: 600,
  },
  layout: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 2.5fr) minmax(240px, 0.95fr)",
    gap: 46,
    alignItems: "start",
  },
  card: {
    border: "1px solid #3d444d",
    borderRadius: 9,
    overflow: "hidden",
    minWidth: 0,
  },
  meta: {
    minHeight: 56,
    padding: "9px 12px",
    borderBottom: "1px solid #30363d",
    background: "#161b22",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    flexWrap: "wrap",
  },
  author: { display: "flex", alignItems: "center", gap: 10, fontSize: 16 },
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
    fontSize: 25,
  },
  metaRight: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    color: "#8b949e",
    fontSize: 15,
    flexWrap: "wrap",
  },
  owner: {
    border: "1px solid #30363d",
    borderRadius: 20,
    padding: "4px 10px",
  },
  content: { padding: "24px 24px 22px", fontSize: 18, lineHeight: 1.55 },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    marginBottom: 34,
    fontSize: 17,
    lineHeight: 1.4,
  },
  th: {
    border: "1px solid #3d444d",
    padding: "10px 13px",
    textAlign: "center",
    whiteSpace: "nowrap",
    fontWeight: 600,
  },
  td: {
    border: "1px solid #3d444d",
    padding: "10px 13px",
    textAlign: "center",
    whiteSpace: "nowrap",
  },
  sectionHeading: { fontSize: 24, margin: "0 0 22px", fontWeight: 600 },
  paragraph: { margin: "0 0 34px" },
  criteriaList: { display: "flex", flexDirection: "column", gap: 15 },
  criterion: {
    display: "flex",
    alignItems: "flex-start",
    gap: 12,
    cursor: "pointer",
    lineHeight: 1.55,
  },
  checkbox: {
    width: 21,
    height: 21,
    flexShrink: 0,
    margin: "5px 0 0",
    accentColor: "#238636",
    cursor: "pointer",
  },
  menu: { color: "#8b949e", marginLeft: "auto", paddingLeft: 10, letterSpacing: 2 },
  divider: { border: 0, borderTop: "1px solid #3d444d", margin: "32px 0 24px" },
  actionRow: { display: "flex", gap: 10, flexWrap: "wrap" },
  actionButton: {
    border: "1px solid #3d444d",
    background: "#21262d",
    color: "#f0f6fc",
    borderRadius: 8,
    padding: "10px 13px",
    fontSize: 15,
    fontWeight: 600,
  },
  sidebar: { color: "#8b949e", fontSize: 16 },
  sidebarSection: { borderBottom: "1px solid #30363d", paddingBottom: 20, marginBottom: 20 },
  sidebarTitle: { color: "#8b949e", margin: "0 0 16px", fontWeight: 500, fontSize: 16 },
  assignee: { display: "flex", alignItems: "center", gap: 10, color: "#f0f6fc", fontWeight: 600 },
  miniAvatar: {
    width: 33,
    height: 33,
    borderRadius: "50%",
    background: "#e6edf3",
    color: "#80b9e9",
    display: "inline-flex",
    justifyContent: "center",
    alignItems: "center",
    border: "1px solid #8b949e",
  },
  labels: { display: "flex", flexWrap: "wrap", gap: 6 },
  label: {
    border: "1px solid #405b83",
    background: "#172b4d",
    color: "#79b8ff",
    borderRadius: 20,
    padding: "4px 11px",
    fontSize: 15,
    whiteSpace: "nowrap",
  },
  featureLabel: { background: "#172b4d", borderColor: "#405b83", color: "#79b8ff" },
  nonFunctional: { background: "#292044", borderColor: "#51417d", color: "#d2c2ff" },
  priority: { background: "#382b1b", borderColor: "#765326", color: "#f0883e" },
  projectCard: {
    border: "1px solid #3d444d",
    borderRadius: 9,
    overflow: "hidden",
    color: "#f0f6fc",
  },
  projectHead: { padding: 16, borderBottom: "1px solid #3d444d" },
  projectName: { display: "flex", alignItems: "center", gap: 12, fontWeight: 600, marginBottom: 18 },
  statusLine: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 },
  progress: {
    background: "#382b1b",
    color: "#e3a13b",
    border: "1px solid #765326",
    borderRadius: 20,
    padding: "4px 10px",
    whiteSpace: "nowrap",
  },
  projectFields: { padding: "16px 20px", display: "grid", gap: 24 },
  fieldRow: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 },
  fieldLabel: { color: "#8b949e" },
  value: { color: "#f0f6fc" },
};

export default function GitHubIssueNFR004() {
  const [checkedItems, setCheckedItems] = useState([]);

  const toggleCriterion = (index) => {
    setCheckedItems((previous) =>
      previous.includes(index)
        ? previous.filter((item) => item !== index)
        : [...previous, index]
    );
  };

  return (
    <div className="issue-root" style={styles.page}>
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; background: #0d1117; }
        .issue-root { min-height: 100vh; }
        .criterion-text.completed { color: #8b949e; text-decoration: line-through; }
        .issue-toolbar { position: absolute; right: 28px; top: 38px; color: #8b949e; font-size: 25px; display: flex; gap: 28px; }
        @media (max-width: 1050px) {
          .issue-layout { grid-template-columns: minmax(0, 1fr) !important; gap: 24px !important; }
          .issue-toolbar { display: none; }
        }
        @media (max-width: 650px) {
          .issue-root { padding: 20px 12px !important; }
          .issue-content { padding: 16px 14px !important; }
          .issue-table-wrap { overflow-x: auto; }
          .issue-table { min-width: 700px; }
          .criterion-menu { display: none; }
        }
      `}</style>

      <div className="issue-toolbar" aria-hidden="true">
        <span>▢</span><span>♧</span><span>•••</span><span>×</span>
      </div>

      <header>
        <h1 style={styles.title}>
          [NFR-004] Simple GUI client{" "}
          <span style={styles.muted}>#16</span>
          <span style={{ ...styles.muted, fontSize: 24, marginLeft: 16 }}>✎</span>
        </h1>

        <div style={styles.badges}>
          <span style={styles.status}><span style={styles.statusIcon}>•</span> Open</span>
          <span style={styles.repo}>
            <span style={{ fontSize: 20 }}>▣</span>
            Kabir7code/Chat-application-Socket-Programming-
            <span style={styles.publicBadge}>Public</span>
          </span>
        </div>
      </header>

      <div className="issue-layout" style={styles.layout}>
        <main style={styles.card}>
          <div style={styles.meta}>
            <div style={styles.author}>
              <div style={styles.avatar}>✚</div>
              <span><strong style={{ fontSize: 19 }}>Kabir7code</strong>{" "}
                <span style={styles.muted}>opened 27d ago</span>
              </span>
            </div>
            <div style={styles.metaRight}>
              <span>Last edited by KeerthanaK0304</span>
              <span style={{ fontSize: 12 }}>▼</span>
              <span style={styles.owner}>Owner</span>
              <span style={{ letterSpacing: 2 }}>•••</span>
            </div>
          </div>

          <section className="issue-content" style={styles.content}>
            <div className="issue-table-wrap">
              <table className="issue-table" style={styles.table}>
                <thead>
                  <tr>
                    {["SRS Req", "Category", "Priority", "Story Points", "Sprint", "Assignee"].map((heading) => (
                      <th key={heading} style={styles.th}>{heading}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td style={styles.td}>NFR-004</td>
                    <td style={styles.td}>feature</td>
                    <td style={styles.td}>Medium</td>
                    <td style={styles.td}>8</td>
                    <td style={styles.td}>Sprint 2</td>
                    <td style={{ ...styles.td, color: "#d29922", textDecoration: "underline" }}>@KeerthanaK0304</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <h2 style={styles.sectionHeading}>Description</h2>
            <p style={styles.paragraph}>
              A simple, user-friendly interface, kept separate from server and chat-management code.
            </p>

            <h2 style={styles.sectionHeading}>Acceptance criteria</h2>
            <div style={styles.criteriaList}>
              {acceptanceCriteria.map((criterion, index) => {
                const checked = checkedItems.includes(index);
                return (
                  <label key={criterion} style={styles.criterion}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleCriterion(index)}
                      style={styles.checkbox}
                    />
                    <span className={`criterion-text${checked ? " completed" : ""}`}>{criterion}</span>
                    <span className="criterion-menu" style={styles.menu}>•••</span>
                  </label>
                );
              })}
            </div>

            <hr style={styles.divider} />
            <div style={styles.actionRow}>
              <button type="button" style={styles.actionButton}>Create sub-issue　⌄</button>
              <button type="button" style={styles.actionButton}>Add artifact</button>
              <button type="button" aria-label="Add reaction" style={{ ...styles.actionButton, borderRadius: "50%", fontSize: 19, padding: "5px 10px" }}>☺</button>
            </div>
          </section>
        </main>

        <aside style={styles.sidebar}>
          <section style={styles.sidebarSection}>
            <h3 style={styles.sidebarTitle}>Assignees <span style={{ float: "right" }}>⚙</span></h3>
            <div style={styles.assignee}>
              <span style={styles.miniAvatar}>▦</span>
              <span>KeerthanaK0304</span>
            </div>
          </section>

          <section style={styles.sidebarSection}>
            <h3 style={styles.sidebarTitle}>Labels <span style={{ float: "right" }}>⚙</span></h3>
            <div style={styles.labels}>
              <span style={styles.label}>Sprint 2</span>
              <span style={{ ...styles.label, ...styles.featureLabel }}>feature</span>
              <span style={{ ...styles.label, ...styles.nonFunctional }}>non-functional</span>
              <span style={{ ...styles.label, ...styles.priority }}>priority: medium</span>
            </div>
          </section>

          <section style={styles.sidebarSection}>
            <h3 style={styles.sidebarTitle}>Projects <span style={{ float: "right" }}>⚙</span></h3>
            <div style={styles.projectCard}>
              <div style={styles.projectHead}>
                <div style={styles.projectName}><span style={{ fontSize: 22, color: "#8b949e" }}>▦</span> Chat App - Backlog</div>
                <div style={styles.statusLine}>
                  <span style={styles.fieldLabel}>Status</span>
                  <span style={styles.progress}>In progress　⌄</span>
                  <span style={{ color: "#8b949e", fontSize: 20 }}>⌃</span>
                </div>
              </div>
              <div style={styles.projectFields}>
                <div style={styles.fieldRow}>
                  <span style={styles.fieldLabel}>Story Points</span>
                  <span style={styles.value}>8</span>
                </div>
                <div style={styles.fieldRow}>
                  <span style={styles.fieldLabel}>Sprint</span>
                  <span style={styles.value}>Sprint 2 ·<br /><span style={{ color: "#8b949e" }}>Oct 26 - Oct 30 · </span><span style={{ color: "#58a6ff" }}>Current</span></span>
                </div>
                <div style={styles.fieldRow}>
                  <span style={styles.fieldLabel}>Priority</span>
                  <span><span style={{ ...styles.label, background: "#161b22", borderColor: "#3d444d", color: "#8b949e" }}>Medium</span></span>
                </div>
              </div>
            </div>
          </section>

          <section>
            <h3 style={styles.sidebarTitle}>Milestone <span style={{ float: "right" }}>⚙</span></h3>
          </section>
        </aside>
      </div>
    </div>
  );
}
