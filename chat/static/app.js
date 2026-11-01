"use strict";

const $ = (id) => document.getElementById(id);
const USERNAME_PATTERN = /^[A-Za-z0-9_]{1,20}$/;
const EVERYONE = "everyone";

const state = {
  session: null,
  username: null,
  events: null,
  online: [],
  groups: new Map(), // group name -> member list
  selectedGroup: null,
  syncedGroup: null, // the selected group last copied into the group name box
  silentUserLists: 0, // list_users replies that only refresh the sidebar
  connected: false,
};

// ------------------------------------------------------------------- API
async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  return { status: response.status, data };
}

async function send(message) {
  const { status, data } = await post("/api/send", { session: state.session, message });
  reportFailure(status, data);
}

async function runCommand(line) {
  const { status, data } = await post("/api/command", { session: state.session, line });
  if (reportFailure(status, data)) return;
  if (data.local) addMessage(data.local, "local");
  if (data.quit) showJoinScreen();
}

function reportFailure(status, data) {
  if (status === 200) return false;
  if (status === 404 || status === 502) markDisconnected();
  else addMessage(`! ${data.error || "Request failed."}`, "error");
  return true;
}

// ------------------------------------------------------------- join / leave
$("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = $("username").value.trim();
  if (!USERNAME_PATTERN.test(username)) {
    $("join-error").textContent = "Use 1-20 letters, digits or underscores.";
    return;
  }
  $("join-error").textContent = "";
  let reply;
  try {
    reply = await post("/api/connect", { username });
  } catch {
    $("join-error").textContent = "Could not reach the web gateway.";
    return;
  }
  if (reply.status !== 200) {
    $("join-error").textContent = reply.data.error || "Could not join.";
    return;
  }
  startChat(reply.data);
});

function startChat({ session, username, users, encrypted }) {
  Object.assign(state, {
    session, username, online: users, groups: new Map(),
    selectedGroup: null, syncedGroup: null, silentUserLists: 0, connected: true,
  });
  $("me").textContent = username;
  $("security").textContent = encrypted ? "Encrypted (TLS)" : "Not encrypted";
  $("status").textContent = "";
  $("messages").replaceChildren();
  $("group-name").value = "";
  $("member-name").value = "";
  $("text").value = "";
  $("join-screen").hidden = true;
  $("chat-screen").hidden = false;
  setSendingEnabled(true);
  renderSidebar();
  openEvents();
  refreshOnline();
  $("text").focus();
}

function openEvents() {
  const url = `/api/events?session=${encodeURIComponent(state.session)}`;
  state.events = new EventSource(url);
  state.events.onmessage = (event) => handleEvent(JSON.parse(event.data));
  state.events.onerror = markDisconnected;
}

function closeEvents() {
  if (state.events) state.events.close();
  state.events = null;
}

function markDisconnected() {
  if (!state.connected) return;
  state.connected = false;
  closeEvents();
  setSendingEnabled(false);
  $("status").textContent = "Disconnected from server";
  addMessage("Disconnected from server", "error");
}

function setSendingEnabled(enabled) {
  const controls = "#send-form input, #send-form select, #send-form button, " +
    ".panel input, .panel button";
  document.querySelectorAll(controls).forEach((control) => { control.disabled = !enabled; });
}

function showJoinScreen() {
  state.connected = false;
  closeEvents();
  state.session = null;
  $("chat-screen").hidden = true;
  $("join-screen").hidden = false;
  $("username").focus();
}

$("leave").addEventListener("click", async () => {
  const session = state.session;
  closeEvents();
  showJoinScreen();
  if (session) await post("/api/disconnect", { session }).catch(() => {});
});

// Closing or reloading the tab leaves the chat straight away.
window.addEventListener("pagehide", () => {
  if (!state.session || !state.connected) return;
  const body = new Blob([JSON.stringify({ session: state.session })], { type: "application/json" });
  navigator.sendBeacon("/api/disconnect", body);
});

// ---------------------------------------------------------- incoming events
function handleEvent(message) {
  switch (message.type) {
    case "disconnected":
      markDisconnected();
      return;
    case "users":
      state.online = message.users;
      renderSidebar();
      if (state.silentUserLists > 0) {
        state.silentUserLists -= 1;
        return;
      }
      break;
    case "system":
      refreshOnline();
      break;
    case "group_update":
      applyGroupUpdate(message);
      break;
    default:
  }
  addMessage(message.display, styleFor(message));
}

function styleFor(message) {
  switch (message.type) {
    case "private":
    case "private_sent":
      return "private";
    case "system":
    case "users":
    case "group_update":
      return "notice";
    case "error":
      return "error";
    case "chat": {
      const classes = [];
      if (message.context === "group") classes.push("group");
      if (message.history) classes.push("history");
      if (message.self) classes.push("mine");
      return classes.join(" ");
    }
    default:
      return "";
  }
}

function refreshOnline() {
  state.silentUserLists += 1;
  send({ type: "list_users" }).catch(markDisconnected);
}

function applyGroupUpdate({ group, members }) {
  if (members.includes(state.username)) {
    state.groups.set(group, members);
    if (!state.selectedGroup) state.selectedGroup = group;
  } else {
    state.groups.delete(group);
    if (state.selectedGroup === group) {
      state.selectedGroup = state.groups.keys().next().value || null;
    }
  }
  renderSidebar();
}

// ---------------------------------------------------------------- rendering
function addMessage(text, classes) {
  const list = $("messages");
  const item = document.createElement("li");
  item.textContent = text; // textContent, so a message can never inject HTML
  if (classes) item.className = classes;
  list.append(item);
  list.scrollTop = list.scrollHeight;
}

function renderNames(listId, names, emptyText, makeItem) {
  const items = names.map((name) => {
    const item = document.createElement("li");
    item.append(makeItem(name));
    return item;
  });
  if (items.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = emptyText;
    items.push(empty);
  }
  $(listId).replaceChildren(...items);
}

function nameButton(label, onClick, selected = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.title = label;
  button.disabled = !state.connected;
  if (selected) button.classList.add("selected");
  button.addEventListener("click", onClick);
  return button;
}

function plainName(name) {
  const text = document.createElement("div");
  text.className = "plain";
  text.textContent = name;
  return text;
}

function renderSidebar() {
  const others = state.online.filter((name) => name !== state.username);
  renderNames("online", state.online, "Nobody online", (name) => (
    name === state.username
      ? plainName(`${name} (you)`)
      : nameButton(name, () => chooseTarget(`user:${name}`))
  ));

  const groupNames = [...state.groups.keys()].sort();
  renderNames("my-groups", groupNames, "No groups yet", (name) => nameButton(name, () => {
    state.selectedGroup = name;
    chooseTarget(`group:${name}`);
    renderSidebar();
  }, name === state.selectedGroup));

  renderTargets(others, groupNames);

  const selected = state.selectedGroup;
  $("members-title").textContent = selected ? `Members of ${selected}` : "Members";
  if (selected !== state.syncedGroup) { // only when the selection changes, not while typing
    state.syncedGroup = selected;
    $("group-name").value = selected || "";
  }
  renderNames("members", selected ? state.groups.get(selected) : [],
    "Select a group", plainName);
}

function renderTargets(users, groups) {
  const target = $("target");
  const current = target.value || EVERYONE;
  const options = [new Option("Everyone", EVERYONE)];
  users.forEach((name) => options.push(new Option(`${name} (private)`, `user:${name}`)));
  groups.forEach((name) => options.push(new Option(`Group: ${name}`, `group:${name}`)));
  target.replaceChildren(...options);
  target.value = options.some((option) => option.value === current) ? current : EVERYONE;
}

function chooseTarget(value) {
  $("target").value = value;
  $("text").focus();
}

// ------------------------------------------------------------------ sending
$("send-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("text");
  const text = input.value;
  if (!text.trim() || !state.connected) return;
  input.value = "";
  const action = text.startsWith("/") ? runCommand(text) : send(messageFor(text));
  action.catch(markDisconnected);
});

function messageFor(text) {
  const target = $("target").value;
  if (target.startsWith("user:")) return { type: "private", to: target.slice(5), text };
  if (target.startsWith("group:")) return { type: "group", group: target.slice(6), text };
  return { type: "chat", text };
}

function groupAction(type) {
  const group = $("group-name").value.trim();
  if (!group) {
    addMessage("! Enter a group name first.", "error");
    $("group-name").focus();
    return;
  }
  send({ type, group }).catch(markDisconnected);
}

$("create-group").addEventListener("click", () => groupAction("create_group"));
$("join-group").addEventListener("click", () => groupAction("join_group"));
$("leave-group").addEventListener("click", () => groupAction("leave_group"));

$("add-member").addEventListener("click", () => {
  const group = $("group-name").value.trim();
  const username = $("member-name").value.trim();
  if (!group || !username) {
    addMessage("! Enter a group name and a username first.", "error");
    return;
  }
  $("member-name").value = "";
  send({ type: "add_member", group, username }).catch(markDisconnected);
});
